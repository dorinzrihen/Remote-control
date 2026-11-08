import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import android_ui
import mock_e2e

TREE = ET.fromstring('''<hierarchy>
  <node text="Bulbs" bounds="[0,100][200,150]" />
  <node text="Living room" bounds="[0,200][500,240]" />
  <node text="2 bulbs  ·  Night" bounds="[0,240][500,270]" />
  <node content-desc="Living room on / off" bounds="[600,200][700,280]" />
  <node checkable="true" checked="false" bounds="[0,300][300,360]"><node text="Regular" bounds="[0,300][300,360]" /></node>
  <node checkable="true" checked="true" bounds="[300,300][600,360]"><node text="Night" bounds="[300,300][600,360]" /></node>
  <node text="Bedroom" bounds="[0,400][500,440]" />
  <node text="1 bulb  ·  no power or offline" bounds="[0,440][500,470]" />
  <node checkable="true" checked="false" bounds="[300,500][600,560]"><node text="Night" bounds="[300,500][600,560]" /></node>
</hierarchy>''')
ROOMS = ["Living room", "Bedroom"]


class HarnessLogicTest(unittest.TestCase):
    def test_room_section_is_scoped_to_one_card(self):
        living = mock_e2e.section(TREE, "Living room", ROOMS)
        self.assertIn("2 bulbs  ·  Night", [n.get("text") for n in living])
        self.assertNotIn("1 bulb  ·  no power or offline", [n.get("text") for n in living])
        self.assertEqual(["Night"], mock_e2e.selected_in(living))
        self.assertEqual([], mock_e2e.selected_in(mock_e2e.section(TREE, "Bedroom", ROOMS)))
        self.assertEqual([], mock_e2e.section(TREE, "Kitchen", ROOMS))

    def test_status_text_matches_app_format(self):
        self.assertEqual("1 bulb  ·  off", mock_e2e.room_status(1, "off"))
        self.assertEqual("2 bulbs  ·  Night", mock_e2e.room_status(2, "Night"))

    def test_only_the_disposable_avd_is_ever_targeted(self):
        mock_e2e.require_disposable("uniremote-preview")
        for name in ("uniremote-pixel-8a", None, "other"):
            with self.assertRaises(mock_e2e.Error):
                mock_e2e.require_disposable(name)

    def test_android_helpers_refuse_physical_devices_and_find_nodes(self):
        with self.assertRaises(ValueError):
            android_ui.Android("R5CT1234")
        self.assertEqual((150, 330), android_ui.center(android_ui.find(TREE, "Regular")))
        self.assertIsNotNone(android_ui.find(TREE, "no power", exact=False))
        self.assertIsNone(android_ui.find(TREE, "no power"))

    def test_mock_preferences_point_only_at_the_reversed_loopback_manager(self):
        values = {n.get("name"): n for n in ET.fromstring(android_ui.preferences("http://127.0.0.1:8789", mock_e2e.SERVICE_NAME))}
        self.assertEqual("http://127.0.0.1:8789", values["butler_url"].text)
        self.assertIn("never household", values["butler_service_name"].text)

    def test_index_lists_results_and_screenshots(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "shots.json").write_text(json.dumps([{"file": "01-a.png", "caption": "A <b>"}]))
            (out / "results.json").write_text(json.dumps(["PASS: x"]))
            page = mock_e2e.write_index(out).read_text()
            self.assertIn('src="01-a.png"', page)
            self.assertIn("A &lt;b&gt;", page)
            self.assertIn("PASS: x", page)

    def test_kill_only_signals_processes_that_are_still_ours(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(process.kill)
        with patch("mock_e2e.os.kill") as killer:
            mock_e2e.kill(process.pid, "wiz_butler.py")
            killer.assert_not_called()
        mock_e2e.kill(process.pid, "time.sleep")
        self.assertIsNotNone(process.wait(timeout=5))

    def test_default_offline_room_only_for_default_layout(self):
        with patch("mock_e2e.up") as up:
            mock_e2e.main(["up"])
            self.assertEqual(["Bedroom"], up.call_args[0][0].offline)
            mock_e2e.main(["up", "--rooms", "Kitchen=2"])
            self.assertEqual([], up.call_args[0][0].offline)


if __name__ == "__main__":
    unittest.main()
