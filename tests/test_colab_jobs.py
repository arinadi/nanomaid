import contextlib
import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from scripts import prepare_colab_job, remote_verify, run_colab_job


class PrepareColabJobTests(unittest.TestCase):
    def test_accelerator_defaults_to_cpu_and_accepts_t4(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "commands.json"
            spec.write_text(json.dumps({"commands": [["python3", "-V"]]}))
            self.assertEqual(prepare_colab_job.load_job_spec(spec), ([["python3", "-V"]], "CPU"))
            spec.write_text(json.dumps({"commands": [["python3", "-V"]], "accelerator": "T4"}))
            self.assertEqual(prepare_colab_job.load_job_spec(spec), ([["python3", "-V"]], "T4"))

    def test_rejects_unsupported_accelerator(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "commands.json"
            spec.write_text(json.dumps({"commands": [["true"]], "accelerator": "A100"}))
            with self.assertRaisesRegex(ValueError, "accelerator"):
                prepare_colab_job.load_job_spec(spec)

    def test_plan_binds_t4_and_excludes_secrets_and_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "sample-project"
            project.mkdir()
            (project / "main.py").write_text("print('ok')\n")
            (project / ".env").write_text("TOKEN=not-for-upload\n")
            (project / "sample.wav").write_bytes(b"audio")
            (project / "sample.jpg").write_bytes(b"image")
            (project / "sample.zip").write_bytes(b"media archive")
            commands = root / "commands.json"
            commands.write_text(json.dumps({"commands": [["python3", "main.py"]], "accelerator": "T4"}))
            home = root / "home"
            home.mkdir()
            output = io.StringIO()
            with patch.dict(os.environ, {"HOME": str(home)}), \
                 patch("sys.argv", ["prepare_colab_job.py", str(project), str(commands)]), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(prepare_colab_job.main(), 0)

            text = output.getvalue()
            job_id = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("Job: "))
            job_dir = home / ".local/share/nanomaid/jobs" / job_id
            job_file = job_dir / "job.json"
            archive = job_dir / "source.tar.gz"
            job = json.loads(job_file.read_text())
            self.assertEqual(job["accelerator"], "T4")
            self.assertIn(f"Job manifest SHA-256: {hashlib.sha256(job_file.read_bytes()).hexdigest()}", text)
            self.assertIn("sample-project/main.py", text)
            self.assertNotIn("TOKEN=not-for-upload", text)
            with tarfile.open(archive, "r:gz") as tar:
                names = tar.getnames()
            self.assertIn("sample-project/main.py", names)
            self.assertFalse(any(name.endswith((".env", ".wav", ".jpg", ".zip")) for name in names))


class RunColabJobTests(unittest.TestCase):
    def make_job(self, home: Path, accelerator: str = "T4") -> tuple[Path, Path, str, str]:
        job_id = "0123456789ab"
        job_dir = home / ".local/share/nanomaid/jobs" / job_id
        job_dir.mkdir(parents=True)
        cli = home / ".local/share/nanomaid/colab-venv/bin/colab"
        cli.parent.mkdir(parents=True)
        cli.write_text("cli stub")
        archive = job_dir / "source.tar.gz"
        archive.write_bytes(b"reviewed source")
        job = {
            "job_id": job_id,
            "project_name": "sample-project",
            "accelerator": accelerator,
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "commands": [["python3", "-m", "unittest", "discover"]],
            "timeout_seconds": 30,
        }
        job_file = job_dir / "job.json"
        job_file.write_text(json.dumps(job) + "\n")
        return archive, job_file, job["archive_sha256"], hashlib.sha256(job_file.read_bytes()).hexdigest()

    def test_t4_job_requests_t4_and_stops_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            archive, job_file, archive_hash, job_hash = self.make_job(home)
            calls = []

            def fake_cli(cli, cli_home, *args, timeout=1800):
                calls.append(args)
                if args[0] == "usage":
                    output = "Current balance: 0.00 compute units\nUsage rate: 1.07/hr\n"
                elif args[0] == "status":
                    output = "GPU: Tesla T4\n"
                else:
                    output = "ok\n"
                return CompletedProcess(args, 0, output, None)

            with patch.dict(os.environ, {"HOME": str(home)}), \
                 patch("sys.argv", ["run_colab_job.py", "0123456789ab", archive_hash, job_hash, "--free-confirmed"]), \
                 patch.object(run_colab_job, "run_cli", side_effect=fake_cli), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_colab_job.main(), 0)

            new_args = next(args for args in calls if args[0] == "new")
            self.assertEqual(new_args[-2:], ("--gpu", "T4"))
            self.assertIn(("status", "-s", "nanomaid-01234567"), calls)
            self.assertIn(("stop", "-s", "nanomaid-01234567"), calls)
            self.assertFalse(archive.exists())
            self.assertFalse(job_file.exists())

    def test_cpu_job_does_not_request_gpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            archive, job_file, archive_hash, job_hash = self.make_job(home, accelerator="CPU")
            calls = []

            def fake_cli(cli, cli_home, *args, timeout=1800):
                calls.append(args)
                output = "Current balance: 0.00 compute units\nUsage rate: 0.00/hr\n" if args[0] == "usage" else "ok\n"
                return CompletedProcess(args, 0, output, None)

            with patch.dict(os.environ, {"HOME": str(home)}), \
                 patch("sys.argv", ["run_colab_job.py", "0123456789ab", archive_hash, job_hash, "--free-confirmed"]), \
                 patch.object(run_colab_job, "run_cli", side_effect=fake_cli), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_colab_job.main(), 0)

            new_args = next(args for args in calls if args[0] == "new")
            self.assertEqual(new_args, ("new", "-s", "nanomaid-01234567"))
            self.assertFalse(any(args[0] == "status" for args in calls))
            self.assertFalse(archive.exists())
            self.assertFalse(job_file.exists())

    def test_manifest_hash_mismatch_refuses_remote_calls_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            archive, job_file, archive_hash, _ = self.make_job(home)
            with patch.dict(os.environ, {"HOME": str(home)}), \
                 patch("sys.argv", ["run_colab_job.py", "0123456789ab", archive_hash, "0" * 64, "--free-confirmed"]), \
                 patch.object(run_colab_job, "run_cli") as run_cli, \
                 contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(SystemExit, "Job manifest hash mismatch"):
                run_colab_job.main()

            run_cli.assert_not_called()
            self.assertFalse(archive.exists())
            self.assertFalse(job_file.exists())

    def test_nonzero_balance_after_allocation_stops_before_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            archive, job_file, archive_hash, job_hash = self.make_job(home)
            calls = []

            def fake_cli(cli, cli_home, *args, timeout=1800):
                calls.append(args)
                if args[0] == "usage":
                    count = sum(call[0] == "usage" for call in calls)
                    balance = "0.00" if count == 1 else "0.25"
                    output = f"Current balance: {balance} compute units\nUsage rate: 1.07/hr\n"
                else:
                    output = "ok\n"
                return CompletedProcess(args, 0, output, None)

            with patch.dict(os.environ, {"HOME": str(home)}), \
                 patch("sys.argv", ["run_colab_job.py", "0123456789ab", archive_hash, job_hash, "--free-confirmed"]), \
                 patch.object(run_colab_job, "run_cli", side_effect=fake_cli), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                 self.assertRaisesRegex(RuntimeError, "zero paid-unit balance"):
                run_colab_job.main()

            self.assertFalse(any(call[0] == "upload" for call in calls))
            self.assertIn(("stop", "-s", "nanomaid-01234567"), calls)
            self.assertFalse(archive.exists())
            self.assertFalse(job_file.exists())

    def test_t4_session_status_rejects_cpu(self):
        with patch.object(
            run_colab_job, "run_cli",
            return_value=CompletedProcess([], 0, "Hardware: CPU\n", None),
        ):
            with self.assertRaisesRegex(RuntimeError, "T4 runtime"):
                run_colab_job.require_t4_session(Path("colab"), Path("home"), "nanomaid-test")


class RemoteVerifyTests(unittest.TestCase):
    def test_t4_gate_accepts_t4_and_rejects_other_gpu(self):
        with patch.object(
            remote_verify.subprocess, "run",
            return_value=CompletedProcess([], 0, stdout="Tesla T4\n"),
        ):
            remote_verify.require_t4()
        with patch.object(
            remote_verify.subprocess, "run",
            return_value=CompletedProcess([], 0, stdout="Tesla V100\n"),
        ):
            with self.assertRaisesRegex(RuntimeError, "T4 required"):
                remote_verify.require_t4()


if __name__ == "__main__":
    unittest.main()
