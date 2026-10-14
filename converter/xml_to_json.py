#!/usr/bin/env python3
"""
Convert Horace's whdload_db.xml to structured JSON for Amiberry.

Source: https://github.com/HoraceAndTheSpider/Amiberry-XML-Builder
Output: whdload_db.json with proper typed fields and SHA1-keyed entries.

On top of the upstream XML this applies, in order:
  1. builder/snippets/*   games added or replaced by this repo (matched by SHA1)
  2. builder/settings/*, builder/customcontrols/*   per-game overrides
  3. de-duplication by SHA1 (the last entry wins)
"""

import argparse
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from overrides import DEFAULT_BUILDER_DIR, Settings, apply_overrides


def parse_hardware(text: str) -> dict:
    """Parse newline-separated KEY=VALUE hardware string into structured dict."""
    if not text:
        return {}

    hw = {}
    # Known boolean fields
    bool_fields = {"screen_autoheight", "ntsc", "jit", "cpu_compatible",
                   "cpu_24bitaddressing", "cpu_exact", "slave_libraries"}
    # Known integer fields
    int_fields = {"screen_height", "screen_width", "screen_offseth",
                  "screen_offsetv", "fast_ram", "z3_ram", "chip_ram"}

    for line in text.strip().splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip()

        if key in bool_fields:
            hw[key] = value.lower() == "true"
        elif key in int_fields:
            try:
                hw[key] = int(value)
            except ValueError:
                hw[key] = value.lower()
        else:
            hw[key] = value.lower()

    return hw


def parse_custom_fields(text: str) -> list:
    """Parse custom field definitions from slave <custom> text.

    Formats:
      C1:B:caption           -> bool_type
      C1:X:label:bit         -> bit_type
      C1:L:caption:opt1,opt2 -> list_type
    """
    if not text:
        return []

    fields = []
    for line in text.strip().splitlines():
        line = line.strip().replace("\t", "")
        if not line:
            continue

        # Only process lines starting with C1-C5
        if not (len(line) >= 2 and line[0] == "C" and line[1] in "12345"):
            continue

        parts = line.split(":")
        if len(parts) < 2:
            continue

        slot = int(parts[0][1])  # 1-5

        if parts[1] == "B" and len(parts) >= 3:
            fields.append({
                "slot": slot,
                "type": "bool",
                "caption": parts[2]
            })
        elif parts[1] == "X" and len(parts) >= 4:
            try:
                bit = int(parts[3])
            except ValueError:
                continue
            fields.append({
                "slot": slot,
                "type": "bit",
                "label": parts[2],
                "bit": bit
            })
        elif parts[1] == "L" and len(parts) >= 4:
            fields.append({
                "slot": slot,
                "type": "list",
                "caption": parts[2],
                "options": parts[3].split(",")
            })

    return fields


def parse_custom_controls(text: str) -> list[str]:
    """Parse custom_controls text into list of amiberry_custom config lines."""
    if not text:
        return []
    lines = []
    for line in text.strip().splitlines():
        line = line.strip()
        if line and "amiberry_custom" in line:
            lines.append(line)
    return lines


def convert_game(game_elem: ET.Element) -> dict:
    """Convert a single <game> XML element to a dict."""
    entry = {}

    # Attributes
    entry["filename"] = game_elem.get("filename", "")
    entry["sha1"] = game_elem.get("sha1", "")

    # Simple text elements
    for tag in ("name", "subpath", "variant_uuid"):
        elem = game_elem.find(tag)
        entry[tag] = elem.text.strip() if elem is not None and elem.text else ""

    # Slave count
    elem = game_elem.find("slave_count")
    entry["slave_count"] = int(elem.text) if elem is not None and elem.text else 0

    # Slave default
    elem = game_elem.find("slave_default")
    entry["slave_default"] = elem.text.strip() if elem is not None and elem.text else ""

    # Slave libraries
    elem = game_elem.find("slave_libraries")
    entry["slave_libraries"] = (
        elem.text.strip().lower() == "true"
        if elem is not None and elem.text
        else False
    )

    # Slaves
    slaves = []
    for slave_elem in game_elem.findall("slave"):
        slave = {}
        fn = slave_elem.find("filename")
        slave["filename"] = fn.text.strip() if fn is not None and fn.text else ""

        dp = slave_elem.find("datapath")
        slave["datapath"] = dp.text.strip() if dp is not None and dp.text else ""

        custom_elem = slave_elem.find("custom")
        custom_text = custom_elem.text if custom_elem is not None else ""
        custom_fields = parse_custom_fields(custom_text)
        if custom_fields:
            slave["custom_fields"] = custom_fields

        slaves.append(slave)
    entry["slaves"] = slaves

    # Hardware
    hw_elem = game_elem.find("hardware")
    hw_text = hw_elem.text if hw_elem is not None else ""
    hardware = parse_hardware(hw_text)
    if hardware:
        entry["hardware"] = hardware

    # Custom controls
    cc_elem = game_elem.find("custom_controls")
    cc_text = cc_elem.text if cc_elem is not None else ""
    custom_controls = parse_custom_controls(cc_text)
    if custom_controls:
        entry["custom_controls"] = custom_controls

    return entry


def load_snippets(builder_dir: str) -> list[dict]:
    """Games from builder/snippets/*: bare <game> elements in upstream XML format."""
    snippet_dir = os.path.join(builder_dir, "snippets")
    if not os.path.isdir(snippet_dir):
        return []
    entries = []
    for name in sorted(os.listdir(snippet_dir)):
        path = os.path.join(snippet_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            root = ET.fromstring(f"<root>{f.read()}</root>")
        entries.extend(convert_game(game_elem) for game_elem in root.findall("game"))
    return entries


def dedupe_by_sha1(games: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep the last entry for each SHA1 (upstream appends newer scans)."""
    seen: set[str] = set()
    kept: list[dict] = []
    dropped: list[dict] = []
    for game in reversed(games):
        if game["sha1"] in seen:
            dropped.append(game)
        else:
            seen.add(game["sha1"])
            kept.append(game)
    kept.reverse()
    dropped.reverse()
    return kept, dropped


def changed_fields(before: dict, after: dict) -> list[str]:
    changes = []
    for key in sorted(set(before) | set(after)):
        if key == "hardware":
            hw_before, hw_after = before.get(key, {}), after.get(key, {})
            for hw_key in sorted(set(hw_before) | set(hw_after)):
                if hw_before.get(hw_key) != hw_after.get(hw_key):
                    changes.append(f"hardware.{hw_key}: {hw_before.get(hw_key)!r} -> {hw_after.get(hw_key)!r}")
        elif key == "slaves":
            old_slaves, new_slaves = before.get(key, []), after.get(key, [])
            old_names = [s.get("filename") for s in old_slaves]
            new_names = [s.get("filename") for s in new_slaves]
            if old_names != new_names:
                changes.append(f"slaves: {old_names!r} -> {new_names!r}")
                continue
            for old, new in zip(old_slaves, new_slaves):
                for slave_key in sorted(set(old) | set(new)):
                    if old.get(slave_key) == new.get(slave_key):
                        continue
                    if slave_key == "custom_fields":
                        changes.append(f"{new['filename']} custom_fields changed")
                    else:
                        changes.append(f"{new['filename']} {slave_key}: "
                                       f"{old.get(slave_key)!r} -> {new.get(slave_key)!r}")
        elif before.get(key) != after.get(key):
            if key == "custom_controls":
                changes.append("custom_controls changed")
            else:
                changes.append(f"{key}: {before.get(key)!r} -> {after.get(key)!r}")
    return changes


def build(xml_path: str, builder_dir: str) -> tuple[dict, list[str]]:
    """Build the database dict and a Markdown report of what this repo changed."""
    root = ET.parse(xml_path).getroot()
    upstream = [convert_game(game_elem) for game_elem in root.findall("game")]

    snippets = load_snippets(builder_dir)
    snippet_sha1s = {s["sha1"] for s in snippets}
    replaced = [g["filename"] for g in upstream if g["sha1"] in snippet_sha1s]
    games = [g for g in upstream if g["sha1"] not in snippet_sha1s] + snippets

    settings = Settings(builder_dir)
    changed: list[tuple[str, list[str]]] = []
    for game in games:
        before = json.loads(json.dumps(game))
        apply_overrides(game, settings)
        fields = changed_fields(before, game)
        if fields:
            changed.append((game["filename"], fields))

    games, dropped = dedupe_by_sha1(games)

    database = {
        "schema_version": 2,
        "source": "https://github.com/HoraceAndTheSpider/Amiberry-XML-Builder",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream_timestamp": root.get("timestamp", ""),
        "game_count": len(games),
        "games": games,
    }

    report = [
        f"- Upstream games: {len(upstream)}",
        f"- Snippets: {len(snippets)} ({len(replaced)} replace an upstream entry)",
        f"- Games changed by overrides: {len(changed)}",
        f"- Duplicate SHA1 entries removed: {len(dropped)}",
        f"- Games written: {len(games)}",
    ]
    if changed:
        report += ["", "### Changed by overrides", ""]
        report += [f"- `{name}`: {'; '.join(fields)}" for name, fields in changed]
    if dropped:
        report += ["", "### Removed duplicates (an entry with the same SHA1 appears later)", ""]
        report += [f"- `{g['filename']}` ({g['sha1']})" for g in dropped]
    return database, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("xml", help="upstream whdload_db.xml")
    parser.add_argument("json", help="output whdload_db.json")
    parser.add_argument("--builder-dir", default=DEFAULT_BUILDER_DIR,
                        help="directory containing settings/, customcontrols/ and snippets/")
    parser.add_argument("--report", help="also write the Markdown report to this file")
    parser.add_argument("--pretty", action="store_true", help="indent the JSON output")
    args = parser.parse_args()

    database, report = build(args.xml, args.builder_dir)
    with open(args.json, "w", encoding="utf-8") as f:
        if args.pretty:
            json.dump(database, f, ensure_ascii=False, indent=2)
        else:
            json.dump(database, f, ensure_ascii=False, separators=(",", ":"))

    text = "\n".join(report) + "\n"
    print(text, end="")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    main()
