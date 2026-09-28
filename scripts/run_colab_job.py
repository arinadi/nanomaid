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


def read_colab_usage(cli: Path, cli_home: Path) -> tuple[float, float | None]:
    result = run_cli(cli, cli_home, "usage", timeout=60)
    if result.returncode != 0:
        raise RuntimeError("Could not verify Colab usage; refusing the job.")
    balance = re.search(r"Current balance:\s*([0-9]+(?:\.[0-9]+)?)\s*compute units", result.stdout, re.I)
    rate = re.search(r"Usage rate:\s*([0-9]+(?:\.[0-9]+)?)\s*(?:compute units?/?h|CU/?h|/hr)", result.stdout, re.I)
    if balance is None:
        raise RuntimeError("Colab paid-unit balance is missing; refusing the job.")
    balance_units = float(balance.group(1))
    rate_per_hour = float(rate.group(1)) if rate is not None else None
    if balance_units < 0 or (rate_per_hour is not None and rate_per_hour < 0):
        raise RuntimeError("Colab reported invalid usage values; refusing the job.")
    rate_text = f"{rate_per_hour:.2f} CU/hr" if rate_per_hour is not None else "not reported"
    print(f"Colab usage: balance={balance_units:.2f} CU, rate={rate_text}")
    return balance_units, rate_per_hour


def require_zero_paid_balance(balance_units: float) -> None:
    if balance_units != 0:
        raise RuntimeError("NanoMaid only permits zero paid-unit balance; refusing the job.")


def require_t4_session(cli: Path, cli_home: Path, session: str) -> None:
    result = run_cli(cli, cli_home, "status", "-s", session, timeout=60)
    if result.returncode != 0 or not re.search(r"\bT4\b", result.stdout, re.I):
        raise RuntimeError("Colab did not confirm a T4 runtime; refusing to upload source.")
    print("Colab hardware preflight: T4 confirmed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("archive_sha256")
    parser.add_argument("job_sha256")
    parser.add_argument("--free-confirmed", action="store_true", help="acknowledge the reviewed zero-paid-balance/T4 preflight")
    args = parser.parse_args()
    if not args.free_confirmed:
        parser.error("include --free-confirmed only after reviewing the archive/commands and zero paid-unit balance")

    home = Path.home()
    state = home / ".local/share/nanomaid"
    job_dir = state / "jobs" / args.job_id
    job_file = job_dir / "job.json"
    archive = job_dir / "source.tar.gz"
    cli = state / "colab-venv/bin/colab"
    cli_home = state / "colab-home"
    if not job_file.is_file() or not archive.is_file() or not cli.is_file():
        archive.unlink(missing_ok=True)
        job_file.unlink(missing_ok=True)
        raise SystemExit("Job staging or Colab CLI missing; run `nanomaid verify plan` first.")
    session = f"nanomaid-{args.job_id[:8]}"
    session_attempted = False
    result_path = job_dir / "result.txt"
    try:
        job = json.loads(job_file.read_text(encoding="utf-8"))
        actual_hash = sha256(archive)
        if actual_hash != args.archive_sha256 or actual_hash != job.get("archive_sha256"):
            raise SystemExit("Archive hash mismatch; re-plan and review the source manifest.")
        actual_job_hash = sha256(job_file)
        if actual_job_hash != args.job_sha256:
            raise SystemExit("Job manifest hash mismatch; re-plan and review commands/accelerator.")
        accelerator = job.get("accelerator", "CPU")
        if not isinstance(accelerator, str) or accelerator not in {"CPU", "T4"}:
            raise SystemExit("Unsupported accelerator in job manifest.")
        print(f"Approved job {args.job_id}; archive SHA-256 {actual_hash}")
        print(f"Job manifest SHA-256 {actual_job_hash}; accelerator {accelerator}")
        print("Commands:")
        print(json.dumps(job["commands"], indent=2))

        balance_before, _ = read_colab_usage(cli, cli_home)
        require_zero_paid_balance(balance_before)
        session_attempted = True
        create_args = ["new", "-s", session]
        if accelerator == "T4":
            create_args.extend(["--gpu", "T4"])
        created_result = run_cli(cli, cli_home, *create_args, timeout=180)
        print(created_result.stdout[-4000:])
        if created_result.returncode != 0:
            raise RuntimeError("Colab session allocation failed.")

        balance_after_allocation, _ = read_colab_usage(cli, cli_home)
        require_zero_paid_balance(balance_after_allocation)
        if accelerator == "T4":
            require_t4_session(cli, cli_home, session)

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

        balance_after_job, _ = read_colab_usage(cli, cli_home)
        require_zero_paid_balance(balance_after_job)

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
            listed = run_cli(cli, cli_home, "sessions", timeout=60)
            if listed.returncode != 0:
                print(f"WARNING: could not verify Colab session cleanup: {session}", file=sys.stderr)
            elif session in listed.stdout:
                print(f"WARNING: Colab still lists session {session}; stop it manually.", file=sys.stderr)
            elif stopped.returncode == 0:
                print(f"Colab session stopped and verified: {session}")
            try:
                final_balance, _ = read_colab_usage(cli, cli_home)
                if final_balance != 0:
                    print(f"WARNING: paid compute balance is no longer zero ({final_balance:.2f} CU).", file=sys.stderr)
            except RuntimeError as error:
                print(f"WARNING: could not verify final Colab balance: {error}", file=sys.stderr)
        archive.unlink(missing_ok=True)
        job_file.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
