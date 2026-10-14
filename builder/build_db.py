#!/usr/bin/env python3
"""
Amiberry WHDLoad Game Database Builder

Scans WHDLoad LHA archives, parses slave headers, applies settings overrides,
and outputs a structured JSON database for use by Amiberry.

Rewrite of HoraceAndTheSpider's amiberry_xml_builder.py.
"""

import argparse
import hashlib
import json
import os
import posixpath
import struct
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import lhafile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "converter"))
from names import make_full_name  # noqa: E402
from overrides import Settings, apply_overrides  # noqa: E402
from xml_to_json import load_snippets  # noqa: E402


# ============================================================================
# WHDLoad slave header parser
# ============================================================================

WHDLOAD_FLAGS = {
    1: "Disk",
    2: "NoError",
    4: "EmulTrap",
    8: "NoDivZero",
    16: "Req68020",
    32: "ReqAGA",
    64: "NoKbd",
    128: "EmulLineA",
    256: "EmulTrapV",
    512: "EmulChk",
    1024: "EmulPriv",
    2048: "EmulLineF",
    4096: "ClearMem",
    8192: "Examine",
    16384: "EmulDivZero",
    32768: "EmulIllegal",
}

HEADER_OFFSET = 0x020


def _read_string(data: bytes, offset: int) -> str:
    if offset == 0 or offset >= len(data):
        return ""
    end = data.find(b"\x00", offset)
    if end == -1:
        end = len(data)
    return data[offset:end].decode("iso-8859-1", errors="replace")


def parse_slave_header(data: bytes) -> dict | None:
    """Parse WHDLoad slave binary header. Returns dict or None on failure."""
    if len(data) < HEADER_OFFSET + 32:
        return None

    hdr = data[HEADER_OFFSET:]
    if len(hdr) < 26:
        return None

    slave_id = struct.unpack_from("8s", hdr, 4)[0].decode("iso-8859-1", errors="replace")
    if slave_id != "WHDLOADS":
        return None

    version = struct.unpack_from(">H", hdr, 12)[0]
    flags_value = struct.unpack_from(">H", hdr, 14)[0]
    base_mem_size = struct.unpack_from(">L", hdr, 16)[0]
    current_dir_offset = struct.unpack_from(">H", hdr, 26)[0]

    flags = [name for bit, name in WHDLOAD_FLAGS.items() if flags_value & bit]

    exp_mem = 0
    if version >= 8:
        exp_mem = struct.unpack_from(">L", hdr, 32)[0]

    name = ""
    if version >= 10 and len(hdr) > 42:
        name_offset = struct.unpack_from(">H", hdr, 36)[0]
        name = _read_string(hdr, name_offset)

    config = []
    if version >= 17 and len(hdr) > 52:
        config_offset = struct.unpack_from(">H", hdr, 50)[0]
        config_str = _read_string(hdr, config_offset)
        if config_str:
            config = [c for c in config_str.split(";") if c]

    current_dir = _read_string(hdr, current_dir_offset)

    return {
        "version": version,
        "flags_value": flags_value,
        "flags": flags,
        "base_mem_size": base_mem_size,
        "exp_mem": exp_mem,
        "current_dir": current_dir,
        "name": name,
        "config": config,
    }


# ============================================================================
# LHA scanning
# ============================================================================

def sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def generate_variant_uuid(file_sha1s: list[str]) -> str:
    """Generate OpenRetro-compatible variant UUID from file SHA1s."""
    joined = "/".join(sorted(file_sha1s))
    url = "http://sha1.fengestad.no/" + joined
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url))


def scan_archive(archive_path: str) -> dict | None:
    """Scan a single LHA archive. Returns game entry dict or None."""
    try:
        archive = lhafile.LhaFile(archive_path)
    except Exception:
        return None

    # Collect file SHA1s for UUID generation
    file_sha1s = []
    for info in archive.infolist():
        fname = info.filename.replace(os.path.sep, posixpath.sep)
        if posixpath.sep not in fname:
            continue
        if fname.lower().endswith(".info"):
            continue
        try:
            data = archive.read(info.filename)
            file_sha1s.append(sha1_bytes(data))
        except Exception:
            continue

    variant_uuid = generate_variant_uuid(file_sha1s) if file_sha1s else ""

    # Find and parse slave files
    slaves = []
    for info in archive.infolist():
        if info.filename.lower().endswith(".slave"):
            try:
                slave_data = archive.read(info.filename)
            except Exception:
                continue

            fname = info.filename.replace(os.path.sep, posixpath.sep)
            slave_dir = posixpath.dirname(fname)
            slave_basename = posixpath.basename(fname)

            header = parse_slave_header(slave_data)
            if header is None:
                slaves.append({
                    "filename": slave_basename,
                    "datapath": "",
                    "subpath": slave_dir,
                    "header": None,
                })
                continue

            # Parse config into custom fields
            custom_fields = []
            if header["config"]:
                for cfg_line in header["config"]:
                    cfg_line = cfg_line.strip().replace("<", "").replace(">", "")
                    if not cfg_line:
                        continue
                    parts = cfg_line.split(":")
                    if len(parts) < 2 or not (parts[0].startswith("C") and len(parts[0]) == 2 and parts[0][1] in "12345"):
                        continue
                    slot = int(parts[0][1])
                    if parts[1] == "B" and len(parts) >= 3:
                        custom_fields.append({"slot": slot, "type": "bool", "caption": parts[2]})
                    elif parts[1] == "X" and len(parts) >= 4:
                        try:
                            bit = int(parts[3])
                        except ValueError:
                            continue
                        custom_fields.append({"slot": slot, "type": "bit", "label": parts[2], "bit": bit})
                    elif parts[1] == "L" and len(parts) >= 4:
                        custom_fields.append({
                            "slot": slot, "type": "list",
                            "caption": parts[2],
                            "options": parts[3].split(","),
                        })

            slave_entry = {
                "filename": slave_basename,
                "datapath": header["current_dir"],
                "subpath": slave_dir,
                "header": header,
            }
            if custom_fields:
                slave_entry["custom_fields"] = custom_fields

            slaves.append(slave_entry)

    if not slaves:
        return None

    # Derive subpath from first slave's directory
    subpath = slaves[0]["subpath"]

    return {
        "variant_uuid": variant_uuid,
        "subpath": subpath,
        "slaves": slaves,
    }


# ============================================================================
# Header-derived hardware
# ============================================================================

def detected_hardware(slaves: list[dict]) -> dict:
    """Requirements read from slave headers.

    apply_overrides() adds the settings-driven keys later; these two survive
    unless a settings file sets them explicitly.
    """
    hw = {}
    if any(s.get("header") and "ReqAGA" in s["header"]["flags"] for s in slaves):
        hw["chipset"] = "aga"
    if any(s.get("header") and "Req68020" in s["header"]["flags"] for s in slaves):
        hw["cpu"] = "68020"
    return hw

# ============================================================================
# Main builder
# ============================================================================

def build_database(scan_dir: str, builder_dir: str, existing_db: str | None = None, full_refresh: bool = False) -> dict:
    settings = Settings(builder_dir)
    longname_fixes = settings.lines("WHD_Longname_Fixes.txt")

    # Load existing database for incremental mode
    existing_sha1s: set[str] = set()
    existing_entries: list[dict] = []
    if not full_refresh and existing_db and os.path.exists(existing_db):
        with open(existing_db) as f:
            old_data = json.load(f)
        existing_entries = old_data.get("games", [])
        existing_sha1s = {g["sha1"] for g in existing_entries if g.get("sha1")}
        print(f"Loaded {len(existing_entries)} existing entries for incremental update")

    # Scan all LHA files
    lha_files = sorted(Path(scan_dir).rglob("*.lha"))
    print(f"Found {len(lha_files)} LHA files to scan")

    new_entries = []
    skipped = 0
    errors = 0

    for i, lha_path in enumerate(lha_files, 1):
        lha_str = str(lha_path)
        basename = lha_path.name
        filename_no_ext = lha_path.stem

        # Skip macOS resource forks
        if basename.startswith("._"):
            continue

        # Incremental: skip if SHA1 already in database
        archive_sha1 = sha1_file(lha_str)
        if archive_sha1 in existing_sha1s:
            skipped += 1
            continue

        if i % 100 == 0 or i == len(lha_files):
            print(f"  [{i}/{len(lha_files)}] Processing {basename}")

        try:
            scan_result = scan_archive(lha_str)
        except Exception as e:
            print(f"  Error scanning {basename}: {e}", file=sys.stderr)
            errors += 1
            continue

        if scan_result is None:
            errors += 1
            continue

        subpath = scan_result["subpath"]

        # Default slave: the only one, else the first. WHD_DefaultSlave.txt
        # is applied by apply_overrides() below.
        default_slave = scan_result["slaves"][0]["filename"]

        slaves_out = []
        for s in scan_result["slaves"]:
            slave_entry = {
                "filename": s["filename"],
                "datapath": s.get("datapath", ""),
            }
            if "custom_fields" in s:
                slave_entry["custom_fields"] = s["custom_fields"]
            slaves_out.append(slave_entry)

        new_entries.append({
            "filename": filename_no_ext,
            "sha1": archive_sha1,
            "name": make_full_name(subpath, longname_fixes),
            "subpath": subpath,
            "variant_uuid": scan_result["variant_uuid"],
            "slave_count": len(scan_result["slaves"]),
            "slave_default": default_slave,
            "slave_libraries": False,
            "slaves": slaves_out,
            "hardware": detected_hardware(scan_result["slaves"]),
        })

    # Load snippets
    snippet_entries = load_snippets(builder_dir)
    snippet_sha1s = {s["sha1"] for s in snippet_entries if s.get("sha1")}

    # Merge: existing (minus updated) + new + snippets
    # Remove existing entries that were re-scanned or are in snippets
    new_sha1s = {e["sha1"] for e in new_entries}
    merged = [e for e in existing_entries
              if e.get("sha1") not in new_sha1s and e.get("sha1") not in snippet_sha1s]
    merged.extend(new_entries)
    merged.extend(snippet_entries)

    # Every entry, including unchanged incremental ones, gets current overrides.
    for entry in merged:
        apply_overrides(entry, settings)

    # Sort by filename for stable output
    merged.sort(key=lambda g: g.get("filename", "").lower())

    print(f"\nDone: {len(new_entries)} scanned, {skipped} unchanged, {len(snippet_entries)} snippets, {errors} errors")
    print(f"Total: {len(merged)} games")

    return {
        "schema_version": 2,
        "source": "https://github.com/BlitterStudio/amiberry-game-db",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "game_count": len(merged),
        "games": merged,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build Amiberry WHDLoad game database from LHA archives"
    )
    parser.add_argument(
        "--scandir", "-s", required=True,
        help="Directory containing WHDLoad LHA files (scanned recursively)"
    )
    parser.add_argument(
        "--output", "-o", default="whdload_db.json",
        help="Output JSON file (default: whdload_db.json)"
    )
    parser.add_argument(
        "--builder-dir", "-d", default=os.path.dirname(os.path.abspath(__file__)),
        help="Builder directory containing settings/ and customcontrols/"
    )
    parser.add_argument(
        "--existing", "-e",
        help="Existing database for incremental updates (skips unchanged files)"
    )
    parser.add_argument(
        "--full-refresh", "-n", action="store_true",
        help="Full rebuild, ignore existing database"
    )

    args = parser.parse_args()

    if not os.path.isdir(args.scandir):
        print(f"Error: scan directory not found: {args.scandir}", file=sys.stderr)
        sys.exit(1)

    db = build_database(args.scandir, args.builder_dir, args.existing, args.full_refresh)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {args.output} ({os.path.getsize(args.output) / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
