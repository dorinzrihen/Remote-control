import unittest
from unittest.mock import patch

from bonjour import Bonjour, txt_record


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

    def test_metadata_describes_trusted_lan_without_pairing(self):
        record = txt_record("10.100.102.19")
        entries = []
        while record:
            length = record[0]
            entries.append(record[1:length + 1])
            record = record[length + 1:]
        self.assertEqual([b"api=1", b"auth=none", b"address=10.100.102.19"], entries)

    def test_loopback_is_not_advertised(self):
        with patch("bonjour.sys.platform", "darwin"), patch("bonjour.threading.Thread") as thread:
            Bonjour("127.0.0.1", 8788).start()
            thread.assert_not_called()

    def test_registration_recovers_after_failure(self):
        bonjour = Bonjour("10.0.0.2", 8788)
        with patch.object(bonjour, "register") as register, patch.object(bonjour.stop, "wait", side_effect=lambda _: bonjour.stop.set()):
            bonjour.run()
        register.assert_called_once()
