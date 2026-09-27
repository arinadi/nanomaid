#!/usr/bin/env python3
"""Verify a pinned uv wheel and extract only its standalone uv/uvx binaries."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def extract_binary(wheel: Path, member: str, destination: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        try:
            info = archive.getinfo(member)
        except KeyError as error:
            raise RuntimeError(f"Pinned wheel is missing expected executable {member}") from error
        mode = info.external_attr >> 16
        if not mode & 0o111:
            raise RuntimeError(f"Wheel member is not marked executable: {member}")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as output, archive.open(info) as source:
                while block := source.read(1024 * 1024):
                    output.write(block)
            os.chmod(temporary, 0o755)
            os.replace(temporary, destination)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("version")
    parser.add_argument("sha256")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if digest(args.wheel) != args.sha256:
        print("uv wheel checksum mismatch", file=sys.stderr)
        return 1
    prefix = f"uv-{args.version}.data/scripts/"
    extract_binary(args.wheel, prefix + "uv", args.destination / "uv")
    extract_binary(args.wheel, prefix + "uvx", args.destination / "uvx")
    print(f"Verified and installed uv {args.version} user-locally at {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
