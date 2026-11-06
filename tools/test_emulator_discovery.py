import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import emulator_discovery as d


class DiscoveryTests(unittest.TestCase):
    def test_only_real_matching_ssdp_responses_become_devices(self):
        text = f"HTTP/1.1 200 OK\r\nST: {d.ST['lg']}\r\nServer: WebOS/4.1 UPnP/1.0\r\n"
        self.assertEqual(d.parse_response("lg", "192.168.1.9", text),
                         {"ip": "192.168.1.9", "name": "WebOS/4.1 UPnP/1.0"})
        self.assertIsNone(d.parse_response("samsung", "192.168.1.9", text))
        self.assertIsNone(d.parse_response("lg", "192.168.1.9", text.replace("200", "404")))
        self.assertIsNone(d.parse_response("lg", "192.168.1.1", "HTTP/1.1 200 OK\r\nST: upnp:rootdevice\r\nServer: router"))

    def test_discovery_only_sends_standard_msearch_and_deduplicates(self):
        sock = Mock()
        sock.__enter__ = Mock(return_value=sock)
        sock.__exit__ = Mock(return_value=False)
        packet = f"HTTP/1.1 200 OK\r\nST: {d.ST['samsung']}\r\nServer: Samsung TV\r\n".encode()
        sock.recvfrom.side_effect = [(packet, ("192.168.1.9", 1900)), (packet, ("192.168.1.9", 1900))]
        with patch.object(d.socket, "socket", return_value=sock), patch.object(d.time, "monotonic", side_effect=[0, 1, 2, 4]):
            devices = d.discover("samsung")
        self.assertEqual(devices, [{"ip": "192.168.1.9", "name": "Samsung TV"}])
        self.assertEqual(sock.sendto.call_count, 2)
        message, target = sock.sendto.call_args.args
        self.assertTrue(message.startswith(b"M-SEARCH * HTTP/1.1"))
        self.assertEqual(target, ("239.255.255.250", 1900))

    def test_http_bridge_loopback_read_only_routes(self):
        server = d.ThreadingHTTPServer(("127.0.0.1", 0), d.Handler)
        server.stop_key = "s" * 64
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            with patch.object(d, "discover", return_value=[{"ip": "192.168.1.9", "name": "TV"}]) as discover:
                with urlopen(base + "/discover/lg", timeout=2) as response:
                    self.assertEqual(json.load(response)["devices"][0]["name"], "TV")
                discover.assert_called_once_with("lg")
                for route in ("/power", "/discover/anything", "/v1/config"):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(base + route, timeout=2)
                    error.exception.close()
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/power", method="POST"), timeout=2)
                error.exception.close()
            with tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp) / "bridge.json"
                state.write_text(json.dumps({"port": server.server_port, "key": server.stop_key}))
                self.assertEqual(d.read_state(state)["port"], server.server_port)
        finally:
            server.shutdown()
            thread.join(2)
            server.server_close()

    def test_missing_or_invalid_bridge_state_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            self.assertIsNone(d.read_state(path))
            for value in ("not-json", '{"port": 80, "key": "bad"}', '{}'):
                path.write_text(value)
                self.assertIsNone(d.read_state(path))


if __name__ == "__main__":
    unittest.main()
