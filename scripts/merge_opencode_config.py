#!/usr/bin/env python3
"""Safely set global OpenCode shell/edit actions to ask."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def config_paths() -> tuple[Path, Path]:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    directory = config_home / "opencode"
    return directory / "opencode.json", directory / "opencode.jsonc"


def merged_config(path: Path, jsonc_path: Path) -> tuple[dict, bool]:
    if jsonc_path.exists() and not path.exists():
        raise RuntimeError(
            f"Found {jsonc_path}; refusing to create a second global config. "
            "Merge the NanoMaid shell/edit ask rules manually."
        )
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"Cannot safely merge {path} as strict JSON. Preserve it and merge the "
                "NanoMaid shell/edit ask rules manually."
            ) from error
        existed = True
    else:
        data = {"$schema": "https://opencode.ai/config.json"}
        existed = False

    if not isinstance(data, dict):
        raise RuntimeError(f"Expected a JSON object in {path}.")
    permissions = data.get("permissions", [])
    if not isinstance(permissions, list) or any(not isinstance(rule, dict) for rule in permissions):
        raise RuntimeError(f"Expected `permissions` to be an array of rule objects in {path}.")

    # Preserve unrelated rules and explicit denies. Existing shell/edit allows are
    # intentionally replaced by the approved global ask policy.
    other_rules = [rule for rule in permissions if rule.get("action") not in {"shell", "edit"}]
    denied_rules = [
        rule
        for rule in permissions
        if rule.get("action") in {"shell", "edit"} and rule.get("effect") == "deny"
    ]
    data["permissions"] = [
        *other_rules,
        {"action": "shell", "resource": "*", "effect": "ask"},
        {"action": "edit", "resource": "*", "effect": "ask"},
        *denied_rules,
    ]
    return data, existed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="check without changing files")
    parser.add_argument("--verify", action="store_true", help="require shell/edit ask rules to exist")
    args = parser.parse_args()
    path, jsonc_path = config_paths()
    try:
        if args.verify:
            if not path.is_file():
                raise RuntimeError(f"Global OpenCode config is missing: {path}")
            data = json.loads(path.read_text(encoding="utf-8"))
            permissions = data.get("permissions") if isinstance(data, dict) else None
            if not isinstance(permissions, list):
                raise RuntimeError("Global OpenCode permissions are missing or malformed.")
            for action in ("shell", "edit"):
                if not any(
                    isinstance(rule, dict)
                    and rule.get("action") == action
                    and rule.get("resource") == "*"
                    and rule.get("effect") == "ask"
                    for rule in permissions
                ):
                    raise RuntimeError(f"Global OpenCode {action} ask rule is missing.")
            print("Global OpenCode shell/edit ask rules verified.")
            return 0

        data, existed = merged_config(path, jsonc_path)
        if args.check:
            print(f"Global OpenCode permission config: {'present' if existed else 'would be created'}")
            return 0

        rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if existed:
            if path.read_text(encoding="utf-8") == rendered:
                print("Global OpenCode shell/edit ask rules already configured.")
                return
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = path.with_name(f"opencode.json.nanomaid-{timestamp}.bak")
            shutil.copy2(path, backup)
            os.chmod(backup, 0o600)
            print(f"OpenCode config backup created at {backup}")

        descriptor, temp_name = tempfile.mkstemp(prefix="opencode.json.", suffix=".tmp", dir=path.parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(rendered)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        os.chmod(path, 0o600)
        print("Global OpenCode shell/edit permissions set to ask.")
        return 0
    except (OSError, RuntimeError) as error:
        print(f"NanoMaid config merge stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
