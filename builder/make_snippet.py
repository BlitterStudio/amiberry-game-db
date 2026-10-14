#!/usr/bin/env python3
"""Write builder/snippets entries for WHDLoad archives missing from the database.

    python3 builder/make_snippet.py Game_v1.0.lha [More.lha ...]

Each archive becomes a <game> element in builder/snippets/<archive name>, in
the upstream XML format. Archives that share a name (different SHA1s) get one
element each in the same file; each SHA1 appears in at most one snippet.
Slaves, data paths, custom fields, the default slave and the variant UUID come
from the archive itself; the name is generated from the subpath the same way
upstream does it. Hardware only records what the slave headers require (AGA,
68020); put everything else in builder/settings.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from build_db import detected_hardware, scan_archive, sha1_file

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "converter"))
from names import make_full_name  # noqa: E402
from overrides import DEFAULT_BUILDER_DIR, Settings  # noqa: E402

REPO_ROOT = os.path.dirname(DEFAULT_BUILDER_DIR)

GAME_BLOCK = re.compile(r"<game\b[^>]*?\bsha1=([\"'])([0-9a-fA-F]{40})\1[^>]*>.*?</game>[ \t]*\n?", re.S)


def snippet_blocks(snippet_dir: str) -> dict[str, tuple[str, str]]:
    """SHA1 -> (snippet file, <game> element text) for every existing snippet."""
    blocks: dict[str, tuple[str, str]] = {}
    if not os.path.isdir(snippet_dir):
        return blocks
    for name in sorted(os.listdir(snippet_dir)):
        path = os.path.join(snippet_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            for match in GAME_BLOCK.finditer(f.read()):
                blocks[match.group(2).lower()] = (path, match.group(0))
    return blocks


def remove_block(path: str, block: str) -> None:
    """Drop one <game> element from a snippet file; delete the file if nothing is left."""
    with open(path, encoding="utf-8") as f:
        rest = f.read().replace(block, "", 1)
    if GAME_BLOCK.search(rest):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(rest)
    else:
        os.remove(path)


def snippet_xml(filename: str, sha1: str, name: str, scan: dict) -> str:
    slaves = scan["slaves"]
    lines = [
        f"<game filename={quoteattr(filename)} sha1={quoteattr(sha1)}>",
        f"\t<name>{escape(name)}</name>",
        f"\t<subpath>{escape(scan['subpath'])}</subpath>",
        f"\t<variant_uuid>{escape(scan['variant_uuid'])}</variant_uuid>",
        f"\t<slave_count>{len(slaves)}</slave_count>",
        f"\t<slave_default>{escape(slaves[0]['filename'])}</slave_default>",
        "\t<slave_libraries>False</slave_libraries>",
    ]
    for number, slave in enumerate(slaves, 1):
        lines += [
            f"\t<slave number=\"{number}\">",
            f"\t\t<filename>{escape(slave['filename'])}</filename>",
            f"\t\t<datapath>{escape(slave.get('datapath', ''))}</datapath>",
        ]
        config = (slave.get("header") or {}).get("config") or []
        if config:
            lines.append("\t\t<custom>")
            lines += ["\t\t" + escape(c.replace("<", "").replace(">", "")) for c in config]
            lines.append("\t\t</custom>")
        lines.append("\t</slave>")
    lines.append("\t<hardware>")
    lines += [f"\t\t{key.upper()}={value.upper()}" for key, value in detected_hardware(slaves).items()]
    lines += ["\t</hardware>", "</game>"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("archives", nargs="+", help=".lha files")
    parser.add_argument("--name", help="display name (only with a single archive); default: generated from the subpath")
    parser.add_argument("--builder-dir", default=DEFAULT_BUILDER_DIR)
    parser.add_argument("--db", default=os.path.join(REPO_ROOT, "whdload_db.json"),
                        help="database to check for archives that are already present")
    parser.add_argument("--stdout", action="store_true", help="print the snippets instead of writing files")
    parser.add_argument("--force", action="store_true",
                        help="replace an existing snippet entry for the same archive (same SHA1)")
    args = parser.parse_args()
    if args.name and len(args.archives) > 1:
        parser.error("--name needs exactly one archive")

    known: dict[str, str] = {}
    if os.path.isfile(args.db):
        with open(args.db, encoding="utf-8") as f:
            known = {g["sha1"]: g["filename"] for g in json.load(f)["games"]}
    longname_fixes = Settings(args.builder_dir).lines("WHD_Longname_Fixes.txt")
    snippet_dir = os.path.join(args.builder_dir, "snippets")
    existing = snippet_blocks(snippet_dir)

    failed = False
    for archive in args.archives:
        path = Path(archive)
        sha1 = sha1_file(str(path))
        scan = scan_archive(str(path))
        if scan is None:
            print(f"{path.name}: no WHDLoad slave found, skipped", file=sys.stderr)
            failed = True
            continue
        if sha1 in known:
            print(f"{path.name}: already in the database as {known[sha1]}; the snippet will replace that entry",
                  file=sys.stderr)

        name = args.name or make_full_name(scan["subpath"], longname_fixes)
        xml = snippet_xml(path.stem, sha1, name, scan)
        if args.stdout:
            sys.stdout.write(xml)
            continue

        if sha1 in existing:
            old_file, old_block = existing[sha1]
            if not args.force:
                print(f"{path.name}: already in {old_file}; use --force to replace it", file=sys.stderr)
                failed = True
                continue
            remove_block(old_file, old_block)

        # One file per archive name; archives that share a name (different
        # SHA1s) get one <game> element each in the same file.
        target = os.path.join(snippet_dir, path.stem)
        os.makedirs(snippet_dir, exist_ok=True)
        with open(target, "a", encoding="utf-8", newline="\n") as f:
            f.write(xml)
        existing[sha1] = (target, xml)
        print(f"wrote {target}: {name} (subpath {scan['subpath']}, {len(scan['slaves'])} slave(s), sha1 {sha1})")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
