import copy
from datetime import datetime
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from zoneinfo import ZoneInfo

from wiz_butler import Butler, DEFAULT_CONFIG, MODES, handler, schedule, validate_config

MAC = "aabbccddeeff"
BULB = {"mac": MAC, "ip": "192.168.1.20", "room": "Bedroom"}


def at(hour, minute=0, day=5):
    return datetime(2026, 11, day, hour, minute, tzinfo=ZoneInfo("Asia/Jerusalem")).timestamp()


class FakeUdp:
    def __init__(self):
        self.state = {"mac": MAC, "state": True, "sceneId": 0, **MODES["REGULAR"]}
        self.writes = []
        self.found = {}
        self.ack = True

    def discover(self):
        return self.found

    def request(self, ip, method, params):
        if method == "getPilot":
            return copy.deepcopy(self.state)
        self.writes.append((ip, method, dict(params)))
        if self.ack:
            self.state.update(params)
            # Match observed hardware, not the published setState assumption.
            if method in ("setState", "setPilot") and "state" not in params:
                self.state["state"] = True
        return {"success": self.ack}


class ButlerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.udp = FakeUdp()
        self.butler = Butler(self.path, self.udp)
        self.config = copy.deepcopy(DEFAULT_CONFIG) | {"enabled": True, "bulbs": [BULB]}
        self.butler.configure(self.config)

    def test_validation(self):
        for patch in ({"night": "25:00"}, {"morning": "21:00"}, {"enabled": 1}, {"timezone": "unknown"}, {"bulbs": [BULB, BULB]},
                      {"bulbs": [BULB | {"ip": "127.0.0.1"}]}, {"bulbs": [BULB | {"mac": "bad"}]}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_config(self.config | patch)

    def test_poll_interval_validation(self):
        for interval in (True, 0, -1, 301, 5.5, "5", None):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                validate_config(self.config | {"pollSeconds": interval})
        for interval in (1, 2, 5, 30, 300):
            self.assertEqual(interval, validate_config(self.config | {"pollSeconds": interval})["pollSeconds"])

    def test_older_config_gets_default_interval(self):
        config = dict(self.config)
        config.pop("pollSeconds")
        self.assertEqual(1, validate_config(config)["pollSeconds"])

    def test_one_second_polling_includes_network_time(self):
        self.butler.configure(self.config | {"pollSeconds": 1})
        self.assertAlmostEqual(0.8, self.butler.poll_delay(at(20), elapsed=0.2))
        self.assertEqual(0.05, self.butler.poll_delay(at(20), elapsed=1.4))

    def test_configured_poll_interval_and_boundary_wakeup(self):
        self.butler.configure(self.config | {"pollSeconds": 30})
        self.assertEqual(30, self.butler.poll_delay(at(20, 30)))
        self.assertEqual(1, self.butler.poll_delay(at(21) - 1))
        self.assertTrue(self.butler.changed.is_set())
        self.butler.changed.clear()
        self.butler.configure(self.config | {"pollSeconds": 10})
        self.assertTrue(self.butler.changed.is_set())
        self.assertEqual(10, self.butler.poll_delay(at(20, 30)))

    def test_custom_times_persist_and_drive_manager_not_21(self):
        self.butler.configure(self.config | {"night": "22:15", "morning": "07:45", "pollSeconds": 17})
        restarted = Butler(self.path, self.udp)
        self.assertEqual("22:15", restarted.config["night"])
        self.assertEqual("07:45", restarted.config["morning"])
        self.assertEqual(17, restarted.config["pollSeconds"])
        restarted.tick(at(20, 59))
        restarted.tick(at(21))
        self.assertEqual([], self.udp.writes)
        restarted.tick(at(22, 14))
        restarted.tick(at(22, 15))
        self.assertEqual(MODES["NIGHT"], self.udp.writes[-1][2])
        restarted.tick(at(7, 44, day=6))
        self.assertEqual(1, len(self.udp.writes))
        restarted.tick(at(7, 45, day=6))
        self.assertEqual(MODES["REGULAR"], self.udp.writes[-1][2])

    def test_preset_boundaries(self):
        for hour, minute, mode in ((20, 59, "REGULAR"), (21, 0, "NIGHT"), (0, 0, "NIGHT"), (5, 59, "NIGHT"), (6, 0, "REGULAR")):
            with self.subTest(hour=hour, minute=minute):
                self.assertEqual(mode, schedule(self.config, at(hour, minute))[0])

    def test_custom_daytime_night_window(self):
        config = self.config | {"night": "10:30", "morning": "18:45"}
        self.assertEqual("NIGHT", schedule(config, at(11))[0])
        self.assertEqual("REGULAR", schedule(config, at(22))[0])

    def test_dst_keeps_wall_clock(self):
        config = self.config | {"timezone": "Europe/Berlin"}
        now = datetime(2027, 3, 27, 21, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
        following = schedule(config, now)[2]
        self.assertEqual(6, datetime.fromtimestamp(following, ZoneInfo("Europe/Berlin")).hour)
        self.assertEqual(8 * 3600, following - now)

    def test_dst_ambiguous_boundary_is_not_repeated(self):
        config = self.config | {"timezone": "Europe/Berlin", "night": "02:30", "morning": "06:00"}
        first = datetime(2027, 10, 31, 2, 45, fold=0, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
        second = datetime(2027, 10, 31, 2, 45, fold=1, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
        self.assertEqual(schedule(config, first)[1], schedule(config, second)[1])

    def test_startup_does_not_override(self):
        self.butler.tick(at(22))
        self.assertEqual([], self.udp.writes)

    def test_evening_boundary(self):
        self.butler.tick(at(20, 59))
        self.butler.tick(at(21))
        self.assertEqual((BULB["ip"], "setPilot", MODES["NIGHT"]), self.udp.writes[-1])
        self.assertNotIn("state", self.udp.writes[-1][2])
        self.butler.tick(at(21, 1))
        self.butler.tick(at(21, 2))
        self.assertEqual(1, len(self.udp.writes))

    def test_morning_boundary(self):
        self.udp.state.update(MODES["NIGHT"])
        self.butler.tick(at(5, 59))
        self.butler.tick(at(6))
        self.assertEqual(MODES["REGULAR"], self.udp.writes[-1][2])

    def test_off_and_unreachable_are_skipped(self):
        for state in (None, {"mac": MAC, "state": False}):
            self.udp.state = state
            self.butler.tick(at(20, 59))
            self.butler.tick(at(21))
        self.assertEqual([], self.udp.writes)

    def test_apply_rechecks_off_state_immediately_before_write(self):
        self.butler.tick(at(20, 59))
        original_request = self.udp.request
        reads = 0

        def switched_off_between_reads(ip, method, params):
            nonlocal reads
            reply = original_request(ip, method, params)
            if method == "getPilot":
                reads += 1
                if reads == 1:
                    self.udp.state["state"] = False
            return reply

        self.udp.request = switched_off_between_reads
        self.butler.tick(at(21))
        self.assertGreaterEqual(reads, 2)
        self.assertEqual([], self.udp.writes)
        self.assertFalse(self.udp.state["state"])

    def test_apply_never_writes_to_off_or_unreachable_bulb(self):
        for state in (None, {"mac": MAC, "state": False}):
            self.udp.state = state
            self.assertFalse(self.butler.apply(BULB, "NIGHT"))
        self.assertEqual([], self.udp.writes)

    def test_wall_on(self):
        self.udp.state["state"] = False
        self.butler.tick(at(22))
        self.udp.state["state"] = True
        self.butler.tick(at(22, 1))
        self.assertEqual(MODES["NIGHT"], self.udp.writes[-1][2])

    def test_wall_power_restoration(self):
        state = self.udp.state
        self.udp.state = None
        self.butler.tick(at(22))
        self.udp.state = state
        self.butler.tick(at(22, 1))
        self.assertEqual(MODES["NIGHT"], self.udp.writes[-1][2])

    def test_explicit_manual_override_survives_polls_and_restart(self):
        self.butler.command("Bedroom", "REGULAR", at(22))
        restarted = Butler(self.path, self.udp)
        restarted.tick(at(22, 1))
        self.udp.state = None
        restarted.tick(at(22, 2))
        self.udp.state = {"mac": MAC, "state": True, **MODES["REGULAR"]}
        restarted.tick(at(22, 3))
        self.assertEqual(1, len(self.udp.writes))
        self.assertGreater(restarted.holds[MAC], at(22, 3))

    def test_manual_override_expires_at_next_boundary(self):
        self.butler.command("Bedroom", "NIGHT", at(22))
        self.butler.tick(at(5, 59, day=6))
        self.butler.tick(at(6, day=6))
        self.assertEqual(MODES["REGULAR"], self.udp.writes[-1][2])

    def test_external_manual_override(self):
        self.butler.tick(at(22))
        self.udp.state.update({"temp": 4000, "dimming": 40})
        self.butler.tick(at(22, 1))
        self.udp.state = None
        self.butler.tick(at(22, 2))
        self.udp.state = {"mac": MAC, "state": True, "temp": 4000, "dimming": 40}
        self.butler.tick(at(22, 3))
        self.assertEqual([], self.udp.writes)

    def test_manual_off_stays_off(self):
        self.butler.command("Bedroom", "OFF", at(22))
        self.butler.tick(at(22, 1))
        self.butler.tick(at(6, day=6))
        self.assertFalse(self.udp.state["state"])
        self.assertEqual(1, len(self.udp.writes))

    def test_follow_resumes_but_never_turns_on(self):
        self.butler.command("Bedroom", "REGULAR", at(22))
        self.butler.command("Bedroom", "AUTO", at(22, 1))
        self.assertNotIn(MAC, self.butler.holds)
        self.assertEqual(MODES["NIGHT"], self.udp.writes[-1][2])
        self.udp.state["state"] = False
        count = len(self.udp.writes)
        self.butler.command("Bedroom", "AUTO", at(22, 2))
        self.assertEqual(count, len(self.udp.writes))

    def test_on_uses_laptop_time_and_rejoins(self):
        self.butler.command("Bedroom", "REGULAR", at(22))
        self.butler.command("Bedroom", "ON", at(22, 1))
        self.assertEqual({"state": True, **MODES["NIGHT"]}, self.udp.writes[-1][2])
        self.assertNotIn(MAC, self.butler.holds)

    def test_toggle_is_decided_by_laptop(self):
        self.butler.command("Bedroom", "TOGGLE", at(22))
        self.assertFalse(self.udp.state["state"])
        self.butler.command("Bedroom", "TOGGLE", at(22, 1))
        self.assertTrue(self.udp.state["state"])
        self.assertEqual({"state": True, **MODES["NIGHT"]}, self.udp.writes[-1][2])
        self.assertNotIn(MAC, self.butler.holds)

    def test_wrong_mac_never_receives_a_write(self):
        self.udp.state["mac"] = "000000000000"
        result = self.butler.command("Bedroom", "NIGHT", at(22))
        self.assertEqual(0, result["answered"])
        self.assertEqual([], self.udp.writes)

    def test_dhcp_rediscovery(self):
        self.udp.found = {MAC: "192.168.1.30"}
        self.udp.state["state"] = False
        self.butler.tick(at(22))
        self.udp.state["state"] = True
        self.butler.tick(at(22, 1))
        self.assertEqual("192.168.1.30", self.udp.writes[-1][0])

    def test_unacknowledged_commands_are_not_counted(self):
        self.udp.ack = False
        result = self.butler.command("Bedroom", "NIGHT", at(22))
        self.assertEqual(0, result["answered"])
        self.assertIn(MAC, self.butler.holds)

    def test_disabling_persists_and_stops_writes(self):
        self.butler.configure(self.config | {"enabled": False})
        self.butler.tick(at(20, 59))
        self.butler.tick(at(21))
        with self.assertRaises(ValueError):
            self.butler.command("Bedroom", "NIGHT", at(22))
        self.assertEqual([], self.udp.writes)
        self.assertFalse(Butler(self.path, self.udp).config["enabled"])

    def test_configure_preserves_holds_and_does_not_write(self):
        self.butler.command("Bedroom", "REGULAR", at(22))
        self.udp.writes.clear()
        self.butler.configure(self.config)
        self.butler.tick(at(22, 1))
        self.assertIn(MAC, self.butler.holds)
        self.assertEqual([], self.udp.writes)
        self.assertEqual(0o600, self.path.stat().st_mode & 0o777)

    def test_http_auth_and_configuration(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.butler, "x" * 32))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(method, path, body=None, token="x" * 32):
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            connection.request(method, path, body=json.dumps(body) if body is not None else None, headers={"Authorization": "Bearer " + token})
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result

        self.assertEqual(401, request("GET", "/v1/config", token="wrong")[0])
        self.assertEqual(404, request("GET", "/missing")[0])
        self.assertEqual(200, request("GET", "/v1/config")[0])
        response = request("POST", "/v1/config", self.config | {"night": "23:15", "morning": "08:30", "pollSeconds": 12})
        self.assertEqual(200, response[0])
        self.assertEqual("23:15", response[1]["config"]["night"])
        self.assertEqual("08:30", response[1]["config"]["morning"])
        self.assertEqual(12, response[1]["config"]["pollSeconds"])
        self.assertEqual(400, request("POST", "/v1/config", {})[0])
        self.assertEqual(400, request("POST", "/v1/room", {"room": "Bedroom", "mode": "reset"})[0])
        self.assertEqual(200, request("POST", "/v1/config", self.config | {"enabled": False})[0])
        self.assertFalse(self.butler.config["enabled"])


if __name__ == "__main__":
    unittest.main()
