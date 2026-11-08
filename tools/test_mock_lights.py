import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "butler"))
import wiz_butler  # noqa: E402
from mock_lights import DISCOVERY_ADDRESS, NIGHT, REGULAR, Simulator, layout, manager_state, parse_rooms  # noqa: E402


class SimulatorProtocolTest(unittest.TestCase):
    def setUp(self):
        self.sim = Simulator(layout())
        self.mac = next(iter(self.sim.bulbs))

    def request(self, method, params=None, mac=None, ident=7):
        return self.sim.handle(mac or self.mac, json.dumps({"id": ident, "method": method, "params": params or {}}))

    def test_get_pilot_echoes_id_and_state(self):
        reply = self.request("getPilot")
        self.assertEqual((7, "getPilot", self.mac), (reply["id"], reply["method"], reply["result"]["mac"]))
        self.assertEqual(NIGHT["temp"], reply["result"]["temp"])

    def test_set_pilot_changes_state_and_records_command(self):
        self.assertEqual({"success": True}, self.request("setPilot", {"state": False})["result"])
        self.assertFalse(self.request("getPilot")["result"]["state"])
        # Like real firmware, a preset write without "state" turns the bulb on.
        self.request("setPilot", REGULAR)
        pilot = self.request("getPilot")["result"]
        self.assertEqual((True, 100, 6500, 0), (pilot["state"], pilot["dimming"], pilot["temp"], pilot["sceneId"]))
        self.assertEqual(2, len(self.sim.snapshot()[0]["commands"]))

    def test_offline_bulb_is_silent_and_unknown_method_errors(self):
        self.sim.update("Bedroom", {"online": False})
        bedroom = next(b["mac"] for b in self.sim.snapshot() if b["room"] == "Bedroom")
        self.assertIsNone(self.request("getPilot", mac=bedroom))
        self.assertIn("error", self.request("reboot"))
        self.assertIsNone(self.sim.handle(self.mac, b"not json"))

    def test_layout_rooms_new_and_offline(self):
        bulbs = layout(parse_rooms("Kitchen=3, Hall=1"), new=2, offline=("Hall",))
        self.assertEqual(["Kitchen"] * 3 + ["Hall", None, None], [b["room"] for b in bulbs])
        self.assertEqual([True, True, True, False, True, True], [b["online"] for b in bulbs])
        self.assertEqual(4, len(manager_state(bulbs)["config"]["bulbs"]))
        with self.assertRaises(ValueError):
            parse_rooms("Kitchen=0")

    def test_manager_accepts_layout_only_in_loopback_test_mode(self):
        config = manager_state(layout())["config"]
        self.assertEqual(3, len(wiz_butler.validate_config(config, loopback=True)["bulbs"]))
        with self.assertRaisesRegex(ValueError, "private LAN"):
            wiz_butler.validate_config(config)

    def test_sockets_refuse_non_loopback_addresses(self):
        with self.assertRaisesRegex(ValueError, "loopback-only"):
            Simulator(layout(), discovery="192.168.1.255")
        sim = Simulator([dict(layout()[0], ip="192.168.1.20")], port=0)
        with self.assertRaisesRegex(ValueError, "loopback-only"):
            sim.start()
        sim.close()


class RealManagerAgainstSimulatorTest(unittest.TestCase):
    """Runs the unmodified Butler logic over real UDP sockets on loopback."""

    def setUp(self):
        self.sim = Simulator(layout(), port=0)
        self.sim.start()
        self.addCleanup(self.sim.close)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "state.json"
        path.write_text(json.dumps(manager_state(layout())))
        udp = wiz_butler.Udp(DISCOVERY_ADDRESS, self.sim.port, loopback_only=True)
        self.butler = wiz_butler.Butler(path, udp, loopback=True)

    def bulbs(self, room):
        return [b for b in self.sim.snapshot() if b["room"] == room]

    def test_room_commands_change_simulated_bulbs(self):
        result = self.butler.command("Living room", "TOGGLE", time.time())
        self.assertEqual((2, 2), (result["answered"], result["total"]))
        self.assertTrue(all(not b["pilot"]["state"] for b in self.bulbs("Living room")))
        self.butler.command("Living room", "REGULAR", time.time())
        self.assertTrue(all(b["pilot"]["state"] and b["pilot"]["temp"] == 6500 for b in self.bulbs("Living room")))
        self.assertTrue(all(b["pilot"]["temp"] == 2700 for b in self.bulbs("Bedroom")))

    def test_offline_bulb_reports_unreachable(self):
        self.butler.tick(time.time())
        status = self.butler.status()
        bedroom = self.bulbs("Bedroom")[0]["mac"]
        self.assertNotIn(bedroom, status["pilots"])
        self.assertIn(bedroom, status["errors"])
        self.assertEqual(2, len(status["pilots"]))

    def test_discovery_finds_new_bulb_at_its_own_loopback_address(self):
        new = self.bulbs(None)[0]
        found = {d["mac"]: d["ip"] for d in self.butler.discover()["discovered"]}
        self.assertEqual(new["ip"], found[new["mac"]])
        self.assertNotIn(self.bulbs("Bedroom")[0]["mac"], found)
        status = self.butler.add_bulb({"mac": new["mac"], "ip": new["ip"], "room": "Kitchen"})
        self.assertIn("Kitchen", [b["room"] for b in status["config"]["bulbs"]])


class LoopbackModeSafetyTest(unittest.TestCase):
    def test_loopback_udp_never_opens_a_socket_to_the_lan(self):
        with patch("wiz_butler.socket.socket") as factory:
            self.assertIsNone(wiz_butler.Udp("127.0.0.10", 1, loopback_only=True).request("192.168.1.20", "getPilot", {}))
            factory.assert_not_called()
        with self.assertRaises(ValueError):
            wiz_butler.Udp("255.255.255.255", loopback_only=True)


if __name__ == "__main__":
    unittest.main()
