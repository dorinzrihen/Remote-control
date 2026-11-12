import unittest
import xml.etree.ElementTree as ET

import lockscreen_widget_demo as demo


class LockscreenDemoLogicTest(unittest.TestCase):
    def test_only_the_disposable_android16_avd(self):
        self.assertEqual(demo.AVD, demo.require_disposable("uniremote-android16"))
        for name in ("uniremote-pixel-8a", "uniremote-preview", None, "other"):
            with self.assertRaises(demo.Error):
                demo.require_disposable(name)

    def test_console_port_is_adb_discoverable_and_not_the_mock_lights_one(self):
        self.assertTrue(5554 <= demo.CONSOLE_PORT <= 5584 and demo.CONSOLE_PORT % 2 == 0)
        self.assertNotEqual(5580, demo.CONSOLE_PORT)

    def test_avd_ini_gets_the_real_target(self):
        fixed = demo.fix_avd_ini("avd.ini.encoding=UTF-8\npath=/x\ntarget=android-0\n")
        self.assertIn("target=android-36.1", fixed)
        self.assertNotIn("android-0", fixed)
        self.assertEqual(fixed, demo.fix_avd_ini(fixed))

    def test_config_tuning(self):
        tuned = demo.tune_config("hw.ramSize=2G\nhw.keyboard=no\nhw.lcd.width=1080\n")
        self.assertIn("hw.ramSize=4096", tuned)
        self.assertIn("hw.keyboard=yes", tuned)
        self.assertIn("hw.gpu.mode=swiftshader_indirect", tuned)
        self.assertIn("hw.lcd.width=1080", tuned)

    def test_tv_commands_skip_pairing_and_old_entries(self):
        state = {"commands": [
            {"t": 1.0, "source": "ssap", "command": "audio/volumeUp"},
            {"t": 5.0, "source": "ssap", "command": "register", "payload": {"knownKey": True}},
            {"t": 6.0, "source": "ssap", "command": "audio/volumeDown"},
            {"t": 7.0, "source": "pointer", "command": "button", "payload": {"type": "button", "name": "LEFT"}},
        ]}
        self.assertEqual([("ssap", "audio/volumeDown"), ("pointer", "LEFT")], demo.tv_commands(state, since=2.0))
        self.assertEqual(demo.BUTTONS["left"][1], ("pointer", "LEFT"))

    def test_widget_nodes_by_resource_id(self):
        tree = ET.fromstring(f'''<hierarchy>
          <node resource-id="{demo.PACKAGE}:id/w_label" text="LG TV" bounds="[0,0][10,10]" />
          <node resource-id="{demo.PACKAGE}:id/w_vol_up" content-desc="TV volume up" bounds="[0,10][10,20]" />
          <node resource-id="com.android.systemui:id/w_vol_up" bounds="[0,0][1,1]" />
        </hierarchy>''')
        nodes = demo.widget_nodes(tree)
        self.assertEqual({"w_label", "w_vol_up"}, set(nodes))
        self.assertEqual("TV volume up", nodes["w_vol_up"].get("content-desc"))

    def test_fixture_points_only_at_the_loopback_mock(self):
        prefs = demo.preferences().decode()
        self.assertIn('<string name="lg_ip">10.0.2.2</string>', prefs)
        self.assertIn("never household", prefs)


if __name__ == "__main__":
    unittest.main()
