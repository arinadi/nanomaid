#!/usr/bin/env python3
"""Idempotently merge the NanoMaid block into global OpenCode AGENTS.md."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BEGIN = "<!-- BEGIN NANOMAID MANAGED BLOCK -->"
END = "<!-- END NANOMAID MANAGED BLOCK -->"


def managed_block(template: Path) -> str:
    text = template.read_bytes().decode("utf-8")
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError("NanoMaid AGENTS template must contain exactly one pair of managed markers.")
    start = text.index(BEGIN)
    end = text.index(END)
    if end <= start:
        raise ValueError("NanoMaid AGENTS markers are out of order.")
    return text[start:end + len(END)].rstrip("\r\n")


def merge_content(existing: str, block: str) -> str:
    begin_count = existing.count(BEGIN)
    end_count = existing.count(END)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("Global AGENTS.md has malformed or duplicate NanoMaid markers; refusing to edit.")

    if begin_count == 0:
        if not existing:
            return f"{block}\n"
        separator = "" if existing.endswith(("\n", "\r")) else "\n"
        return f"{existing}{separator}\n{block}\n"

    start = existing.index(BEGIN)
    end = existing.index(END)
    if end < start:
        raise ValueError("Global AGENTS.md NanoMaid markers are out of order; refusing to edit.")
    end += len(END)

    newline = "\r\n" if "\r\n" in existing else "\n"
    replacement = block.replace("\n", newline)
    return f"{existing[:start]}{replacement}{existing[end:]}"


def backup_file(path: Path, data: bytes) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.nanomaid-{timestamp}.bak")
    suffix = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.nanomaid-{timestamp}-{suffix}.bak")
        suffix += 1
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(backup, 0o600)
    return backup


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix="AGENTS.md.nanomaid.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "check"))
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    args = parser.parse_args()

    try:
        block = managed_block(args.template)
        target = args.target
        if target.is_symlink():
            raise RuntimeError(f"Refusing to modify symlinked global AGENTS.md: {target}")

        if args.action == "check":
            if not target.is_file():
                raise RuntimeError(f"Global AGENTS.md is missing: {target}")
            existing = target.read_bytes().decode("utf-8")
            merged = merge_content(existing, block)
            if merged != existing:
                raise RuntimeError("NanoMaid global AGENTS block is missing or differs from the source template.")
            print("NanoMaid global AGENTS block verified.")
            return 0

        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        old_data = target.read_bytes() if target.exists() else b""
        existing = old_data.decode("utf-8")
        merged = merge_content(existing, block)
        rendered = merged.encode("utf-8")
        if rendered == old_data:
            print("NanoMaid global AGENTS block already up to date.")
            return 0

        if target.exists():
            backup = backup_file(target, old_data)
            print(f"Global AGENTS backup saved: {backup}")
            mode = target.stat().st_mode & 0o777
        else:
            mode = 0o600
        atomic_write(target, rendered, mode)
        print("NanoMaid managed block merged into global AGENTS.md.")
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"NanoMaid AGENTS merge stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
