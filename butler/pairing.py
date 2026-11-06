"""Explicit, local-only activation of a short-lived, single-use pairing code."""

import hashlib
import fcntl
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from contextlib import contextmanager


class Pairing:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            fd = os.open(self.path.with_suffix(".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
            with os.fdopen(fd, "w") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                yield

    def enable(self, now=None):
        now = time.time() if now is None else now
        code = f"{secrets.randbelow(1000000):06d}"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.locked():
            self.write({"digest": hashlib.sha256(code.encode()).hexdigest(),
                        "expires": now + 300, "attempts": 0})
        return code

    def write(self, value):
        temporary = self.path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
        temporary.replace(self.path)

    def redeem(self, code, now=None):
        now = time.time() if now is None else now
        with self.locked():
            try:
                value = json.loads(self.path.read_text())
            except FileNotFoundError:
                return False
            if now >= value["expires"] or value["attempts"] >= 5:
                return False
            value["attempts"] += 1
            valid = isinstance(code, str) and len(code) == 6 and code.isascii() and code.isdigit()
            matches = valid and hmac.compare_digest(value["digest"], hashlib.sha256(code.encode()).hexdigest())
            if matches:
                # Consume before returning credentials, including on a lost reply.
                self.path.unlink()
            else:
                self.write(value)
            return matches
