import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import signal

spec = importlib.util.spec_from_file_location("install_launcher", Path(__file__).parent / "macos/install_launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class MacLauncherTest(unittest.TestCase):
    def test_app_has_explicit_network_permission_description(self):
        info = launcher.application_info(Path("/Users/test/repos/Remote-control/butler/run-butler.sh"))
        self.assertEqual("com.uniremote.lights", info["CFBundleIdentifier"])
        self.assertTrue(info["NSLocalNetworkUsageDescription"])
        self.assertTrue(info["LSUIElement"])
        self.assertNotIn("UNIREMOTE_TOKEN", str(info))

    def test_login_job_retains_responsible_app_identity(self):
        app = Path("/Users/test/Applications/Butler Lights.app")
        job = launcher.login_job(Path("/Users/test"), app)
        self.assertEqual(["/usr/bin/open", "-W", "-g", str(app)], job["ProgramArguments"])
        self.assertEqual(["com.uniremote.lights"], job["AssociatedBundleIdentifiers"])
        self.assertTrue(job["RunAtLoad"])
        self.assertTrue(job["KeepAlive"])

    def test_idle_old_launcher_can_be_closed_without_rebuilding_identity(self):
        app = Path("/Users/test/Applications/Butler Lights.app")
        binary = str(app / "Contents/MacOS/ButlerLights")
        with patch.object(launcher.subprocess, "check_output", side_effect=[f"123 {binary}\n", f"123 1 {binary}\n"]), \
             patch.object(launcher.time, "monotonic", side_effect=[0, 9]), \
             patch.object(launcher.os, "kill") as kill:
            launcher.stop_running_app(app)
        self.assertEqual([(123, signal.SIGTERM), (123, signal.SIGKILL)], [c.args for c in kill.call_args_list])

    def test_unresponsive_launcher_with_manager_is_not_force_killed(self):
        app = Path("/Users/test/Applications/Butler Lights.app")
        binary = str(app / "Contents/MacOS/ButlerLights")
        with patch.object(launcher.subprocess, "check_output", side_effect=[f"123 {binary}\n", f"123 1 {binary}\n124 123 Python\n"]), \
             patch.object(launcher.time, "monotonic", side_effect=[0, 9]), \
             patch.object(launcher.os, "kill") as kill, self.assertRaises(SystemExit):
            launcher.stop_running_app(app)
        self.assertEqual([(123, signal.SIGTERM)], [c.args for c in kill.call_args_list])
