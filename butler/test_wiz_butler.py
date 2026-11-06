import copy
from datetime import datetime
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from zoneinfo import ZoneInfo

from wiz_butler import Butler, DEFAULT_CONFIG, MODES, Udp, handler, schedule, validate_config

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
        if method == "getSystemConfig":
            return {"mac": MAC, "moduleName": "ESP24_SHRGBC_01", "fwVersion": "1.29.0"}
        self.writes.append((ip, method, dict(params)))
        if self.ack:
            self.state.update(params)
            # Match observed hardware, not the published setState assumption.
            if method in ("setState", "setPilot") and "state" not in params:
                self.state["state"] = True
        return {"success": self.ack}


class DiscoveryTest(unittest.TestCase):
    def test_malformed_lan_replies_do_not_abort_discovery(self):
        replies = [
            {"method": "getSystemConfig", "result": {"mac": 123}},
            {"method": "getSystemConfig", "result": None},
            {"method": "getSystemConfig", "result": {"mac": MAC.upper()}},
        ]
        with patch("wiz_butler.socket.socket") as socket_factory, patch("wiz_butler.time.monotonic", side_effect=[0, 0, 0, 0, 2]):
            sock = socket_factory.return_value.__enter__.return_value
            sock.recvfrom.side_effect = [(json.dumps(reply).encode(), (BULB["ip"], 38899)) for reply in replies]
            self.assertEqual({MAC: BULB["ip"]}, Udp("192.168.1.255").discover())


class ButlerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.udp = FakeUdp()
        self.butler = Butler(self.path, self.udp)
        self.config = copy.deepcopy(DEFAULT_CONFIG) | {"enabled": True, "bulbs": [BULB]}
        self.butler.add_bulb(BULB)
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

    def test_on_uses_manager_time_and_holds_until_boundary(self):
        self.butler.command("Bedroom", "REGULAR", at(22))
        self.butler.command("Bedroom", "ON", at(22, 1))
        self.assertEqual({"state": True, **MODES["NIGHT"]}, self.udp.writes[-1][2])
        self.assertEqual(at(6, day=6), self.butler.holds[MAC])

    def test_toggle_is_decided_by_laptop(self):
        self.butler.command("Bedroom", "TOGGLE", at(22))
        self.assertFalse(self.udp.state["state"])
        self.butler.command("Bedroom", "TOGGLE", at(22, 1))
        self.assertTrue(self.udp.state["state"])
        self.assertEqual({"state": True, **MODES["NIGHT"]}, self.udp.writes[-1][2])
        self.assertEqual(at(6, day=6), self.butler.holds[MAC])

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
        self.assertEqual([], self.udp.writes)
        self.assertFalse(Butler(self.path, self.udp).config["enabled"])
        self.assertEqual(1, self.butler.command("Bedroom", "NIGHT", at(22))["answered"])
        with self.assertRaisesRegex(ValueError, "Timetable is disabled"):
            self.butler.command("Bedroom", "AUTO", at(22))

    def test_configure_preserves_holds_and_does_not_write(self):
        self.butler.command("Bedroom", "REGULAR", at(22))
        self.udp.writes.clear()
        self.butler.configure(self.config)
        self.butler.tick(at(22, 1))
        self.assertIn(MAC, self.butler.holds)
        self.assertEqual([], self.udp.writes)
        self.assertEqual(0o600, self.path.stat().st_mode & 0o777)

    def test_existing_manager_file_preserves_bulbs_and_holds_without_migration(self):
        hold = at(6, day=6)
        second = {"mac": "112233445566", "ip": "192.168.1.12", "room": "Bulb …a582"}
        stored = {"config": self.config | {"bulbs": [BULB, second]}, "holds": {MAC: hold}}
        self.path.write_text(json.dumps(stored))
        restarted = Butler(self.path, self.udp)
        self.assertEqual(stored["config"], restarted.config)
        self.assertEqual({MAC: hold}, restarted.holds)
        self.assertEqual([], self.udp.writes)

    def test_schedule_only_save_cannot_erase_existing_manager_bulbs(self):
        self.butler.command("Bedroom", "NIGHT", at(22))
        self.udp.writes.clear()
        with self.assertRaisesRegex(ValueError, "Manager owns the bulb list"):
            self.butler.configure(self.config | {"bulbs": []})
        schedule_only = {key: value for key, value in self.config.items() if key != "bulbs"}
        self.butler.configure(schedule_only | {"night": "23:15"})
        self.assertEqual([BULB], self.butler.config["bulbs"])
        self.assertEqual(at(6, day=6), self.butler.holds[MAC])
        self.assertEqual([], self.udp.writes)
        self.assertEqual([BULB], Butler(self.path, self.udp).config["bulbs"])

    def test_discovery_is_read_only_and_returns_manager_observations(self):
        self.udp.found = {MAC: "192.168.1.30"}
        result = self.butler.discover()
        found = result["discovered"][0]
        self.assertEqual(MAC, found["mac"])
        self.assertEqual("192.168.1.30", found["ip"])
        self.assertTrue(found["pilot"]["state"])
        self.assertEqual("1.29.0", found["systemConfig"]["fwVersion"])
        self.assertEqual("192.168.1.30", result["status"]["config"]["bulbs"][0]["ip"])
        self.assertEqual([], self.udp.writes)

    def test_discovery_rejects_mismatched_mac_and_invalid_addresses(self):
        self.udp.found = {"000000000000": "192.168.1.30", MAC: "127.0.0.1", "not-a-mac": "192.168.1.31"}
        self.assertEqual([], self.butler.discover()["discovered"])
        self.assertNotIn(MAC, self.butler.addresses)
        self.assertEqual([], self.udp.writes)

    def test_schedule_save_preserves_dhcp_address_and_existing_errors(self):
        self.butler.addresses[MAC] = "192.168.1.30"
        self.butler.errors[MAC] = "unreachable or MAC mismatch"
        self.butler.configure(self.config)
        snapshot = self.butler.status()
        self.assertEqual("192.168.1.30", snapshot["config"]["bulbs"][0]["ip"])
        self.assertIn(MAC, snapshot["errors"])

    def test_failed_override_storage_never_sends_write_and_rolls_back_hold(self):
        with patch.object(self.butler, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.butler.command("Bedroom", "NIGHT", at(22))
        self.assertNotIn(MAC, self.butler.holds)
        self.assertEqual([], self.udp.writes)

    def test_add_is_explicit_persists_room_and_never_applies_preset(self):
        self.butler.add_bulb(BULB | {"room": "Kitchen"})
        self.assertEqual("Kitchen", Butler(self.path, self.udp).config["bulbs"][0]["room"])
        self.butler.tick(at(22))
        self.assertEqual([], self.udp.writes)

    def test_add_rejects_wrong_identity_without_changing_manager_file(self):
        before = self.path.read_text()
        self.udp.state["mac"] = "000000000000"
        with self.assertRaisesRegex(ValueError, "expected MAC"):
            self.butler.add_bulb(BULB | {"room": "Kitchen"})
        self.assertEqual(before, self.path.read_text())
        self.assertEqual([], self.udp.writes)

    def test_remove_persists_without_contacting_or_turning_off_bulb(self):
        self.butler.command("Bedroom", "NIGHT", at(22))
        self.udp.writes.clear()
        with patch.object(self.udp, "request", side_effect=AssertionError("Remove must not contact bulb")):
            result = self.butler.remove_bulb(MAC)
        self.assertEqual([], result["config"]["bulbs"])
        self.assertNotIn(MAC, result["holds"])
        self.assertEqual([], Butler(self.path, self.udp).config["bulbs"])
        self.assertEqual([], self.udp.writes)

    def test_add_remove_roll_back_on_storage_failure(self):
        before = copy.deepcopy(self.butler.config)
        with patch.object(self.butler, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.butler.add_bulb(BULB | {"room": "Kitchen"})
            self.assertEqual(before, self.butler.config)
            with self.assertRaises(OSError):
                self.butler.remove_bulb(MAC)
            self.assertEqual(before, self.butler.config)

    def test_disabled_timetable_still_polls_authoritative_status(self):
        self.butler.configure(self.config | {"enabled": False})
        self.udp.state["state"] = False
        self.butler.tick(at(22))
        status = self.butler.status()
        self.assertFalse(status["pilots"][MAC]["state"])
        self.assertEqual(at(22), status["lastPoll"])
        self.assertGreater(status["observedAt"][MAC], 0)
        self.assertGreaterEqual(status["statusAt"], status["observedAt"][MAC])
        self.assertEqual("1.29.0", status["systemConfigs"][MAC]["fwVersion"])
        self.assertEqual([], self.udp.writes)

    def test_timeout_clears_current_state_but_keeps_last_success_time(self):
        self.butler.tick(at(22))
        observed = self.butler.status()["observedAt"][MAC]
        self.udp.state = None
        self.butler.tick(at(22, 1))
        snapshot = self.butler.status()
        self.assertNotIn(MAC, snapshot["pilots"])
        self.assertEqual(observed, snapshot["observedAt"][MAC])
        self.assertIn("unreachable", snapshot["errors"][MAC])

    def test_every_write_rechecks_identity_not_only_initial_room_read(self):
        original = self.udp.request
        reads = 0

        def changed_identity(ip, method, params):
            nonlocal reads
            result = original(ip, method, params)
            if method == "getPilot":
                reads += 1
                if reads == 1:
                    self.udp.state["mac"] = "000000000000"
            return result

        self.udp.request = changed_identity
        self.assertEqual(0, self.butler.command("Bedroom", "NIGHT", at(22))["answered"])
        self.assertEqual([], self.udp.writes)

    def test_blink_preserves_power_preset_and_existing_override(self):
        for on in (False, True):
            with self.subTest(on=on), patch("wiz_butler.time.sleep"):
                self.udp.state = {"mac": MAC, "state": on, **MODES["REGULAR"]}
                self.butler.holds[MAC] = at(6, day=6)
                self.butler.tick(at(22))
                self.udp.writes.clear()
                self.butler.blink(MAC)
                self.assertEqual(on, self.udp.state["state"])
                self.assertEqual(6500, self.udp.state["temp"])
                self.assertEqual(100, self.udp.state["dimming"])
                self.assertEqual(at(6, day=6), self.butler.holds[MAC])
                count = len(self.udp.writes)
                self.butler.tick(at(22, 1))
                self.assertEqual(count, len(self.udp.writes))

    def test_blink_discovered_unsaved_bulb_and_reject_unknown_identifier(self):
        self.butler.remove_bulb(MAC)
        with self.assertRaisesRegex(ValueError, "Unknown bulb"):
            self.butler.blink(MAC)
        self.udp.found = {MAC: BULB["ip"]}
        self.butler.discover()
        with patch("wiz_butler.time.sleep"):
            self.butler.blink(MAC)
        self.assertEqual([], self.butler.config["bulbs"])
        self.assertTrue(self.udp.writes)

    def test_blink_never_writes_to_wrong_identity_or_unreachable_bulb(self):
        for state in (None, {"mac": "000000000000", "state": True}):
            self.udp.state = state
            with self.assertRaisesRegex(ValueError, "MAC mismatch"):
                self.butler.blink(MAC)
        self.assertEqual([], self.udp.writes)

    def test_blink_restore_rechecks_identity_before_each_write(self):
        original = self.udp.request

        def identity_changes_after_first_flash(ip, method, params):
            result = original(ip, method, params)
            if method == "setPilot":
                self.udp.state["mac"] = "000000000000"
            return result

        self.udp.request = identity_changes_after_first_flash
        with patch("wiz_butler.time.sleep"), self.assertRaisesRegex(ValueError, "restore"):
            self.butler.blink(MAC)
        self.assertEqual(1, len(self.udp.writes))

    def test_all_http_endpoints_require_auth_and_status_get_is_cached(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.butler, "x" * 32))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(method, path, value=None, authorized=True):
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            headers = {"Authorization": "Bearer " + "x" * 32} if authorized else {}
            connection.request(method, path, json.dumps(value) if value is not None else None, headers)
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result

        for path in ("/v1/status", "/v1/config"):
            self.assertEqual(401, request("GET", path, authorized=False)[0])
        for path in ("/v1/config", "/v1/room", "/v1/discover", "/v1/bulbs/add", "/v1/bulbs/remove", "/v1/bulbs/blink"):
            with self.subTest(path=path):
                self.assertEqual(401, request("POST", path, {}, authorized=False)[0])
        with patch.object(self.udp, "request", side_effect=AssertionError("GET is a cached manager snapshot")):
            self.assertEqual([BULB], request("GET", "/v1/status")[1]["config"]["bulbs"])
        self.assertEqual(400, request("POST", "/v1/config", self.config | {"bulbs": []})[0])
        self.udp.found = {MAC: BULB["ip"]}
        self.assertEqual(MAC, request("POST", "/v1/discover", {})[1]["discovered"][0]["mac"])
        self.assertEqual(200, request("POST", "/v1/bulbs/add", BULB | {"room": "Kitchen"})[0])
        with patch("wiz_butler.time.sleep"):
            self.assertEqual(200, request("POST", "/v1/bulbs/blink", {"mac": MAC})[0])
        self.assertEqual(400, request("POST", "/v1/bulbs/blink", {"mac": "unknown"})[0])
        self.assertEqual(200, request("POST", "/v1/bulbs/remove", {"mac": MAC})[0])
        self.assertEqual(400, request("POST", "/v1/bulbs/remove", {"mac": MAC})[0])

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
