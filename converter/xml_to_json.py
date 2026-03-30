#!/usr/bin/env python3
"""
Convert Horace's whdload_db.xml to structured JSON for Amiberry.

Source: https://github.com/HoraceAndTheSpider/Amiberry-XML-Builder
Output: whdload_db.json with proper typed fields and SHA1-keyed entries.
"""

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


def load_datapath_overrides() -> dict[str, str]:
    """Load archive/slave datapath overrides shared with the local builder."""
    settings_path = Path(__file__).resolve().parents[1] / "builder" / "settings" / "WHD_DataPath.txt"
    if not settings_path.is_file():
        return {}

    overrides: dict[str, str] = {}
    with settings_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                overrides[parts[0]] = parts[1]
    return overrides


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


def convert_game(game_elem: ET.Element, datapath_overrides: dict[str, str] | None = None) -> dict:
    """Convert a single <game> XML element to a dict."""
    entry = {}
    datapath_overrides = datapath_overrides or {}

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

        override = (
            datapath_overrides.get(f"{entry['filename']}/{slave['filename']}")
            or datapath_overrides.get(entry["filename"])
        )
        if override:
            slave["datapath"] = override

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


def convert(xml_path: str, json_path: str) -> None:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    datapath_overrides = load_datapath_overrides()

    # Extract timestamp from root
    timestamp = root.get("timestamp", "")

    games = []
    for game_elem in root.findall("game"):
        games.append(convert_game(game_elem, datapath_overrides))

    output = {
        "schema_version": 2,
        "source": "https://github.com/HoraceAndTheSpider/Amiberry-XML-Builder",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream_timestamp": timestamp,
        "game_count": len(games),
        "games": games,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    # Also write a pretty-printed version for diffing
    pretty_path = json_path.replace(".json", ".pretty.json")
    with open(pretty_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Converted {len(games)} games")
    print(f"  Compact: {json_path}")
    print(f"  Pretty:  {pretty_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.xml> <output.json>")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
