import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallerSafetyTests(unittest.TestCase):
    def test_dry_run_refuses_symlinked_bot_config_before_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            bot_home = home / ".config/opencode-telegram-bot"
            bot_home.mkdir(parents=True)
            referent = Path(tmp) / "private-data"
            original = "keep this file unchanged\n"
            referent.write_text(original)
            referent.chmod(0o640)
            env_file = bot_home / ".env"
            env_file.symlink_to(referent)
            environment = os.environ.copy()
            environment["HOME"] = str(home)
            environment["XDG_CONFIG_HOME"] = str(home / ".config")

            result = subprocess.run(
                [str(ROOT / "install.sh"), "--dry-run"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Bot config is a symlink", result.stderr)
            self.assertTrue(env_file.is_symlink())
            self.assertEqual(referent.read_text(), original)
            self.assertEqual(referent.stat().st_mode & 0o777, 0o640)
            self.assertFalse((home / ".local").exists())

    def test_dry_run_refuses_nonregular_bot_config_before_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            bot_home = home / ".config/opencode-telegram-bot"
            bot_home.mkdir(parents=True)
            env_path = bot_home / ".env"
            env_path.mkdir()
            environment = os.environ.copy()
            environment["HOME"] = str(home)
            environment["XDG_CONFIG_HOME"] = str(home / ".config")

            result = subprocess.run(
                [str(ROOT / "install.sh"), "--dry-run"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Bot config is not a regular file", result.stderr)
            self.assertTrue(env_path.is_dir())
            self.assertFalse((home / ".local").exists())


if __name__ == "__main__":
    unittest.main()
