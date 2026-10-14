#!/usr/bin/env python3
"""Check builder/settings, builder/customcontrols and a built database.

Errors (exit status 1):
  - unknown files in settings/ (a typo would be ignored silently)
  - duplicate lines, malformed lines, out-of-range offsets
  - a game listed in more than one file of an exclusive group
    (two screen heights, two CPU clocks, mouse and CD32 on one port, ...)
  - a WHD_DefaultSlave.txt slave that the archive does not contain
  - customcontrols lines that are not amiberry_custom mappings
  - more than one database entry with the same SHA1
  - JSON Schema violations (with --schema)

Warnings (reported, not fatal):
  - settings keys or customcontrols files that match no game in the database
  - archive filenames that appear more than once with different SHA1s
"""

import argparse
import collections
import json
import os
import re
import sys

from overrides import (BUILDER_ONLY_FILES, DEFAULT_BUILDER_DIR, EXCLUSIVE_GROUPS, FLAG_FILES, OFFSET_H_RANGE,
                       OFFSET_V_RANGE, VALUE_FILES, Settings, resolve_slave)

CONTROL_LINE = re.compile(r"^joyport[0-3]_amiberry_custom_(axis_)?(none|hotkey)_[a-z0-9_]+=.+$")
OFFSET_BOUNDS = {"Screen_Offset_H.txt": OFFSET_H_RANGE, "Screen_Offset_V.txt": OFFSET_V_RANGE}


def check(builder_dir: str, games: list[dict]) -> tuple[list[str], list[str]]:
    settings = Settings(builder_dir)
    errors: list[str] = []
    warnings: list[str] = []

    subpaths = {g.get("subpath", "") for g in games}
    by_filename: dict[str, list[dict]] = collections.defaultdict(list)
    for game in games:
        by_filename[game["filename"]].append(game)

    known = set(FLAG_FILES) | set(VALUE_FILES) | set(BUILDER_ONLY_FILES)
    present = sorted(os.listdir(settings.settings_dir)) if os.path.isdir(settings.settings_dir) else []
    for name in present:
        if name not in known:
            errors.append(f"settings/{name}: unknown settings file (see CONTRIBUTING.md for the supported names)")

    for name in FLAG_FILES:
        lines = settings.lines(name)
        for line, count in collections.Counter(lines).items():
            if count > 1:
                errors.append(f"settings/{name}: `{line}` is listed {count} times")
        for line in lines:
            if len(line.split()) != 1:
                errors.append(f"settings/{name}: `{line}` must be a single game folder name")
        unknown = sorted({line for line in lines if line not in subpaths})
        if unknown:
            warnings.append(f"settings/{name}: no game with subpath {', '.join(f'`{u}`' for u in unknown)}")

    for group, files in EXCLUSIVE_GROUPS.items():
        owners: dict[str, list[str]] = collections.defaultdict(list)
        for name in files:
            for line in set(settings.lines(name)):
                owners[line].append(name)
        for game, names in sorted(owners.items()):
            if len(names) > 1:
                errors.append(f"`{game}` has conflicting {group} settings: {', '.join(names)}")

    for name, key_kind in VALUE_FILES.items():
        seen: set[str] = set()
        for line in settings.lines(name):
            parts = line.split()
            if len(parts) != 2:
                errors.append(f"settings/{name}: `{line}` must be `<{key_kind}> <value>`")
                continue
            key, value = parts
            if key in seen:
                errors.append(f"settings/{name}: `{key}` is listed more than once")
            seen.add(key)

            if name in OFFSET_BOUNDS:
                low, high = OFFSET_BOUNDS[name]
                if not re.fullmatch(r"-?\d+", value) or not low <= int(value) <= high:
                    errors.append(f"settings/{name}: `{line}` offset must be an integer from {low} to {high}")
                if key not in subpaths:
                    warnings.append(f"settings/{name}: no game with subpath `{key}`")
                continue

            archive, _, slave = key.partition("/")
            matches = by_filename.get(archive, [])
            if not matches:
                warnings.append(f"settings/{name}: no archive named `{archive}`")
            elif name == "WHD_DefaultSlave.txt":
                for game in matches:
                    if not resolve_slave(value, game.get("slaves", [])):
                        errors.append(f"settings/{name}: `{archive}` ({game['sha1']}) has no slave `{value}`")
            elif slave and not any(s.get("filename") == slave for g in matches for s in g.get("slaves", [])):
                errors.append(f"settings/{name}: `{archive}` has no slave `{slave}`")

    for line in settings.lines("WHD_Longname_Fixes.txt"):
        if "|" not in line:
            errors.append(f"settings/WHD_Longname_Fixes.txt: `{line}` must be `generated name|fixed name`")

    cc_dir = settings.customcontrols_dir
    for name in sorted(os.listdir(cc_dir)) if os.path.isdir(cc_dir) else []:
        with open(os.path.join(cc_dir, name), encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        for line in lines:
            if not CONTROL_LINE.match(line):
                errors.append(f"customcontrols/{name}: `{line}` is not a joyportN_amiberry_custom_... mapping")
        for line, count in collections.Counter(lines).items():
            if count > 1:
                errors.append(f"customcontrols/{name}: `{line}` is listed {count} times")
        if name not in subpaths:
            warnings.append(f"customcontrols/{name}: no game with subpath `{name}`")

    for sha1, count in collections.Counter(g["sha1"] for g in games).items():
        if count > 1:
            errors.append(f"database: {count} entries share SHA1 {sha1}")
    for filename, entries in sorted(by_filename.items()):
        if len(entries) > 1:
            warnings.append(f"database: `{filename}` appears {len(entries)} times with different SHA1s")

    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("db", help="built whdload_db.json to check against")
    parser.add_argument("--builder-dir", default=DEFAULT_BUILDER_DIR)
    parser.add_argument("--schema", help="also validate the database against this JSON Schema (needs jsonschema)")
    parser.add_argument("--report", help="also write the Markdown report to this file")
    args = parser.parse_args()

    with open(args.db, encoding="utf-8") as f:
        database = json.load(f)
    errors, warnings = check(args.builder_dir, database["games"])

    if args.schema:
        import jsonschema
        with open(args.schema, encoding="utf-8") as f:
            validator = jsonschema.Draft202012Validator(json.load(f))
        for error in validator.iter_errors(database):
            path = "/".join(str(p) for p in error.absolute_path)
            errors.append(f"schema: {path or '(root)'}: {error.message}")

    out = [f"- Errors: {len(errors)}", f"- Warnings: {len(warnings)}"]
    if errors:
        out += ["", "### Errors", ""] + [f"- {e}" for e in errors]
    if warnings:
        out += ["", "<details><summary>Warnings</summary>", ""] + [f"- {w}" for w in warnings] + ["", "</details>"]
    text = "\n".join(out) + "\n"
    print(text, end="")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(text)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
