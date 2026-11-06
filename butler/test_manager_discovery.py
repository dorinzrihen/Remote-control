import hashlib
import hmac
import http.client
import json
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

from bonjour import Bonjour, txt_record
from pairing import Pairing
from wiz_butler import handler


class BonjourTest(unittest.TestCase):
    def test_registration_uses_macos_system_library_and_releases_reference(self):
        bonjour = Bonjour("10.100.102.19", 8788)
        bonjour.stop.set()
        with patch("bonjour.ctypes.CDLL") as load:
            library = load.return_value
            def register(reference, _flags, _interface, name, kind, _domain, _host, port, length, record, callback, _context):
                reference._obj.value = 123
                self.assertEqual(b"Butler Lights", name)
                self.assertEqual(b"_uniremote._tcp", kind)
                self.assertEqual(len(record), length)
                self.assertEqual(txt_record("10.100.102.19"), record)
                return 0
            library.DNSServiceRegister.side_effect = register
            bonjour.register()
            load.assert_called_once_with("/usr/lib/libSystem.B.dylib")
            library.DNSServiceRefDeallocate.assert_called_once()

    def test_metadata_contains_protocol_and_bound_address_only(self):
        record = txt_record("10.100.102.19")
        entries = []
        while record:
            length = record[0]
            entries.append(record[1:length + 1])
            record = record[length + 1:]
        self.assertEqual([b"api=1", b"pairing=code", b"address=10.100.102.19"], entries)

    def test_loopback_is_not_advertised(self):
        with patch("bonjour.sys.platform", "darwin"), patch("bonjour.threading.Thread") as thread:
            Bonjour("127.0.0.1", 8788).start()
            thread.assert_not_called()

    def test_registration_recovers_after_failure(self):
        bonjour = Bonjour("10.0.0.2", 8788)
        with patch.object(bonjour, "register") as register, patch.object(bonjour.stop, "wait", side_effect=lambda _: bonjour.stop.set()):
            bonjour.run()
        register.assert_called_once()


class PairingTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "pairing.json"
        self.pairing = Pairing(self.path)

    def test_explicit_activation_private_file_single_use(self):
        self.assertFalse(self.pairing.redeem("123456", now=1))
        code = self.pairing.enable(now=1)
        self.assertRegex(code, r"^[0-9]{6}$")
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))
        self.assertNotIn(code, self.path.read_text())
        self.assertTrue(self.pairing.redeem(code, now=2))
        self.assertFalse(self.pairing.redeem(code, now=3))

    def test_expires_in_five_minutes(self):
        code = self.pairing.enable(now=1)
        self.assertFalse(self.pairing.redeem(code, now=301))

    def test_five_wrong_attempts_lock_even_correct_code(self):
        code = self.pairing.enable(now=1)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.assertFalse(self.pairing.redeem(wrong, now=2))
        self.assertFalse(self.pairing.redeem(code, now=2))

    def test_new_code_revokes_old_code(self):
        with patch("pairing.secrets.randbelow", side_effect=[123456, 654321]):
            old = self.pairing.enable(now=1)
            new = self.pairing.enable(now=2)
        self.assertFalse(self.pairing.redeem(old, now=3))
        self.assertTrue(self.pairing.redeem(new, now=3))

    def test_concurrent_requests_only_redeem_once(self):
        code = self.pairing.enable()
        results = []
        workers = [threading.Thread(target=lambda: results.append(Pairing(self.path).redeem(code))) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(1, results.count(True))

    def test_http_pairing_and_identity_never_control_bulbs(self):
        butler = Mock()
        token = "x" * 32
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(butler, token, self.pairing))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def post(path, value):
            connection = http.client.HTTPConnection(*server.server_address)
            connection.request("POST", path, json.dumps(value))
            response = connection.getresponse()
            self.assertEqual("no-store", response.getheader("Cache-Control"))
            result = response.status, json.loads(response.read())
            connection.close()
            return result

        self.assertEqual(403, post("/v1/pair", {"code": "123456"})[0])
        code = self.pairing.enable()
        self.assertEqual((200, {"token": token}), post("/v1/pair", {"code": code}))
        self.assertEqual(403, post("/v1/pair", {"code": code})[0])
        nonce = "ab" * 32
        expected = hmac.new(token.encode(), ("uniremote-manager-v1:" + nonce).encode(), hashlib.sha256).hexdigest()
        self.assertEqual((200, {"proof": expected}), post("/v1/identity", {"nonce": nonce}))
        self.assertEqual(400, post("/v1/identity", {"nonce": "bad"})[0])
        self.assertEqual(401, post("/v1/room", {"mode": "ON"})[0])
        self.assertEqual([], butler.mock_calls)
