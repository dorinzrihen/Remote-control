import importlib.util
from pathlib import Path
import unittest

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
