#!/usr/bin/env python3
"""Summarise the entry-level differences between two whdload_db.json files."""

import argparse
import json

from xml_to_json import changed_fields


def diff(old_games: list[dict], new_games: list[dict]) -> list[str]:
    old = {g["sha1"]: g for g in old_games}
    new = {g["sha1"]: g for g in new_games}
    added = [new[s] for s in new if s not in old]
    removed = [old[s] for s in old if s not in new]
    changed = [(new[s]["filename"], changed_fields(old[s], new[s])) for s in new if s in old]
    changed = [(name, fields) for name, fields in changed if fields]

    out = [f"- Added: {len(added)}", f"- Removed: {len(removed)}", f"- Changed: {len(changed)}"]
    if added:
        out += ["", "### Added", ""] + [f"- `{g['filename']}` ({g['sha1']})" for g in added]
    if removed:
        out += ["", "### Removed", ""] + [f"- `{g['filename']}` ({g['sha1']})" for g in removed]
    if changed:
        out += ["", "### Changed", ""] + [f"- `{name}`: {'; '.join(fields)}" for name, fields in changed]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old")
    parser.add_argument("new")
    args = parser.parse_args()
    with open(args.old, encoding="utf-8") as f:
        old = json.load(f)["games"]
    with open(args.new, encoding="utf-8") as f:
        new = json.load(f)["games"]
    print("\n".join(diff(old, new)))


if __name__ == "__main__":
    main()
