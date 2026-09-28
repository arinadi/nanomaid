"""Executed inside a temporary Colab kernel; runs only argv arrays from job.json."""

from __future__ import annotations

import hashlib
import json
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_t4() -> None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError("T4 required; nvidia-smi could not verify a GPU") from error
    names = [name.strip() for name in result.stdout.splitlines() if name.strip()]
    if not any("t4" in name.lower() for name in names):
        raise RuntimeError(f"T4 required; detected: {names or 'no GPU'}")
    print(f"T4 verified: {', '.join(names)}")


def main() -> int:
    job = json.loads(JOB_FILE.read_text(encoding="utf-8"))
    accelerator = job.get("accelerator", "CPU")
    if not isinstance(accelerator, str) or accelerator not in {"CPU", "T4"}:
        raise ValueError("Unsupported accelerator in job manifest")
    if sha256(ARCHIVE) != job.get("archive_sha256"):
        raise ValueError("Source archive hash mismatch")
    if accelerator == "T4":
        require_t4()

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
    return overall


if __name__ == "__main__":
    raise SystemExit(main())
