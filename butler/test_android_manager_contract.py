"""Real manager HTTP boundary with Android-shaped payloads; all bulbs are fake."""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from test_wiz_butler import FakeUdp, BULB, MAC, at
from wiz_butler import Butler, DEFAULT_CONFIG, MODES, TIMETABLE_KEYS, handler


class AndroidManagerContractTest(unittest.TestCase):
    def test_stale_save_preserves_pending_intent_and_all_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            udp = FakeUdp()
            butler = Butler(path, udp)
            butler.add_bulb(BULB)
            butler.configure(DEFAULT_CONFIG | {"enabled": True, "bulbs": [BULB]})
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler(butler))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)

            def request(method, endpoint, value=None):
                connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                connection.request(method, endpoint, json.dumps(value) if value is not None else None)
                response = connection.getresponse()
                result = response.status, json.loads(response.read())
                connection.close()
                return result

            # Timetable.json contains exactly these five fields, never bulbs.
            config = request("GET", "/v1/status")[1]["config"]
            baseline = {key: config[key] for key in TIMETABLE_KEYS}
            udp.state = None
            now = at(20)
            with patch("wiz_butler.time.time", return_value=now):
                code, pending = request("POST", "/v1/room", {"room": BULB["room"], "mode": "NIGHT"})
            self.assertEqual((200, 0, 1), (code, pending["answered"], pending["total"]))
            self.assertEqual("NIGHT", butler.intents[MAC]["mode"])
            changed = baseline | {"morning": "07:30", "expectedConfig": baseline}
            self.assertEqual(200, request("POST", "/v1/config", changed)[0])
            before_file = path.read_bytes()
            before_memory = copy.deepcopy(butler.status())
            before_writes = list(udp.writes)
            # Phone two passed its preflight GET before phone one saved.
            stale_draft = baseline | {"night": "22:00", "expectedConfig": baseline}
            self.assertEqual(409, request("POST", "/v1/config", stale_draft)[0])
            self.assertEqual(before_file, path.read_bytes())
            after_memory = butler.status()
            before_memory.pop("statusAt")
            after_memory.pop("statusAt")
            self.assertEqual(before_memory, after_memory)
            self.assertEqual(before_writes, udp.writes)
            self.assertEqual("22:00", stale_draft["night"])
            self.assertEqual([BULB], after_memory["config"]["bulbs"])
            # Zero acknowledgements meant pending, not discarded. Restart delivers it.
            restarted = Butler(path, udp)
            udp.state = {"mac": MAC, "state": False, **MODES["REGULAR"]}
            restarted.tick(now + 1)
            self.assertTrue(udp.state["state"])
            self.assertEqual(MODES["NIGHT"], {key: udp.state[key] for key in MODES["NIGHT"]})
            self.assertFalse(restarted.intents[MAC]["powerPending"])
