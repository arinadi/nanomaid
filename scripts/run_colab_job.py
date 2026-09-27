#!/usr/bin/env python3
"""Run one reviewed NanoMaid code-verification job and always stop its VM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_cli(cli: Path, cli_home: Path, *args: str, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(cli_home)
    env["PATH"] = f"{cli.parent}:{env.get('PATH', '/usr/bin:/bin')}"
    command = [str(cli), "--auth=oauth2", *args]
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            raise RuntimeError(f"Colab CLI command timed out: {args[0] if args else 'unknown'}")
        output.seek(max(0, output.tell() - 64 * 1024))
        stdout = output.read().decode("utf-8", errors="replace")
    return subprocess.CompletedProcess(command, return_code, stdout, None)


def require_free_usage(cli: Path, cli_home: Path) -> None:
    result = run_cli(cli, cli_home, "usage", timeout=60)
    print("Colab usage/cost preflight:")
    print(result.stdout[-4000:])
    if result.returncode != 0:
        raise RuntimeError("Could not verify Colab usage; refusing the job.")
    balance = re.search(r"Current balance:\s*([0-9]+(?:\.[0-9]+)?)\s*compute units", result.stdout, re.I)
    rate = re.search(r"Usage rate:\s*([0-9]+(?:\.[0-9]+)?)\s*(?:compute units?/?h|CU/?h|/hr)", result.stdout, re.I)
    if balance is None or rate is None:
        raise RuntimeError("Colab usage output format is unknown; refusing the job to avoid charges.")
    if float(balance.group(1)) != 0 or float(rate.group(1)) != 0:
        raise RuntimeError("Colab reports non-zero compute-unit balance/rate; no-paid policy blocks this job.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("archive_sha256")
    parser.add_argument("--free-confirmed", action="store_true", help="acknowledge the reviewed zero-cost preflight")
    args = parser.parse_args()
    if not args.free_confirmed:
        parser.error("include --free-confirmed only after reviewing the archive/commands and zero-cost status")

    home = Path.home()
    state = home / ".local/share/nanomaid"
    job_dir = state / "jobs" / args.job_id
    job_file = job_dir / "job.json"
    archive = job_dir / "source.tar.gz"
    cli = state / "colab-venv/bin/colab"
    cli_home = state / "colab-home"
    if not job_file.is_file() or not archive.is_file() or not cli.is_file():
        raise SystemExit("Job staging or Colab CLI missing; run `nanomaid verify plan` first.")
    job = json.loads(job_file.read_text(encoding="utf-8"))
    actual_hash = sha256(archive)
    if actual_hash != args.archive_sha256 or actual_hash != job.get("archive_sha256"):
        raise SystemExit("Archive hash mismatch; re-plan and review the source manifest.")
    print(f"Approved job {args.job_id}; archive SHA-256 {actual_hash}")
    print("Commands:")
    print(json.dumps(job["commands"], indent=2))

    require_free_usage(cli, cli_home)
    session = f"nanomaid-{args.job_id[:8]}"
    session_attempted = False
    result_path = job_dir / "result.txt"
    try:
        session_attempted = True
        created_result = run_cli(cli, cli_home, "new", "-s", session, timeout=180)
        print(created_result.stdout[-4000:])
        if created_result.returncode != 0:
            raise RuntimeError("Colab session allocation failed.")

        for local, remote in (
            (archive, "/content/nanomaid-source.tar.gz"),
            (job_file, "/content/nanomaid-job.json"),
        ):
            uploaded = run_cli(cli, cli_home, "upload", "-s", session, str(local), remote, timeout=300)
            print(uploaded.stdout[-2000:])
            if uploaded.returncode != 0:
                raise RuntimeError(f"Colab upload failed for {local.name}.")

        runner = Path(__file__).with_name("remote_verify.py")
        execution = run_cli(
            cli, cli_home, "exec", "-s", session, "--timeout", "1800", "-f", str(runner), timeout=2100
        )
        print(execution.stdout[-12000:])
        if execution.returncode != 0:
            raise RuntimeError(f"Colab verification failed (exit {execution.returncode}).")

        downloaded = run_cli(
            cli, cli_home, "download", "-s", session, "/content/nanomaid-result.txt", str(result_path), timeout=300
        )
        if downloaded.returncode != 0:
            raise RuntimeError("Could not retrieve text verification log.")
        print(f"Verification log saved at {result_path}")
        return 0
    finally:
        if session_attempted:
            stopped = run_cli(cli, cli_home, "stop", "-s", session, timeout=180)
            print(stopped.stdout[-2000:])
            if stopped.returncode != 0:
                print(f"WARNING: stop the Colab session manually: {session}", file=sys.stderr)
            else:
                listed = run_cli(cli, cli_home, "sessions", timeout=60)
                if listed.returncode == 0 and session in listed.stdout:
                    print(f"WARNING: Colab still lists session {session}; verify and stop it manually.", file=sys.stderr)
        archive.unlink(missing_ok=True)
        job_file.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
