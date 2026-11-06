import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer

from android_preview import FixtureHandler, STATE_SCREENSHOTS, copy_state_screenshots, fixture, fixture_preferences, selected_controls


class PreviewFixtureTest(unittest.TestCase):
    def test_fixture_has_a_reachable_and_an_unreachable_room(self):
        status = fixture()
        self.assertEqual(["Living room", "Bedroom"], [bulb["room"] for bulb in status["config"]["bulbs"]])
        self.assertEqual(1, len(status["pilots"]))
        self.assertEqual(1, len(status["errors"]))

    def test_sample_server_is_read_only(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(method, path):
            connection = http.client.HTTPConnection(*server.server_address)
            connection.request(method, path)
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result

        code, status = request("GET", "/v1/status")
        self.assertEqual(200, code)
        self.assertEqual(2, len(status["config"]["bulbs"]))
        for path in ("/v1/room", "/v1/config", "/v1/discover", "/v1/bulbs/blink", "/v1/pair"):
            self.assertEqual(403, request("POST", path)[0])

    def test_preferences_pin_fixture_before_any_bulbs_open(self):
        preferences = ET.fromstring(fixture_preferences())
        values = {node.get("name"): node for node in preferences}
        self.assertEqual("http://127.0.0.1:8789", values["butler_url"].text)
        self.assertEqual("true", values["butler_enabled"].get("value"))
        self.assertIn("never household", values["butler_service_name"].text)
        self.assertNotIn("butler_token", values)

    def test_radio_checked_semantics_use_parent_and_child_label(self):
        tree = ET.fromstring('''<hierarchy><node checkable="true" checked="false"><node text="Night" /></node>
            <node checkable="true" checked="true"><node text="Follow timetable" /></node></hierarchy>''')
        self.assertEqual(["Follow timetable"], selected_controls(tree))

    def test_preset_and_follow_fixtures_are_deterministic_and_fresh(self):
        for mode, dimming, temp in (("regular", 100, 6500), ("night", 20, 2700), ("follow", 20, 2700)):
            with self.subTest(mode=mode):
                status = fixture(mode)
                self.assertEqual({}, status["errors"])
                self.assertEqual(2, len(status["pilots"]))
                for mac, pilot in status["pilots"].items():
                    self.assertTrue(pilot["state"])
                    self.assertEqual((dimming, temp), (pilot["dimming"], pilot["temp"]))
                    self.assertEqual(status["statusAt"], status["observedAt"][mac])
                self.assertEqual(mode != "follow", bool(status["holds"]))
        with self.assertRaises(ValueError):
            fixture("invalid")

    def test_optional_discovery_is_canned_and_never_enables_control(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        server.fixture_discovery = True
        server.fixture_mode = "night"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for path in ("/v1/status", "/v1/discover", "/v1/room", "/v1/config", "/v1/bulbs/add",
                     "/v1/bulbs/remove", "/v1/bulbs/blink", "/v1/pair"):
            method = "GET" if path == "/v1/status" else "POST"
            connection = http.client.HTTPConnection(*server.server_address)
            connection.request(method, path)
            response = connection.getresponse()
            result = json.loads(response.read())
            if path in ("/v1/status", "/v1/discover"):
                self.assertEqual(200, response.status)
                if path == "/v1/discover":
                    self.assertEqual("aabb00000003", result["discovered"][0]["mac"])
                else:
                    self.assertEqual(2700, next(iter(result["pilots"].values()))["temp"])
            else:
                self.assertEqual(403, response.status)
            connection.close()

    def test_copy_preserves_live_evidence_and_gallery(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / "fixture", Path(directory) / "live"
            source.mkdir()
            destination.mkdir()
            protected = ("bulbs-setup.png", "bulbs-connected.png", "bulbs-timetable.png", "bulbs-advanced.png", "index.html")
            for name in (*STATE_SCREENSHOTS, *protected):
                (source / name).write_bytes(b"fixture")
            for name in protected:
                (destination / name).write_bytes(b"real")
            copy_state_screenshots(source, destination)
            for name in STATE_SCREENSHOTS:
                self.assertEqual(b"fixture", (destination / name).read_bytes())
            for name in protected:
                self.assertEqual(b"real", (destination / name).read_bytes())
