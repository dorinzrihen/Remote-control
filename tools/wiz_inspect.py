#!/usr/bin/env python3
"""Read-only WiZ discovery/inventory or offline ESP firmware dispatch inspection.

Does not send setters, registration, resets, OTA or timetable payloads.
"""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import struct
import time


def inventory(broadcast, ips):
    found = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.25)
        for target in [broadcast, *ips]:
            sock.sendto(b'{"method":"getSystemConfig","params":{}}', (target, 38899))
        end = time.monotonic() + 3
        while time.monotonic() < end:
            try:
                data, source = sock.recvfrom(8192)
                reply = json.loads(data)
                if reply.get("method") == "getSystemConfig" and "result" in reply:
                    found[source[0]] = {"getSystemConfig": reply}
            except (socket.timeout, ValueError):
                continue
    for ip, responses in found.items():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((ip, 38899))
            sock.settimeout(1)
            for method in ("getModelConfig", "getUserConfig", "getPilot", "getTime", "getSchd", "getSchdPset"):
                sock.send(json.dumps({"method": method, "params": {}}).encode())
                end = time.monotonic() + 1
                while time.monotonic() < end:
                    try:
                        data = sock.recv(8192)
                        reply = json.loads(data)
                        if reply.get("method") == method:
                            responses[method] = reply
                            break
                    except (socket.timeout, ValueError):
                        break
                else:
                    responses[method] = {"observation": "timeout"}
                responses.setdefault(method, {"observation": "timeout"})
    return found


def firmware(path):
    """Find dispatch candidates; report raw flags, not an unverified capability.

    Unlike the upstream research script, do not assume segment zero is DROM
    or that every hardware variant shares the same addresses.
    """
    data = Path(path).read_bytes()
    if len(data) < 24 or data[0] != 0xE9:
        raise ValueError("Expected an uncompressed ESP image")
    segments, offset = [], 24
    for _ in range(data[1]):
        if offset + 8 > len(data):
            raise ValueError("Truncated segment header")
        address, length = struct.unpack_from("<II", data, offset)
        offset += 8
        if offset + length > len(data):
            raise ValueError("Truncated segment")
        segments.append((address, offset, length))
        offset += length

    def string(address):
        for base, start, length in segments:
            if base <= address < base + length:
                pos = start + address - base
                end = data.find(b"\0", pos, min(pos + 64, start + length))
                if end > pos:
                    try:
                        value = data[pos:end].decode("ascii")
                        if value.isidentifier():
                            return value
                    except UnicodeDecodeError:
                        pass
        return None

    entries = []
    for base, start, length in segments:
        for pos in range(start, start + length - 11, 4):
            name, target, flags = struct.unpack_from("<III", data, pos)
            # ESP32-C3 executable mappings. Other chip families need review.
            if not (0x42000000 <= target < 0x42800000 and 0 < flags < 0x100000):
                continue
            value = string(name)
            if value and value.startswith(("get", "set", "sync", "reg", "first", "pulse", "reset", "reboot", "update", "ping", "space")):
                entries.append({"method": value, "fileOffset": hex(pos), "handler": hex(target), "flags": hex(flags),
                                "udpFlagByte": (flags >> 8) & 255})
    return {"sha256": hashlib.sha256(data).hexdigest(), "segments": [{"address": hex(a), "fileOffset": hex(o), "length": n} for a, o, n in segments],
            "dispatchCandidates": entries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broadcast", default="255.255.255.255")
    parser.add_argument("--ip", action="append", default=[], help="Also query a known bulb IP")
    parser.add_argument("--firmware", type=Path, help="Offline analysis only; sends no network packets")
    parser.add_argument("--output", type=Path, help="Private inventory may include MAC/home/room identifiers")
    args = parser.parse_args()
    result = firmware(args.firmware) if args.firmware else inventory(args.broadcast, args.ip)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        # Do not silently overwrite a previous configuration snapshot.
        with args.output.open("x") as out:
            out.write(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
