"""Executed inside a temporary Colab kernel; runs only argv arrays from job.json."""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
from pathlib import Path

ROOT = Path("/content")
ARCHIVE = ROOT / "nanomaid-source.tar.gz"
JOB_FILE = ROOT / "nanomaid-job.json"
RESULT = ROOT / "nanomaid-result.txt"


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                raise ValueError(f"Unsafe archive entry rejected: {member.name}")
        tar.extractall(destination, members=members, filter="data")


def main() -> int:
    job = json.loads(JOB_FILE.read_text(encoding="utf-8"))
    workspace = ROOT / "nanomaid-workspace"
    safe_extract(ARCHIVE, workspace)
    project = workspace / job["project_name"]
    if not project.is_dir():
        raise RuntimeError("Project directory missing after extraction")

    lines: list[str] = []
    overall = 0
    for index, argv in enumerate(job["commands"], start=1):
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
            raise ValueError("Invalid command argv in job manifest")
        lines.append(f"[{index}/{len(job['commands'])}] $ {json.dumps(argv)}")
        try:
            completed = subprocess.run(
                argv,
                cwd=project,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=int(job.get("timeout_seconds", 1800)),
                check=False,
                shell=False,
            )
            output = completed.stdout or ""
            lines.append(output[-200_000:])
            lines.append(f"exit_code={completed.returncode}")
            if completed.returncode != 0:
                overall = completed.returncode
                break
        except subprocess.TimeoutExpired as error:
            output = error.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            lines.extend([str(output)[-200_000:], "ERROR: command timed out"])
            overall = 124
            break
        except OSError as error:
            lines.append(f"ERROR: could not start command: {error}")
            overall = 127
            break

    RESULT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(RESULT.read_text(encoding="utf-8")[-200_000:])
    raise SystemExit(overall)


main()
