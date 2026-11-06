"""Host-independent tests; no SDK, physical phone or light manager is contacted."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import emulator as e


def result(text="", code=0):
    return subprocess.CompletedProcess([], code, text)


class EmulatorTests(unittest.TestCase):
    def device(self):
        d = object.__new__(e.Device)
        d.system = "Linux"
        d.env = {}
        d.adb = Path("sdk/platform-tools/adb")
        d.emulator = Path("sdk/emulator/emulator")
        d.local = Path(".local/emulator")
        return d

    def test_sdk_discovery_order_and_local_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "local.properties").write_text(r"sdk.dir=C\:\\Users\\Dorin\\Android\\Sdk")
            paths = list(e.sdk_candidates({"ANDROID_HOME": "/first", "ANDROID_SDK_ROOT": "/second"},
                                         Path("/home/user"), "Linux", root))
            self.assertEqual(paths[:3], [Path("/first"), Path("/second"), Path(r"C:\Users\Dorin\Android\Sdk")])
            self.assertEqual(paths[-1], root / ".local/build-tools/android-sdk")

    def test_standard_mac_and_windows_sdk_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIn(Path("/Users/a/Library/Android/sdk"),
                          list(e.sdk_candidates({}, Path("/Users/a"), "Darwin", root)))
            self.assertIn(Path("C:/Local/Android/Sdk"),
                          list(e.sdk_candidates({"LOCALAPPDATA": "C:/Local"}, root, "Windows", root)))

    def test_host_image_architecture(self):
        for host in ("AMD64", "x86_64"):
            self.assertEqual(e.image_abi(host), "x86_64")
        for host in ("arm64", "aarch64"):
            self.assertEqual(e.image_abi(host), "arm64-v8a")
        with self.assertRaises(e.Error):
            e.image_abi("mips")

    def test_selection_uses_avd_name_not_port_or_usb(self):
        d = self.device()
        calls = []

        def adb(*args, **kwargs):
            calls.append(args)
            if args == ("devices",):
                return result("List of devices attached\nphone123\tdevice\nemulator-5554\tdevice\nemulator-5560\toffline\n")
            return result("other-avd\nOK\n" if args[1] == "emulator-5554" else e.AVD + "\nOK\n")

        d.adb_run = adb
        self.assertEqual(d.ours(), "emulator-5560")
        self.assertFalse(any("phone123" in call for call in calls))

    def test_unresponsive_adb_not_selected(self):
        d = self.device()
        d.serials = Mock(return_value=["emulator-5554"])
        d.adb_run = Mock(side_effect=subprocess.TimeoutExpired("adb", 5))
        self.assertIsNone(d.ours())

    def test_duplicate_avds_fail(self):
        d = self.device()
        d.serials = Mock(return_value=["emulator-5554", "emulator-5556"])
        d.adb_run = Mock(return_value=result(e.AVD + "\nOK\n"))
        with self.assertRaises(e.Error):
            d.ours()

    def test_window_mode_detection(self):
        d = self.device()
        for flags, headless in (("-no-window", True), ("", False)):
            d.processes = Mock(return_value=["qemu -avd " + e.AVD + " " + flags])
            self.assertEqual(d.headless(), headless)
        d.processes = Mock(return_value=[])
        with self.assertRaises(e.Error):
            d.headless()

    def test_processes_match_exact_own_avd(self):
        d = self.device()
        with patch.object(e, "run", return_value=result(
                f"qemu -avd {e.AVD} -gpu swiftshader\nqemu -avd {e.AVD}-other\nqemu -avd uniremote-preview\n")):
            self.assertEqual(len(d.processes()), 1)

    def configured_dev(self, headless=False):
        d = self.device()
        for method in ("java", "ensure_avd", "boot", "stop"):
            setattr(d, method, Mock())
        d.ours = Mock(return_value="emulator-5562")
        d.headless = Mock(return_value=headless)
        d.launch = Mock(return_value="emulator-5564")
        d.adb_run = Mock(side_effect=[result("Success"), result("Status: ok")])
        return d

    def test_window_reuse_preserves_data_and_installs_same_app(self):
        d = self.configured_dev()
        with patch.object(e, "run", return_value=result()):
            d.dev()
        d.launch.assert_not_called()
        d.stop.assert_not_called()
        calls = d.adb_run.call_args_list
        self.assertEqual(calls[0].args[:4], ("-s", "emulator-5562", "install", "-r"))
        self.assertIn(e.PACKAGE + "/" + e.ACTIVITY, calls[1].args)
        self.assertNotIn("clear", str(calls))
        self.assertNotIn("wipe", str(calls))

    def test_headless_restart_targets_only_own_serial(self):
        d = self.configured_dev(headless=True)
        d.processes = Mock(return_value=[])
        with patch.object(e, "run", return_value=result()):
            d.dev()
        d.stop.assert_called_once_with("emulator-5562")
        d.launch.assert_called_once()
        d.boot.assert_called_once_with("emulator-5564")

    def test_build_failure_never_installs_or_starts(self):
        d = self.configured_dev()
        with patch.object(e, "run", side_effect=e.Error("build failed")):
            with self.assertRaises(e.Error):
                d.dev()
        d.ensure_avd.assert_not_called()
        d.adb_run.assert_not_called()
        d.launch.assert_not_called()

    def test_boot_failure_never_installs(self):
        d = self.configured_dev()
        d.boot.side_effect = e.Error("not booted")
        with patch.object(e, "run", return_value=result()):
            with self.assertRaises(e.Error):
                d.dev()
        d.adb_run.assert_not_called()

    def test_windows_uses_gradle_bat(self):
        d = self.configured_dev()
        d.system = "Windows"
        with patch.object(e, "run", return_value=result()) as run:
            d.dev()
        self.assertEqual(run.call_args.args[0][0].name, "gradlew.bat")

    def test_nonzero_install_does_not_launch(self):
        d = self.configured_dev()
        d.adb_run.side_effect = e.Error("install failed")
        with patch.object(e, "run", return_value=result()):
            with self.assertRaises(e.Error):
                d.dev()
        self.assertEqual(d.adb_run.call_count, 1)

    def test_stop_keeps_data_and_only_kills_identified_serial(self):
        d = self.device()
        d.adb_run = Mock(return_value=result("OK"))
        d.serials = Mock(return_value=["emulator-5554"])
        d.processes = Mock(return_value=[])
        d.stop("emulator-5562")
        d.adb_run.assert_called_once_with("-s", "emulator-5562", "emu", "kill", timeout=10)

    def test_launch_is_windowed_and_never_wipes(self):
        d = self.device()
        d.env = {"DISPLAY": ":0"}
        d.ours = Mock(return_value="emulator-5568")
        with tempfile.TemporaryDirectory() as tmp:
            d.local = Path(tmp)
            process = Mock()
            process.poll.return_value = None
            with patch.object(e.subprocess, "Popen", return_value=process) as popen:
                self.assertEqual(d.launch(), "emulator-5568")
            args = popen.call_args.args[0]
            self.assertEqual(args[1:3], ["-avd", e.AVD])
            self.assertNotIn("-no-window", args)
            self.assertNotIn("-wipe-data", args)

    def test_launch_requires_graphical_linux_session(self):
        with self.assertRaises(e.Error):
            self.device().launch()

    def test_boot_timeout_is_bounded(self):
        d = self.device()
        d.adb_run = Mock(return_value=result("0"))
        with patch.object(e.time, "monotonic", side_effect=[0, 1, 181]), patch.object(e.time, "sleep"):
            with self.assertRaises(e.Error):
                d.boot("emulator-5562")
        self.assertEqual(d.adb_run.call_count, 1)

    def test_windows_process_discovery(self):
        d = self.device()
        d.system = "Windows"
        with patch.object(e, "run", return_value=result(f'qemu.exe -avd {e.AVD} -gpu swiftshader')) as run:
            self.assertEqual(len(d.processes()), 1)
        self.assertEqual(run.call_args.args[0][0], "powershell.exe")

    def test_existing_avd_is_not_recreated(self):
        d = self.device()
        with patch.object(e.Path, "is_file", return_value=True), patch.object(e, "run", return_value=result(e.AVD)) as run:
            d.ensure_avd()
        self.assertEqual(run.call_count, 1)
        self.assertIn("-list-avds", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
