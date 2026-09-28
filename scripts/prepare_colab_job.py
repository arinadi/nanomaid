#!/usr/bin/env python3
"""Stage an inspectable, secret-filtered source archive for one Colab check."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
import uuid
from pathlib import Path

SKIP_DIRS = {
    ".git", ".nanomaid", ".venv", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".next", "node_modules", "__pycache__", "coverage",
    ".ipynb_checkpoints", "dist", "build", "target", "vendor",
}
SKIP_NAMES = {".npmrc", ".pypirc", "credentials.json", "service-account.json"}
SKIP_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".jks", ".mp3", ".wav", ".m4a",
    ".aac", ".ogg", ".opus", ".flac", ".mp4", ".mov", ".webm", ".mkv",
    ".avi", ".mpeg", ".mpg", ".m4v", ".3gp", ".jpg", ".jpeg", ".png",
    ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".sqlite", ".db",
    ".zip", ".tar", ".gz", ".7z", ".rar",
}
SENSITIVE_PART = re.compile(r"(secret|credential|token|private.?key)", re.IGNORECASE)
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
ACCELERATORS = {"CPU", "T4"}


def excluded(relative: Path, is_dir: bool) -> bool:
    parts = relative.parts
    name = relative.name
    if any(part in SKIP_DIRS for part in parts):
        return True
    if name == ".env" or name.startswith(".env."):
        return True
    if name in SKIP_NAMES or SENSITIVE_PART.search(name):
        return True
    if relative.suffix.lower() in SKIP_SUFFIXES:
        return True
    return False


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_job_spec(path: Path) -> tuple[list[list[str]], str]:
    """Load reviewed argv arrays and their requested accelerator."""
    command_spec = json.loads(path.read_text(encoding="utf-8"))
    commands = command_spec["commands"]
    accelerator = command_spec.get("accelerator", "CPU")
    if not isinstance(commands, list) or not commands:
        raise ValueError("commands must be a non-empty array of argument arrays")
    for command in commands:
        if not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg for arg in command):
            raise ValueError("each command must be a non-empty array of non-empty strings (no shell string)")
    if not isinstance(accelerator, str) or accelerator not in ACCELERATORS:
        raise ValueError(f"accelerator must be one of {sorted(ACCELERATORS)}")
    return commands, accelerator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("commands_json", type=Path, help='JSON object with "commands" argv arrays and optional "accelerator": "T4"')
    args = parser.parse_args()

    project = args.project.resolve(strict=True)
    if not project.is_dir():
        parser.error("project must be a directory")
    try:
        commands, accelerator = load_job_spec(args.commands_json)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(f"invalid commands JSON: {error}")

    job_id = uuid.uuid4().hex[:12]
    job_dir = Path.home() / ".local/share/nanomaid/jobs" / job_id
    job_dir.mkdir(parents=True, mode=0o700)
    os.chmod(job_dir.parent, 0o700)
    archive = job_dir / "source.tar.gz"
    manifest: list[tuple[str, int]] = []
    total_bytes = 0

    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(project.rglob("*")):
            relative = path.relative_to(project)
            if excluded(relative, path.is_dir()) or path.is_symlink():
                continue
            if not path.is_file():
                continue
            size = path.stat().st_size
            total_bytes += size
            if total_bytes > MAX_ARCHIVE_BYTES:
                archive.unlink(missing_ok=True)
                parser.error("selected source exceeds the 100 MiB archive limit")
            tar.add(path, arcname=(Path(project.name) / relative).as_posix(), recursive=False)
            manifest.append(((Path(project.name) / relative).as_posix(), size))

    if not manifest:
        archive.unlink(missing_ok=True)
        parser.error("no eligible regular files found in project")

    job = {
        "job_id": job_id,
        "project_name": project.name,
        "accelerator": accelerator,
        "archive_sha256": sha256(archive),
        "commands": commands,
        "timeout_seconds": 1800,
    }
    job_file = job_dir / "job.json"
    job_file.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    os.chmod(archive, 0o600)
    os.chmod(job_file, 0o600)

    print(f"Job: {job_id}")
    print(f"Accelerator: {accelerator}")
    print(f"Archive: {archive}")
    print(f"SHA-256: {job['archive_sha256']}")
    print(f"Archive size: {archive.stat().st_size} bytes; source files: {len(manifest)}")
    print(f"Job manifest SHA-256: {sha256(job_file)}")
    print("Commands (argument arrays; not shell strings):")
    print(json.dumps(commands, indent=2))
    print("Files staged for review (secrets, media, dependencies, and build outputs excluded):")
    for name, size in manifest:
        print(f"  {size:>9}  {name}")
    print("Review this complete manifest and hash before approving any Colab upload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
