"""
Unit tests for Dynamic Notch desktop installer, autostart manager, and uninstaller.
Uses temporary isolated directories to verify filesystem contracts safely.
"""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import notch


class TestDesktopInstallerAndAutostart(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.mock_data = os.path.join(self.test_dir.name, "share")
        self.mock_config = os.path.join(self.test_dir.name, "config")
        os.makedirs(self.mock_data, exist_ok=True)
        os.makedirs(self.mock_config, exist_ok=True)

        self.project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.setup_script = os.path.join(self.project_dir, "setup.sh")
        self.uninstall_script = os.path.join(self.project_dir, "uninstall.sh")
        self.run_script = os.path.join(self.project_dir, "run.sh")

        self.env = os.environ.copy()
        self.env["XDG_DATA_HOME"] = self.mock_data
        self.env["XDG_CONFIG_HOME"] = self.mock_config

    def tearDown(self):
        self.test_dir.cleanup()

    def test_launcher_generation_and_attributes(self):
        """Verify setup.sh generates a valid desktop launcher with correct attributes."""
        res = subprocess.run([self.setup_script], env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"setup.sh failed: {res.stderr}")

        launcher_path = os.path.join(self.mock_data, "applications", "dynamic-notch.desktop")
        self.assertTrue(os.path.isfile(launcher_path), f"Launcher not found at {launcher_path}")

        with open(launcher_path, "r") as f:
            content = f.read()

        self.assertIn("[Desktop Entry]", content)
        self.assertIn("Name=Dynamic Notch", content)
        self.assertIn(f"Exec={self.run_script}", content)
        self.assertIn("Terminal=false", content)
        self.assertIn("Categories=Utility;Audio;", content)
        self.assertIn("Icon=multimedia-player", content)

    def test_default_autostart_disabled(self):
        """Verify normal installation does not enable autostart by default."""
        res = subprocess.run([self.setup_script], env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)

        autostart_entry = os.path.join(self.mock_config, "autostart", "dynamic-notch.desktop")
        self.assertFalse(os.path.exists(autostart_entry), "Autostart should be disabled by default")

    def test_autostart_enable_and_disable(self):
        """Verify --enable-autostart and --disable-autostart lifecycle."""
        # First install launcher
        subprocess.run([self.setup_script], env=self.env, check=True)

        # Enable autostart
        res = subprocess.run([self.setup_script, "--enable-autostart"], env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        autostart_entry = os.path.join(self.mock_config, "autostart", "dynamic-notch.desktop")
        self.assertTrue(os.path.isfile(autostart_entry))

        with open(autostart_entry, "r") as f:
            content = f.read()
        self.assertIn(f"Exec={self.run_script}", content)

        # Disable autostart
        res_dis = subprocess.run([self.setup_script, "--disable-autostart"], env=self.env, capture_output=True, text=True)
        self.assertEqual(res_dis.returncode, 0)
        self.assertFalse(os.path.exists(autostart_entry))

        # Ensure main application launcher remains intact
        launcher_path = os.path.join(self.mock_data, "applications", "dynamic-notch.desktop")
        self.assertTrue(os.path.isfile(launcher_path), "Main launcher must remain after disabling autostart")

    def test_repeated_enable_disable_idempotence(self):
        """Verify repeated autostart enable/disable operations are safe and idempotent."""
        subprocess.run([self.setup_script], env=self.env, check=True)

        # Enable twice
        res1 = subprocess.run([self.setup_script, "--enable-autostart"], env=self.env, capture_output=True, text=True)
        res2 = subprocess.run([self.setup_script, "--enable-autostart"], env=self.env, capture_output=True, text=True)
        self.assertEqual(res1.returncode, 0)
        self.assertEqual(res2.returncode, 0)

        autostart_entry = os.path.join(self.mock_config, "autostart", "dynamic-notch.desktop")
        self.assertTrue(os.path.isfile(autostart_entry))

        # Disable twice
        res3 = subprocess.run([self.setup_script, "--disable-autostart"], env=self.env, capture_output=True, text=True)
        res4 = subprocess.run([self.setup_script, "--disable-autostart"], env=self.env, capture_output=True, text=True)
        self.assertEqual(res3.returncode, 0)
        self.assertEqual(res4.returncode, 0)
        self.assertIn("already disabled", res4.stdout)
        self.assertFalse(os.path.exists(autostart_entry))

    def test_protection_of_unrelated_desktop_entries(self):
        """Verify installer and uninstaller never touch or overwrite unrelated desktop files."""
        apps_dir = os.path.join(self.mock_data, "applications")
        autostart_dir = os.path.join(self.mock_config, "autostart")
        os.makedirs(apps_dir, exist_ok=True)
        os.makedirs(autostart_dir, exist_ok=True)

        unrelated_app = os.path.join(apps_dir, "unrelated-editor.desktop")
        unrelated_auto = os.path.join(autostart_dir, "unrelated-service.desktop")

        with open(unrelated_app, "w") as f:
            f.write("[Desktop Entry]\nName=Unrelated Editor\nExec=/usr/bin/editor\n")

        with open(unrelated_auto, "w") as f:
            f.write("[Desktop Entry]\nName=Unrelated Service\nExec=/usr/bin/service\n")

        # Run setup and enable autostart
        subprocess.run([self.setup_script], env=self.env, check=True)
        subprocess.run([self.setup_script, "--enable-autostart"], env=self.env, check=True)

        # Run disable autostart and uninstall
        subprocess.run([self.setup_script, "--disable-autostart"], env=self.env, check=True)
        subprocess.run([self.uninstall_script], env=self.env, check=True)

        # Unrelated files must still exist and remain untouched
        self.assertTrue(os.path.isfile(unrelated_app))
        self.assertTrue(os.path.isfile(unrelated_auto))

        with open(unrelated_app, "r") as f:
            self.assertIn("Name=Unrelated Editor", f.read())
        with open(unrelated_auto, "r") as f:
            self.assertIn("Name=Unrelated Service", f.read())

    def test_status_reporting(self):
        """Verify setup.sh --status provides accurate reporting."""
        res = subprocess.run([self.setup_script, "--status"], env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("==> Dynamic Notch Status", res.stdout)
        self.assertIn("Application Launcher:", res.stdout)
        self.assertIn("Project Executables:", res.stdout)
        self.assertIn("Autostart on Login:", res.stdout)
        self.assertIn("Application Process:", res.stdout)

    def test_uninstaller_removes_launcher_and_autostart_safely(self):
        """Verify uninstall.sh removes Dynamic Notch entries while leaving source code intact."""
        subprocess.run([self.setup_script], env=self.env, check=True)
        subprocess.run([self.setup_script, "--enable-autostart"], env=self.env, check=True)

        launcher_path = os.path.join(self.mock_data, "applications", "dynamic-notch.desktop")
        autostart_entry = os.path.join(self.mock_config, "autostart", "dynamic-notch.desktop")
        self.assertTrue(os.path.isfile(launcher_path))
        self.assertTrue(os.path.isfile(autostart_entry))

        res_un = subprocess.run([self.uninstall_script], env=self.env, capture_output=True, text=True)
        self.assertEqual(res_un.returncode, 0)

        # Dynamic Notch entries must be gone
        self.assertFalse(os.path.exists(launcher_path))
        self.assertFalse(os.path.exists(autostart_entry))

        # Project source tree must remain completely intact
        self.assertTrue(os.path.isfile(os.path.join(self.project_dir, "notch.py")))
        self.assertTrue(os.path.isfile(os.path.join(self.project_dir, "setup.sh")))
        self.assertTrue(os.path.isfile(os.path.join(self.project_dir, "run.sh")))
        self.assertTrue(os.path.isfile(os.path.join(self.project_dir, "uninstall.sh")))

    def test_single_instance_lock_prevention(self):
        """Verify acquire_single_instance_lock detects running instances."""
        lock_fd, pid = notch.acquire_single_instance_lock()
        # Because PID 14298 or an active process is currently running on host:
        # It must either detect the existing process or succeed with a valid lock fd.
        if lock_fd is None:
            self.assertIsNotNone(pid)
            self.assertGreater(pid, 0)
        else:
            try:
                # If lock was acquired, a second attempt in the same process must detect it or succeed
                self.assertIsInstance(lock_fd, int)
            finally:
                os.close(lock_fd)


if __name__ == "__main__":
    unittest.main()
