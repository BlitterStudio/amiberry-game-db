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
import math
import os
import posixpath
import struct
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import lhafile


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
# Settings overrides
# ============================================================================

class SettingsDB:
    """Reads Horace-format settings/*.txt and customcontrols/ files."""

    def __init__(self, builder_dir: str):
        self.settings_dir = os.path.join(builder_dir, "settings")
        self.customcontrols_dir = os.path.join(builder_dir, "customcontrols")
        self._cache: dict[str, list[str]] = {}

    def _load_list(self, filename: str) -> list[str]:
        if filename in self._cache:
            return self._cache[filename]
        path = os.path.join(self.settings_dir, filename)
        if not os.path.isfile(path):
            self._cache[filename] = []
            return []
        with open(path) as f:
            lines = [line.strip() for line in f if line.strip()]
        self._cache[filename] = lines
        return lines

    def check_list(self, filename: str, game_name: str) -> bool:
        """Check if game_name appears in a settings list file."""
        for line in self._load_list(filename):
            if line == game_name:
                return True
        return False

    def value_list(self, filename: str, game_name: str) -> str:
        """Get a value associated with game_name from a settings file (word1=name, word2=value)."""
        for line in self._load_list(filename):
            parts = line.split()
            if parts and parts[0] == game_name and len(parts) >= 2:
                return parts[1]
        return ""

    def get_slave_datapath(self, archive_name: str, slave_name: str) -> str:
        """Get a datapath override for an archive or a specific slave in that archive."""
        slave_key = f"{archive_name}/{slave_name}"
        return (
            self.value_list("WHD_DataPath.txt", slave_key)
            or self.value_list("WHD_DataPath.txt", archive_name)
        )

    def get_custom_controls(self, subpath: str) -> list[str]:
        """Load custom controls for a game."""
        path = os.path.join(self.customcontrols_dir, subpath)
        if not os.path.isfile(path):
            return []
        with open(path) as f:
            return [line.strip() for line in f
                    if "amiberry_custom" in line and line.strip()]


def round_up_power_of_2(value_mb: float) -> int:
    """Round up to next power of 2 (in MB), matching Horace's logic."""
    for i in range(8):
        low = 2 ** (i - 1) if i > 0 else 0
        high = 2 ** i
        if low < value_mb < high:
            return high
    return max(1, int(value_mb))


def build_hardware(
    slaves: list[dict],
    subpath: str,
    filename: str,
    settings: SettingsDB,
) -> dict:
    """Build structured hardware settings from slave headers + overrides."""
    hw = {}

    # Detect flags from slave headers
    requires_aga = any(
        s.get("header") and "ReqAGA" in s["header"]["flags"]
        for s in slaves
    )
    requires_68020 = any(
        s.get("header") and "Req68020" in s["header"]["flags"]
        for s in slaves
    )

    # Chipset (from filename, settings, or slave flags)
    is_cd32 = "_CD32" in filename
    is_aga = "_AGA" in filename or is_cd32 or settings.check_list("Chipset_AGA.txt", subpath) or requires_aga

    if is_aga:
        hw["chipset"] = "aga"

    # CPU (from slave flags)
    if requires_68020:
        hw["cpu"] = "68020"

    # Blitter
    if settings.check_list("Chipset_ImmediateBlitter.txt", subpath):
        hw["blitter"] = "immediate"

    # Fast copper
    if settings.check_list("Chipset_FastCopper.txt", subpath):
        hw["fast_copper"] = True

    # Clock speed
    if settings.check_list("CPU_ClockSpeed_Max.txt", subpath):
        hw["clock"] = "max"
    elif settings.check_list("CPU_ClockSpeed_25.txt", subpath):
        hw["clock"] = "25"
    elif settings.check_list("CPU_ClockSpeed_14.txt", subpath):
        hw["clock"] = "14"

    # CPU compatible
    if settings.check_list("CPU_NoCompatible.txt", subpath):
        hw["cpu_compatible"] = False

    # CPU cycle exact
    if settings.check_list("CPU_CycleExact.txt", subpath):
        hw["cpu_exact"] = True

    # JIT
    if settings.check_list("CPU_ForceJIT.txt", subpath):
        hw["jit"] = True

    # NTSC
    if settings.check_list("Chipset_ForceNTSC.txt", subpath) or "NTSC" in filename:
        hw["ntsc"] = True

    # Controls
    use_mouse1 = settings.check_list("Control_Port0_Mouse.txt", subpath)
    use_mouse2 = settings.check_list("Control_Port1_Mouse.txt", subpath)
    use_cd32 = settings.check_list("Control_CD32.txt", subpath) or is_cd32

    hw["primary_control"] = "mouse" if use_mouse1 else "joystick"

    if use_mouse1:
        hw["port0"] = "mouse"
    elif use_cd32:
        hw["port0"] = "cd32"
    else:
        hw["port0"] = "joy"

    if use_mouse2:
        hw["port1"] = "mouse"
    elif use_cd32:
        hw["port1"] = "cd32"
    else:
        hw["port1"] = "joy"

    # Screen height
    screen_height = ""
    for h in ["400", "432", "480", "512", "524", "540", "568"]:
        if settings.check_list(f"Screen_Height_{h}.txt", subpath):
            screen_height = h
            break

    if screen_height:
        hw["screen_autoheight"] = False
        hw["screen_height"] = int(screen_height)
    else:
        hw["screen_autoheight"] = True

    # Screen width
    screen_width = "720"
    for w in ["640", "704"]:
        if settings.check_list(f"Screen_Width_{w}.txt", subpath):
            screen_width = w
            break

    if screen_width != "720" or screen_height:
        hw["screen_width"] = int(screen_width)

    # Offsets
    offset_h = settings.value_list("Screen_Offset_H.txt", subpath)
    offset_v = settings.value_list("Screen_Offset_V.txt", subpath)

    h_offset = None
    if offset_h.lstrip("-").isdigit():
        h_offset = max(-60, min(60, int(offset_h)))

    v_offset = None
    if offset_v.lstrip("-").isdigit():
        v_offset = max(-20, min(20, int(offset_v)))

    # Centering (disabled if offset is set)
    hw["screen_centerh"] = "none" if h_offset is not None else "smart"
    hw["screen_centerv"] = "none" if v_offset is not None else "smart"

    if settings.check_list("Screen_NoCenter_H.txt", subpath):
        hw["screen_centerh"] = "none"
    if settings.check_list("Screen_NoCenter_V.txt", subpath):
        hw["screen_centerv"] = "none"

    if h_offset is not None:
        hw["screen_offseth"] = h_offset
    if v_offset is not None:
        hw["screen_offsetv"] = v_offset

    # Z3 RAM
    for i in range(8):
        z3 = 2 ** i
        if settings.check_list(f"Memory_Z3Ram_{z3}.txt", subpath):
            hw["z3_ram"] = z3
            hw["cpu_24bitaddressing"] = False
            break

    return hw


# ============================================================================
# Snippet support
# ============================================================================

def load_snippets(builder_dir: str) -> list[dict]:
    """Load XML snippet files and convert to JSON game entries."""
    import xml.etree.ElementTree as ET

    snippet_dir = os.path.join(builder_dir, "snippets")
    if not os.path.isdir(snippet_dir):
        return []

    # Reuse the converter's parsing logic
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from converter.xml_to_json import convert_game

    entries = []
    for snippet_file in sorted(os.listdir(snippet_dir)):
        path = os.path.join(snippet_dir, snippet_file)
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            content = f.read()

        # Wrap in root element for parsing
        xml_str = f"<root>{content}</root>"
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            print(f"  Warning: failed to parse snippet {snippet_file}", file=sys.stderr)
            continue

        for game_elem in root.findall("game"):
            entry = convert_game(game_elem)
            entries.append(entry)

    return entries


def apply_datapath_overrides(games: list[dict], settings: SettingsDB) -> None:
    """Apply datapath overrides to all entries, including unchanged incremental ones."""
    for game in games:
        archive_name = game.get("filename", "")
        for slave in game.get("slaves", []):
            override = settings.get_slave_datapath(archive_name, slave.get("filename", ""))
            if override:
                slave["datapath"] = override


# ============================================================================
# Main builder
# ============================================================================

def make_game_name(subpath: str) -> str:
    """Convert subpath like 'TurricanII' to friendly name 'Turrican II'."""
    import re
    # Insert spaces before capitals that follow lowercase
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", subpath)
    # Insert spaces before numbers that follow letters
    name = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", name)
    # Insert spaces after numbers that precede letters
    name = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", name)
    return name


def build_database(scan_dir: str, builder_dir: str, existing_db: str | None = None, full_refresh: bool = False) -> dict:
    settings = SettingsDB(builder_dir)

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

        # Determine default slave
        default_slave_override = settings.value_list("WHD_DefaultSlave.txt", filename_no_ext)
        default_slave = ""

        if default_slave_override:
            # Verify override exists in slaves
            for s in scan_result["slaves"]:
                if s["filename"] == default_slave_override or default_slave_override in s["filename"]:
                    default_slave = s["filename"]
                    break

        if not default_slave:
            if len(scan_result["slaves"]) == 1:
                default_slave = scan_result["slaves"][-1]["filename"]
            else:
                default_slave = scan_result["slaves"][0]["filename"]

        # Build hardware settings
        hardware = build_hardware(scan_result["slaves"], subpath, filename_no_ext, settings)

        # Custom controls
        custom_controls = settings.get_custom_controls(subpath)

        # Slave libraries
        slave_libraries = settings.check_list("WHD_Libraries.txt", subpath)

        # Game name from longname fixes or subpath
        longname = settings.value_list("WHD_Longname_Fixes.txt", subpath)
        game_name = longname if longname else make_game_name(subpath)

        # Build the entry
        slaves_out = []
        for s in scan_result["slaves"]:
            slave_entry = {
                "filename": s["filename"],
                "datapath": s.get("datapath", ""),
            }
            if "custom_fields" in s:
                slave_entry["custom_fields"] = s["custom_fields"]
            slaves_out.append(slave_entry)

        entry = {
            "filename": filename_no_ext,
            "sha1": archive_sha1,
            "name": game_name,
            "subpath": subpath,
            "variant_uuid": scan_result["variant_uuid"],
            "slave_count": len(scan_result["slaves"]),
            "slave_default": default_slave,
            "slave_libraries": slave_libraries,
            "slaves": slaves_out,
            "hardware": hardware,
        }

        if custom_controls:
            entry["custom_controls"] = custom_controls

        new_entries.append(entry)

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

    apply_datapath_overrides(merged, settings)

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
