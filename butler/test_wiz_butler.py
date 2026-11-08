import copy
from datetime import datetime
import http.client
import json
import socket
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from zoneinfo import ZoneInfo

from wiz_butler import Butler, ConfigConflict, DEFAULT_CONFIG, MODES, TIMETABLE_KEYS, Udp, handler, schedule, validate_config

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
            if "temp" in params:
                self.state["sceneId"] = 0
            # Match observed hardware, not the published setState assumption.
            if method in ("setState", "setPilot") and "state" not in params:
                self.state["state"] = True
        return {"success": self.ack}


class DiscoveryTest(unittest.TestCase):
    def test_udp_write_does_not_blindly_retransmit_after_lost_ack(self):
        with patch("wiz_butler.socket.socket") as socket_factory, patch("wiz_butler.time.monotonic", return_value=0):
            sock = socket_factory.return_value.__enter__.return_value
            sock.recv.side_effect = socket.timeout
            self.assertIsNone(Udp("192.168.1.255").request(BULB["ip"], "setPilot", MODES["NIGHT"]))
            self.assertEqual(1, sock.send.call_count)

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

    def test_dst_fold_and_gap_reconciliation_uses_configured_zone(self):
        zone = ZoneInfo("Europe/Berlin")
        self.butler.configure(self.config | {"timezone": "Europe/Berlin", "night": "02:30"})
        for now, expected in (
            (datetime(2027, 3, 28, 3, 15, tzinfo=zone).timestamp(), "REGULAR"),
            (datetime(2027, 3, 28, 3, 45, tzinfo=zone).timestamp(), "NIGHT"),
            (datetime(2027, 10, 31, 2, 45, fold=0, tzinfo=zone).timestamp(), "NIGHT"),
            (datetime(2027, 10, 31, 2, 45, fold=1, tzinfo=zone).timestamp(), "NIGHT"),
        ):
            with self.subTest(now=now):
                self.udp.state.update(temp=4100, dimming=43)
                self.butler.tick(now)
                self.assertTrue(self.butler.matches(self.udp.state, MODES[expected]))

    def test_timezone_edit_recomputes_expiry_from_absolute_request_time(self):
        self.butler.command("Bedroom", "NIGHT", at(12, 17))
        changed = self.config | {"timezone": "America/New_York", "night": "13:23"}
        self.butler.configure(changed)
        expiry = schedule(changed, at(12, 17))[2]
        self.assertEqual(expiry, self.butler.holds[MAC])
        self.butler.tick(expiry + 13)
        self.assertNotIn(MAC, self.butler.holds)
        self.assertTrue(self.butler.matches(self.udp.state, MODES[schedule(changed, expiry + 13)[0]]))

    def test_startup_reconciles_current_timetable_without_boundary_event(self):
        self.butler.tick(at(22))
        self.assertEqual([MODES["NIGHT"]], [write[2] for write in self.udp.writes])

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

    def test_fresh_prewrite_read_already_matching_suppresses_udp_write(self):
        original = self.udp.request

        def fade_completes_between_reads(ip, method, params):
            result = original(ip, method, params)
            if method == "getPilot":
                self.udp.state.update(MODES["NIGHT"])
            return result

        self.udp.request = fade_completes_between_reads
        self.butler.tick(at(23, 17))
        self.assertEqual([], self.udp.writes)
        self.assertNotIn(MAC, self.butler.errors)

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
        self.assertEqual(0, len(self.udp.writes))  # Already matched: no redundant write.
        self.assertGreater(restarted.holds[MAC], at(22, 3))

    def test_manual_override_expires_at_next_boundary(self):
        self.butler.command("Bedroom", "NIGHT", at(22))
        self.butler.tick(at(5, 59, day=6))
        self.butler.tick(at(6, day=6))
        self.assertEqual(MODES["REGULAR"], self.udp.writes[-1][2])

    def test_external_changes_are_corrected_not_inferred_as_overrides(self):
        self.butler.tick(at(22))
        self.udp.state.update({"temp": 4000, "dimming": 40})
        self.butler.tick(at(22, 1))
        self.udp.state = None
        self.butler.tick(at(22, 2))
        self.udp.state = {"mac": MAC, "state": True, "temp": 4000, "dimming": 40}
        self.butler.tick(at(22, 3))
        self.assertEqual(3, len(self.udp.writes))
        self.assertEqual(2700, self.udp.state["temp"])
        self.assertNotIn(MAC, self.butler.holds)

    def test_manual_off_stays_off(self):
        self.butler.command("Bedroom", "OFF", at(22))
        self.assertNotIn(MAC, self.butler.holds)
        self.assertNotIn(MAC, self.butler.intents)
        self.butler.tick(at(22, 1))
        self.butler.tick(at(6, day=6))
        self.assertFalse(self.udp.state["state"])
        self.assertEqual(1, len(self.udp.writes))

    def test_confirmed_off_allows_later_wall_on_and_reconciles_timetable(self):
        self.butler.command("Bedroom", "OFF", at(23, 17))
        self.butler = Butler(self.path, self.udp)
        self.butler.tick(at(23, 18))
        self.assertFalse(self.udp.state["state"])
        self.assertEqual(1, len(self.udp.writes))
        self.udp.state.update(state=True, temp=4100, dimming=43)
        self.butler.tick(at(23, 19))
        self.assertTrue(self.udp.state["state"])
        self.assertTrue(self.butler.matches(self.udp.state, MODES["NIGHT"]))
        self.assertNotIn("state", self.udp.writes[-1][2])
        self.assertNotIn(MAC, self.butler.status()["holds"])
        self.assertNotIn(MAC, self.butler.status()["intents"])

    def test_unreachable_off_is_pending_until_confirmed_then_wall_on_is_allowed(self):
        self.udp.state = None
        self.assertEqual(0, self.butler.command("Bedroom", "OFF", at(23, 17))["answered"])
        self.assertTrue(self.butler.intents[MAC]["powerPending"])
        self.butler = Butler(self.path, self.udp)
        self.butler.tick(at(23, 18))
        self.assertIn(MAC, self.butler.intents)
        self.udp.state = {"mac": MAC, "state": True, **MODES["REGULAR"]}
        self.udp.ack = False
        self.butler.tick(at(23, 19))
        self.assertTrue(self.udp.state["state"])
        self.assertTrue(self.butler.intents[MAC]["powerPending"])
        self.assertEqual({"state": False}, self.udp.writes[-1][2])
        self.udp.ack = True
        self.butler.tick(at(23, 20))
        self.assertFalse(self.udp.state["state"])
        self.assertNotIn(MAC, Butler(self.path, self.udp).intents)
        self.udp.state["state"] = True
        self.butler.tick(at(23, 21))
        self.assertTrue(self.udp.state["state"])
        self.assertTrue(self.butler.matches(self.udp.state, MODES["NIGHT"]))

    def test_confirmed_on_does_not_undo_later_off(self):
        self.udp.state["state"] = False
        self.butler.command("Bedroom", "ON", at(23, 17))
        self.assertTrue(self.udp.state["state"])
        self.butler = Butler(self.path, self.udp)
        self.udp.state["state"] = False
        before = len(self.udp.writes)
        self.butler.tick(at(23, 18))
        self.butler.tick(at(23, 19))
        self.assertFalse(self.udp.state["state"])
        self.assertEqual(before, len(self.udp.writes))

    def test_disabled_schedule_does_not_force_off_again_after_delivery(self):
        self.butler.configure(self.config | {"enabled": False})
        self.butler.command("Bedroom", "OFF", at(23, 17))
        self.udp.state.update(state=True, temp=4100, dimming=43)
        before = len(self.udp.writes)
        self.butler.tick(at(23, 18))
        self.assertTrue(self.udp.state["state"])
        self.assertEqual(4100, self.udp.state["temp"])
        self.assertEqual(before, len(self.udp.writes))

    def test_expired_override_cleanup_failure_never_blocks_reads_or_correction(self):
        self.butler.command("Bedroom", "NIGHT", at(23, 17))
        stored = self.path.read_text()
        with patch.object(self.butler, "save", side_effect=OSError("disk full")):
            for now in (at(6, 17, day=6), at(6, 18, day=6)):
                self.udp.state.update(MODES["NIGHT"])
                with patch.object(self.udp, "request", wraps=self.udp.request) as request:
                    self.butler.tick(now)
                self.assertTrue(any(call.args[1] == "getPilot" for call in request.call_args_list))
                self.assertTrue(self.butler.matches(self.udp.state, MODES["REGULAR"]))
                self.assertIn(MAC, self.butler.intents)  # Durable cleanup retry retained.
                self.assertIn("could not be saved", self.butler.status()["errors"][MAC])
                self.butler.pilot(BULB)
                self.assertIn("could not be saved", self.butler.status()["errors"][MAC])
                self.assertIsNotNone(self.butler.status()["persistenceError"])
                self.assertEqual(stored, self.path.read_text())
        self.butler.tick(at(6, 19, day=6))
        self.assertNotIn(MAC, self.butler.intents)
        self.assertNotIn(MAC, self.butler.holds)
        self.assertIsNone(self.butler.status()["persistenceError"])
        self.assertNotIn(MAC, self.butler.status()["errors"])
        self.assertNotIn(MAC, Butler(self.path, self.udp).intents)

    def test_expired_intent_does_not_resurrect_after_restart_with_failed_storage(self):
        self.udp.state = None
        self.butler.command("Bedroom", "NIGHT", at(23, 17))
        self.assertTrue(self.butler.intents[MAC]["powerPending"])
        for now in (at(6, 17, day=6), at(6, 18, day=6)):
            restarted = Butler(self.path, self.udp)
            self.udp.state = {"mac": MAC, "state": True, **MODES["NIGHT"]}
            with patch.object(restarted, "save", side_effect=OSError("disk full")):
                restarted.tick(now)
            self.assertTrue(restarted.matches(self.udp.state, MODES["REGULAR"]))
            self.assertNotIn("state", self.udp.writes[-1][2])
        restarted = Butler(self.path, self.udp)
        self.udp.state["state"] = False
        before = len(self.udp.writes)
        with patch.object(restarted, "save", side_effect=OSError("disk full")):
            restarted.tick(at(6, 19, day=6))
        self.assertFalse(self.udp.state["state"])
        self.assertEqual(before, len(self.udp.writes))

    def test_confirmed_off_cleanup_failure_does_not_block_wall_on(self):
        # Initial request is durably queued, then verification cleanup hits a
        # full disk. Readback must still retire its effective power forcing.
        original = self.butler.save
        saves = 0

        def fail_cleanup():
            nonlocal saves
            saves += 1
            if saves == 1:
                return original()
            raise OSError("disk full")

        with patch.object(self.butler, "save", side_effect=fail_cleanup):
            self.butler.command("Bedroom", "OFF", at(23, 17))
        self.assertFalse(self.udp.state["state"])
        self.assertFalse(self.butler.intents[MAC]["powerPending"])
        self.assertNotIn(MAC, self.butler.status()["holds"])
        self.udp.state.update(state=True, **MODES["REGULAR"])
        with patch.object(self.butler, "save", side_effect=OSError("disk full")):
            self.butler.tick(at(23, 18))
        self.assertTrue(self.udp.state["state"])
        self.assertTrue(self.butler.matches(self.udp.state, MODES["NIGHT"]))
        self.assertNotIn(MAC, self.butler.status()["holds"])
        self.assertIn("could not be saved", self.butler.status()["errors"][MAC])
        self.butler.tick(at(23, 19))
        self.assertNotIn(MAC, Butler(self.path, self.udp).intents)
        self.assertIsNone(self.butler.persistence_error)

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

    def test_failed_schedule_adjustment_is_corrected_on_ordinary_next_poll(self):
        self.udp.ack = False
        self.butler.tick(at(23, 17))
        self.assertIn("pending", self.butler.errors[MAC])
        self.butler.pilot(BULB)  # Successful reads must not erase write failure.
        self.assertIn("pending", self.butler.errors[MAC])
        self.butler.tick(at(23, 18))
        self.assertEqual(2, len(self.udp.writes))
        self.assertNotIn(MAC, self.butler.holds)
        self.udp.ack = True
        self.butler.tick(at(23, 19))
        self.assertEqual(2700, self.udp.state["temp"])
        self.assertNotIn(MAC, self.butler.errors)
        self.butler.tick(at(23, 20))
        self.assertEqual(3, len(self.udp.writes))

    def test_arbitrary_times_reconcile_invariant_not_events(self):
        self.butler.configure(self.config | {"night": "13:37", "morning": "03:19"})
        for hour in range(24):
            for minute in (2, 23, 48):
                with self.subTest(hour=hour, minute=minute):
                    now = at(hour, minute)
                    expected = MODES[schedule(self.butler.config, now)[0]]
                    self.udp.state.update(temp=4100, dimming=43)
                    before = len(self.udp.writes)
                    self.butler.tick(now)
                    self.assertTrue(self.butler.matches(self.udp.state, expected))
                    self.butler.tick(now + 1)
                    self.assertEqual(before + 1, len(self.udp.writes))
                    self.assertFalse(self.butler.holds)

    def test_unreachable_manual_intent_survives_restart_and_is_delivered(self):
        self.udp.state = None
        result = self.butler.command("Bedroom", "NIGHT", at(12, 17))
        self.assertEqual(0, result["answered"])
        self.assertEqual("NIGHT", self.butler.status()["intents"][MAC]["mode"])
        stored = json.loads(self.path.read_text())
        self.assertEqual(2, stored["schemaVersion"])
        restarted = Butler(self.path, self.udp)
        restarted.tick(at(12, 18))
        self.udp.state = {"mac": MAC, "state": True, **MODES["REGULAR"]}
        restarted.tick(at(12, 19))
        self.assertEqual(2700, self.udp.state["temp"])
        self.assertFalse(restarted.intents[MAC]["powerPending"])
        self.assertFalse(Butler(self.path, self.udp).intents[MAC]["powerPending"])
        restarted.tick(at(12, 20))
        self.assertEqual(1, len(self.udp.writes))

    def test_ambiguous_ack_applied_once_verified_without_repeating_power(self):
        original = self.udp.request

        def lose_ack(ip, method, params):
            result = original(ip, method, params)
            return None if method == "setPilot" else result

        self.udp.request = lose_ack
        result = self.butler.command("Bedroom", "NIGHT", at(12, 17))
        self.assertEqual(0, result["answered"])
        self.assertFalse(self.butler.intents[MAC]["powerPending"])
        self.butler.tick(at(12, 18))
        self.assertEqual(1, len(self.udp.writes))
        self.udp.state["state"] = False
        self.butler.tick(at(12, 19))
        self.assertFalse(self.udp.state["state"])
        self.assertEqual(1, len(self.udp.writes))

    def test_success_ack_without_applied_setting_remains_pending(self):
        original = self.udp.request

        def lie_about_write(ip, method, params):
            if method == "setPilot":
                self.udp.writes.append((ip, method, dict(params)))
                return {"success": True}
            return original(ip, method, params)

        self.udp.request = lie_about_write
        self.assertEqual(0, self.butler.command("Bedroom", "NIGHT", at(12, 17))["answered"])
        self.assertTrue(self.butler.intents[MAC]["powerPending"])
        self.butler.tick(at(12, 18))
        self.assertIn("pending", self.butler.errors[MAC])
        self.assertEqual(2, len(self.udp.writes))
        self.udp.request = original
        self.butler.tick(at(12, 19))
        self.assertFalse(self.butler.intents[MAC]["powerPending"])
        self.assertNotIn(MAC, self.butler.errors)

    def test_failed_explicit_on_and_off_reconcile_until_delivered(self):
        for mode, initial in (("ON", False), ("OFF", True)):
            with self.subTest(mode=mode):
                self.udp.state = {"mac": MAC, "state": initial, **MODES["REGULAR"]}
                self.udp.ack = False
                self.assertEqual(0, self.butler.command("Bedroom", mode, at(23, 17))["answered"])
                self.udp.ack = True
                self.butler.tick(at(23, 18))
                self.assertEqual(mode == "ON", self.udp.state["state"])
                before = len(self.udp.writes)
                self.butler.tick(at(23, 19))
                self.assertEqual(before, len(self.udp.writes))

    def test_follow_clears_unreachable_pending_intent_permanently(self):
        self.udp.state = None
        self.butler.command("Bedroom", "REGULAR", at(23, 17))
        self.butler.command("Bedroom", "AUTO", at(23, 18))
        restarted = Butler(self.path, self.udp)
        self.assertNotIn(MAC, restarted.intents)
        self.assertNotIn(MAC, restarted.holds)
        self.udp.state = {"mac": MAC, "state": False, **MODES["REGULAR"]}
        restarted.tick(at(23, 19))
        self.assertEqual([], self.udp.writes)

    def test_edit_recomputes_override_expiry_earlier_and_later(self):
        for morning, expiry in (("05:13", at(5, 13, day=6)), ("08:47", at(8, 47, day=6))):
            with self.subTest(morning=morning):
                self.butler.configure(self.config)
                self.butler.command("Bedroom", "NIGHT", at(23, 17))
                self.butler.configure(self.config | {"morning": morning})
                self.assertEqual(expiry, self.butler.holds[MAC])
                restarted = Butler(self.path, self.udp)
                restarted.tick(expiry - 1)
                self.assertEqual(2700, self.udp.state["temp"])
                restarted.tick(expiry + 17)
                self.assertEqual(6500, self.udp.state["temp"])
                self.assertNotIn(MAC, restarted.holds)
                self.assertNotIn(MAC, restarted.intents)

    def test_edit_boundary_into_past_expires_on_next_poll(self):
        self.butler.command("Bedroom", "NIGHT", at(12, 17))
        self.butler.configure(self.config | {"night": "13:23"})
        self.butler.tick(at(14, 17))
        self.assertNotIn(MAC, self.butler.intents)
        self.assertNotIn(MAC, self.butler.holds)

    def test_disabled_schedule_still_reconciles_explicit_pending_intent(self):
        self.butler.configure(self.config | {"enabled": False})
        self.udp.state = None
        self.butler.command("Bedroom", "NIGHT", at(12, 17))
        self.udp.state = {"mac": MAC, "state": True, **MODES["REGULAR"]}
        self.butler.tick(at(12, 18))
        self.assertEqual(2700, self.udp.state["temp"])
        self.udp.state.update(MODES["REGULAR"])
        self.butler.tick(at(12, 19))
        self.assertEqual(2700, self.udp.state["temp"])
        self.butler.tick(at(21, 1))
        self.udp.state.update(MODES["REGULAR"])
        self.butler.tick(at(21, 2))
        self.assertEqual(6500, self.udp.state["temp"])

    def test_legacy_hold_unknown_preset_preserved_until_expiry(self):
        self.path.write_text(json.dumps({"config": self.config, "holds": {MAC: at(6, day=6)}}))
        restarted = Butler(self.path, self.udp)
        self.udp.state.update(temp=4100, dimming=43)
        restarted.tick(at(23, 17))
        restarted.save()
        restarted = Butler(self.path, self.udp)
        restarted.tick(at(23, 18))
        self.assertEqual([], self.udp.writes)
        self.assertNotIn(MAC, restarted.intents)
        restarted.tick(at(6, 17, day=6))
        self.assertEqual(6500, self.udp.state["temp"])

    def test_schedule_off_invariant_even_after_failed_write(self):
        self.udp.ack = False
        self.butler.tick(at(23, 17))
        self.udp.state["state"] = False
        before = len(self.udp.writes)
        self.udp.ack = True
        for now in (at(23, 18), at(6, 17, day=6), at(22, 11, day=6)):
            self.butler.tick(now)
            self.assertFalse(self.udp.state["state"])
            self.assertEqual(before, len(self.udp.writes))

    def test_scene_mismatch_is_corrected_even_with_matching_temperature(self):
        self.udp.state["sceneId"] = 5
        self.butler.tick(at(12, 17))
        self.assertEqual(1, len(self.udp.writes))
        self.assertEqual(0, self.udp.state["sceneId"])

    def test_expected_config_atomic_concurrent_save_and_conflict(self):
        baseline = {key: self.config[key] for key in TIMETABLE_KEYS}
        self.butler.command("Bedroom", "NIGHT", at(12, 17))
        gate = threading.Barrier(3)
        results = []

        def save(night):
            gate.wait()
            try:
                self.butler.configure(self.config | {"night": night, "expectedConfig": baseline})
                results.append("saved")
            except ConfigConflict:
                results.append("conflict")

        threads = [threading.Thread(target=save, args=(night,)) for night in ("22:13", "23:27")]
        for thread in threads:
            thread.start()
        gate.wait()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(["saved", "conflict"], results)
        before = self.path.read_text(), copy.deepcopy(self.butler.status())
        with self.assertRaisesRegex(ConfigConflict, "Timetable changed on another device"):
            self.butler.configure(self.config | {"expectedConfig": baseline})
        self.assertEqual(before[0], self.path.read_text())
        for field in ("config", "holds", "intents", "errors", "pilots"):
            self.assertEqual(before[1][field], self.butler.status()[field])

    def test_expected_config_strict_validation_and_legacy_compatibility(self):
        expected = {key: self.config[key] for key in TIMETABLE_KEYS}
        for invalid in (None, [], {}, expected | {"bulbs": []}, expected | {"pollSeconds": True},
                        expected | {"enabled": 1}, expected | {"night": "bad"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.butler.configure(self.config | {"expectedConfig": invalid})
        self.butler.configure(self.config | {"expectedConfig": expected, "night": "23:27"})
        self.butler.configure(self.config)  # Old clients retain unconditional save.
        self.assertEqual("21:00", self.butler.config["night"])

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
        self.assertEqual(at(23, 15), self.butler.holds[MAC])
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
        self.assertNotIn(MAC, self.butler.intents)
        self.assertEqual([], self.udp.writes)

    def test_atomic_save_failure_keeps_prior_state_and_intent(self):
        self.butler.command("Bedroom", "NIGHT", at(12, 17))
        before = self.path.read_text()
        intent = copy.deepcopy(self.butler.intents)
        with patch("wiz_butler.os.fsync", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.butler.command("Bedroom", "OFF", at(12, 18))
        self.assertEqual(before, self.path.read_text())
        self.assertEqual(intent, self.butler.intents)
        self.assertEqual(intent, Butler(self.path, self.udp).intents)

    def test_add_persists_room_without_writing_then_next_poll_reconciles(self):
        self.butler.add_bulb(BULB | {"room": "Kitchen"})
        self.assertEqual("Kitchen", Butler(self.path, self.udp).config["bulbs"][0]["room"])
        self.assertEqual([], self.udp.writes)
        self.butler.tick(at(22))
        self.assertEqual(MODES["NIGHT"], self.udp.writes[-1][2])

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

    def seed_second_bulb(self):
        second = {"mac": "112233445566", "ip": "192.168.1.12", "room": "Bulb …a582"}
        self.path.write_text(json.dumps({"config": self.config | {"bulbs": [BULB, second]}}))
        self.butler = Butler(self.path, self.udp)
        return second

    def test_rename_persists_across_restart_and_keeps_bulb_order(self):
        second = self.seed_second_bulb()
        result = self.butler.rename_bulb(MAC, "Reading lamp")
        expected = [BULB | {"room": "Reading lamp"}, second]
        self.assertEqual(expected, result["config"]["bulbs"])
        self.assertEqual(expected, Butler(self.path, self.udp).config["bulbs"])
        self.assertEqual(0o600, self.path.stat().st_mode & 0o777)

    def test_rename_keeps_holds_intents_and_timetable(self):
        self.butler.command("Bedroom", "NIGHT", at(22))
        self.butler.tick(at(22))
        holds, intents = copy.deepcopy(self.butler.holds), copy.deepcopy(self.butler.intents)
        timetable = {key: self.butler.config[key] for key in TIMETABLE_KEYS}
        self.assertEqual(1, len(intents))
        self.butler.rename_bulb(MAC, "Reading lamp")
        restarted = Butler(self.path, self.udp)
        for butler in (self.butler, restarted):
            self.assertEqual(holds, butler.holds)
            self.assertEqual(intents, butler.intents)
            self.assertEqual(timetable, {key: butler.config[key] for key in TIMETABLE_KEYS})

    def test_rename_rejects_bad_input_without_changing_anything(self):
        before, config = self.path.read_bytes(), copy.deepcopy(self.butler.config)
        for mac, room in ((MAC, ""), (MAC, "   "), (MAC, None), (MAC, 7), (MAC, "x" * 101), (MAC, ["Kitchen"]),
                          ("000000000000", "Kitchen"), (None, "Kitchen"), (7, "Kitchen")):
            with self.subTest(mac=mac, room=room), self.assertRaises(ValueError):
                self.butler.rename_bulb(mac, room)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(config, self.butler.config)

    def test_rename_rolls_back_on_save_failure(self):
        self.butler.command("Bedroom", "NIGHT", at(22))
        before, config = self.path.read_bytes(), copy.deepcopy(self.butler.config)
        holds, intents = copy.deepcopy(self.butler.holds), copy.deepcopy(self.butler.intents)
        with patch("wiz_butler.os.fsync", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.butler.rename_bulb(MAC, "Reading lamp")
        self.assertEqual(config, self.butler.config)
        self.assertEqual((holds, intents), (self.butler.holds, self.butler.intents))
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual("Bedroom", self.butler.status()["config"]["bulbs"][0]["room"])

    def test_rename_sends_no_bulb_traffic_and_does_not_wake_the_poll_loop(self):
        self.butler.changed.clear()
        self.udp.writes.clear()
        with patch.object(self.udp, "request", side_effect=AssertionError("Rename must not contact a bulb")), \
                patch.object(self.udp, "discover", side_effect=AssertionError("Rename must not discover")):
            self.butler.rename_bulb(MAC, "Reading lamp")
        self.assertEqual([], self.udp.writes)
        self.assertFalse(self.butler.changed.is_set())

    def test_two_bulbs_given_one_name_form_one_room(self):
        second = self.seed_second_bulb()
        self.butler.rename_bulb(MAC, "Kitchen")
        self.butler.rename_bulb(second["mac"], "Kitchen")
        self.assertEqual(["Kitchen", "Kitchen"], [b["room"] for b in self.butler.status()["config"]["bulbs"]])
        self.assertEqual(2, self.butler.command("Kitchen", "NIGHT", at(22))["total"])
        self.assertEqual({MAC, second["mac"]}, set(self.butler.intents))
        with self.assertRaisesRegex(ValueError, "Room is not configured"):
            self.butler.command("Bedroom", "NIGHT", at(22))

    def test_rename_over_http(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.butler))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def rename(value):
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            connection.request("POST", "/v1/bulbs/rename", json.dumps(value))
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result

        code, status = rename({"mac": MAC, "room": "Reading lamp"})
        self.assertEqual((200, "Reading lamp"), (code, status["config"]["bulbs"][0]["room"]))
        self.assertIn("pilots", status)
        for value in ({"mac": "000000000000", "room": "Kitchen"}, {"mac": MAC, "room": " "}, {"mac": MAC}, {"room": "Kitchen"}):
            with self.subTest(value=value):
                self.assertEqual(400, rename(value)[0])
        with patch("wiz_butler.os.fsync", side_effect=OSError("disk full")):
            self.assertEqual(503, rename({"mac": MAC, "room": "Kitchen"})[0])
        self.assertEqual("Reading lamp", Butler(self.path, self.udp).config["bulbs"][0]["room"])

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

    def test_all_http_endpoints_trust_lan_and_status_get_is_cached(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.butler))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(method, path, value=None):
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            connection.request(method, path, json.dumps(value) if value is not None else None)
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result

        for path in ("/v1/status", "/v1/config"):
            self.assertEqual(200, request("GET", path)[0])
        for path in ("/v1/pair", "/v1/identity"):
            self.assertEqual(404, request("POST", path, {})[0])
        with patch.object(self.udp, "request", side_effect=AssertionError("GET is a cached manager snapshot")):
            self.assertEqual([BULB], request("GET", "/v1/status")[1]["config"]["bulbs"])
        self.assertEqual(400, request("POST", "/v1/config", self.config | {"bulbs": []})[0])
        self.assertEqual(200, request("POST", "/v1/config", self.config)[0])
        expected = {key: self.config[key] for key in TIMETABLE_KEYS}
        self.assertEqual(200, request("POST", "/v1/config", self.config | {
            "night": "23:27", "expectedConfig": expected})[0])
        before = self.path.read_text()
        conflict = request("POST", "/v1/config", self.config | {"expectedConfig": expected})
        self.assertEqual((409, {"error": "Timetable changed on another device. Reload before saving."}), conflict)
        self.assertEqual(before, self.path.read_text())
        self.assertEqual(200, request("POST", "/v1/config", self.config)[0])
        self.assertEqual(200, request("POST", "/v1/room", {"room": "Bedroom", "mode": "NIGHT"})[0])
        self.udp.found = {MAC: BULB["ip"]}
        self.assertEqual(MAC, request("POST", "/v1/discover", {})[1]["discovered"][0]["mac"])
        self.assertEqual(200, request("POST", "/v1/bulbs/add", BULB | {"room": "Kitchen"})[0])
        with patch("wiz_butler.time.sleep"):
            self.assertEqual(200, request("POST", "/v1/bulbs/blink", {"mac": MAC})[0])
        self.assertEqual(400, request("POST", "/v1/bulbs/blink", {"mac": "unknown"})[0])
        self.assertEqual(200, request("POST", "/v1/bulbs/remove", {"mac": MAC})[0])
        self.assertEqual(400, request("POST", "/v1/bulbs/remove", {"mac": MAC})[0])

    def test_http_configuration_ignores_legacy_authorization(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.butler))
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

        self.assertEqual(200, request("GET", "/v1/config", token="wrong")[0])
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


class LoopbackTestModeTest(unittest.TestCase):
    """--test-loopback-bulbs exists only for tools/mock_lights.py; production is unchanged."""

    def args(self, **values):
        from argparse import Namespace
        return Namespace(**({"test_loopback_bulbs": True, "test_bulb_port": 48899, "listen": "127.0.0.1",
                             "broadcast": "127.0.0.10", "state": "/tmp/mock/state.json"} | values))

    def test_production_rejects_loopback_bulbs_and_test_mode_rejects_lan_bulbs(self):
        loopback = DEFAULT_CONFIG | {"bulbs": [BULB | {"ip": "127.0.0.11"}]}
        with self.assertRaises(ValueError):
            validate_config(loopback)
        self.assertEqual("127.0.0.11", validate_config(loopback, loopback=True)["bulbs"][0]["ip"])
        with self.assertRaises(ValueError):
            validate_config(DEFAULT_CONFIG | {"bulbs": [BULB]}, loopback=True)

    def test_loopback_butler_refuses_a_lan_bulb(self):
        with tempfile.TemporaryDirectory() as directory:
            butler = Butler(Path(directory) / "state.json", FakeUdp(), loopback=True)
            with self.assertRaises(ValueError):
                butler.add_bulb(BULB)
            self.assertEqual([], FakeUdp().writes)

    def test_test_mode_options_must_stay_on_loopback_and_isolated_state(self):
        from wiz_butler import WIZ_PORT, test_mode_error
        self.assertIsNone(test_mode_error(self.args()))
        self.assertIn("--listen", test_mode_error(self.args(listen="0.0.0.0")))
        self.assertIn("--broadcast", test_mode_error(self.args(broadcast="255.255.255.255")))
        self.assertIn("--broadcast", test_mode_error(self.args(broadcast="192.168.1.255")))
        self.assertIn("household", test_mode_error(self.args(state="/x/state.json"), default_state=Path("/x/state.json")))
        self.assertIsNone(test_mode_error(self.args(test_loopback_bulbs=False, test_bulb_port=WIZ_PORT)))
        self.assertIn("requires", test_mode_error(self.args(test_loopback_bulbs=False)))

    def test_default_udp_still_targets_the_real_wiz_port_and_lan(self):
        udp = Udp("192.168.1.255")
        self.assertEqual((38899, False), (udp.port, udp.loopback_only))
        self.assertTrue(udp.allowed("192.168.1.20"))


if __name__ == "__main__":
    unittest.main()
