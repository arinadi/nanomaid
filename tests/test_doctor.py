import os
import pty
import select
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DoctorTests(unittest.TestCase):
    def make_fixture(self, temp: Path) -> tuple[Path, Path, dict[str, str]]:
        project = temp / "project"
        for directory in ("scripts", "templates", "skills/colab", "bin"):
            (project / directory).mkdir(parents=True, exist_ok=True)
        for relative in (
            "doctor.sh",
            "scripts/merge_agents.py",
            "scripts/merge_opencode_config.py",
            "templates/AGENTS.nanomaid.md",
            "skills/colab/SKILL.md",
        ):
            shutil.copy2(ROOT / relative, project / relative)

        marker = temp / "installer-was-run"
        installer = project / "install.sh"
        installer.write_text(
            "#!/usr/bin/env bash\n"
            "printf 'mock installer ran\\n'\n"
            "touch -- \"$NANOMAID_INSTALLER_MARKER\"\n"
        )
        installer.chmod(0o755)

        fake_bin = temp / "bin"
        fake_bin.mkdir()
        (fake_bin / "opencode").write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"${1:-}\" == --version ]]; then echo 'opencode v2.0.18'; exit 0; fi\n"
            "if [[ \"${1:-}\" == service && \"${2:-}\" == status ]]; then echo 'http://127.0.0.1:49374'; exit 0; fi\n"
            "exit 1\n"
        )
        (fake_bin / "loginctl").write_text("#!/usr/bin/env bash\necho yes\n")
        (fake_bin / "systemctl").write_text("#!/usr/bin/env bash\nexit 1\n")
        for command in fake_bin.iterdir():
            command.chmod(0o755)

        home = temp / "home"
        bot_home = home / ".config/opencode-telegram-bot"
        bot_home.mkdir(parents=True)
        config_home = temp / "xdg"
        environment = os.environ.copy()
        environment.update({
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config_home),
            "NANOMAID_ROOT": str(project),
            "NANOMAID_INSTALLER_MARKER": str(marker),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        })
        return project, home, environment

    def run_interactive_doctor(self, project: Path, environment: dict[str, str], answer: str):
        master, slave = pty.openpty()
        process = subprocess.Popen(
            [str(project / "doctor.sh")], stdin=slave, stdout=slave, stderr=slave,
            env=environment, close_fds=True,
        )
        os.close(slave)
        output = bytearray()
        prompt = b"Run ./install.sh now? [y/N]"
        deadline = time.monotonic() + 10
        answered = False
        try:
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([master], [], [], remaining)[0]:
                    process.kill()
                    self.fail("doctor did not reach/finish its installer prompt")
                try:
                    output.extend(os.read(master, 8192))
                except OSError:
                    break
                if not answered and prompt in output:
                    os.write(master, f"{answer}\n".encode())
                    answered = True
            process.wait(timeout=2)
        finally:
            os.close(master)
        self.assertTrue(answered, output.decode(errors="replace"))
        return process.returncode, output.decode(errors="replace")

    def test_doctor_repairs_regular_config_mode_without_reading_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, home, environment = self.make_fixture(Path(tmp))
            env_file = home / ".config/opencode-telegram-bot/.env"
            original = "TELEGRAM_BOT_TOKEN=placeholder\n"
            env_file.write_text(original)
            env_file.chmod(0o640)

            result = subprocess.run(
                [str(project / "doctor.sh")], input="", env=environment,
                capture_output=True, text=True, check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("FIX: bot config permissions changed from 640 to 0600", result.stdout)
            self.assertEqual(env_file.read_text(), original)
            self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
            self.assertFalse((Path(tmp) / "installer-was-run").exists())

    def test_doctor_does_not_change_symlink_target_or_run_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, home, environment = self.make_fixture(Path(tmp))
            target = Path(tmp) / "unrelated-file"
            original = "keep this content\n"
            target.write_text(original)
            target.chmod(0o640)
            env_file = home / ".config/opencode-telegram-bot/.env"
            env_file.symlink_to(target)

            result = subprocess.run(
                [str(project / "doctor.sh")], input="", env=environment,
                capture_output=True, text=True, check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to inspect or change its target", result.stdout)
            self.assertFalse((Path(tmp) / "installer-was-run").exists())
            self.assertTrue(env_file.is_symlink())
            self.assertEqual(target.read_text(), original)
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_doctor_does_not_run_installer_for_nonregular_bot_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, home, environment = self.make_fixture(Path(tmp))
            env_path = home / ".config/opencode-telegram-bot/.env"
            env_path.mkdir()

            result = subprocess.run(
                [str(project / "doctor.sh")], input="", env=environment,
                capture_output=True, text=True, check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not a regular file", result.stdout)
            self.assertFalse((Path(tmp) / "installer-was-run").exists())
            self.assertTrue(env_path.is_dir())

    def test_doctor_asks_before_global_and_dependency_repairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, _, environment = self.make_fixture(Path(tmp))

            result, output = self.run_interactive_doctor(project, environment, "n")

            self.assertNotEqual(result, 0)
            self.assertIn("Running the installer may", output)
            self.assertIn("installer repair skipped", output)
            self.assertFalse((Path(tmp) / "installer-was-run").exists())

    def test_doctor_runs_installer_only_after_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, _, environment = self.make_fixture(Path(tmp))

            result, output = self.run_interactive_doctor(project, environment, "y")

            self.assertNotEqual(result, 0)
            self.assertIn("mock installer ran", output)
            self.assertTrue((Path(tmp) / "installer-was-run").exists())

    def test_cli_uses_doctor_and_removes_check_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, home, environment = self.make_fixture(Path(tmp))
            environment["NANOMAID_ROOT"] = str(project)
            environment["HOME"] = str(home)
            result = subprocess.run(
                ["bash", str(ROOT / "bin/nanomaid"), "doctor", "--help"],
                env=environment, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("NanoMaid doctor", result.stdout)

            old_command = subprocess.run(
                ["bash", str(ROOT / "bin/nanomaid"), "check"],
                env=environment, capture_output=True, text=True, check=False,
            )
            self.assertEqual(old_command.returncode, 2)
            self.assertFalse((ROOT / "check.sh").exists())

            old_installer_flag = subprocess.run(
                [str(ROOT / "install.sh"), "--check"],
                env=environment, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(old_installer_flag.returncode, 0)
            self.assertIn("--doctor", old_installer_flag.stderr)


if __name__ == "__main__":
    unittest.main()
