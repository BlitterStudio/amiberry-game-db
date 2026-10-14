"""Per-game overrides from builder/settings and builder/customcontrols.

The settings format is the one used by HoraceAndTheSpider's Amiberry-XML-Builder:
one file per setting, one game per line. Most files are keyed by subpath (the
game's folder name inside the archive, shared by every version of the game);
WHD_DefaultSlave.txt and WHD_DataPath.txt are keyed by archive filename, or by
archive SHA1 when several archives share a filename.

Both the XML converter and the LHA builder apply these overrides to every
entry on every run, so a change here reaches all matching games, not only
newly scanned archives.
"""

import os
import re

SHA1_KEY = re.compile(r"[0-9a-f]{40}")
DEFAULT_BUILDER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "builder")

SCREEN_HEIGHTS = ("400", "432", "480", "512", "524", "540", "568")
SCREEN_WIDTHS = ("640", "704")
DEFAULT_SCREEN_WIDTH = "720"
# Later entries win when a game is listed in more than one file, matching
# Horace's builder; the linter rejects such conflicts anyway.
CLOCK_SPEEDS = (("7", "7"), ("14", "14"), ("25", "25"), ("28", "28"), ("Max", "max"))
CPU_MODELS = ("68000", "68010", "68020", "68040")
Z3_SIZES = tuple(2 ** i for i in range(8))  # 1..128 MB
OFFSET_H_RANGE = (-60, 60)
OFFSET_V_RANGE = (-20, 20)

# Plain list files: one subpath per line.
FLAG_FILES = (
    "Chipset_AGA.txt",
    "Chipset_ForceNTSC.txt",
    "Chipset_ImmediateBlitter.txt",
    "Control_CD32.txt",
    "Control_Port0_CD32.txt",
    "Control_Port0_Mouse.txt",
    "Control_Port1_CD32.txt",
    "Control_Port1_Mouse.txt",
    "CPU_CycleExact.txt",
    "CPU_ForceJIT.txt",
    "CPU_NoCompatible.txt",
    "Screen_NoCenter_H.txt",
    "Screen_NoCenter_V.txt",
    "WHD_Libraries.txt",
    *(f"CPU_ClockSpeed_{name}.txt" for name, _ in CLOCK_SPEEDS),
    *(f"CPU_Model_{model}.txt" for model in CPU_MODELS),
    *(f"Memory_Z3Ram_{size}.txt" for size in Z3_SIZES),
    *(f"Screen_Height_{h}.txt" for h in SCREEN_HEIGHTS),
    *(f"Screen_Width_{w}.txt" for w in SCREEN_WIDTHS),
)

# "key value" files. Archive keys are the archive filename or, when several
# archives share a filename, the archive's SHA1 (a SHA1 key wins).
VALUE_FILES = {
    "Screen_Offset_H.txt": "subpath",
    "Screen_Offset_V.txt": "subpath",
    "WHD_DefaultSlave.txt": "archive",
    "WHD_DataPath.txt": "archive",
}

# Read when generating names (make_snippet.py, build_db.py); the XML sync keeps upstream names.
BUILDER_ONLY_FILES = ("WHD_Longname_Fixes.txt",)

# A game may appear in at most one file of each group.
EXCLUSIVE_GROUPS = {
    "screen height": [f"Screen_Height_{h}.txt" for h in SCREEN_HEIGHTS],
    "screen width": [f"Screen_Width_{w}.txt" for w in SCREEN_WIDTHS],
    "CPU clock": [f"CPU_ClockSpeed_{name}.txt" for name, _ in CLOCK_SPEEDS],
    "CPU model": [f"CPU_Model_{model}.txt" for model in CPU_MODELS],
    "Z3 RAM": [f"Memory_Z3Ram_{size}.txt" for size in Z3_SIZES],
    "port 0": ["Control_Port0_Mouse.txt", "Control_Port0_CD32.txt"],
    "port 1": ["Control_Port1_Mouse.txt", "Control_Port1_CD32.txt"],
}

# Hardware keys fully determined by settings + archive filename. Values for
# these keys coming from upstream are replaced. fast_copper is listed so the
# upstream value is always dropped: only Amiberry-Lite uses it, and Lite reads
# Horace's XML directly, so it has no place in whdload_db.json.
CONTROLLED_HARDWARE_KEYS = frozenset({
    "blitter", "clock", "cpu_24bitaddressing", "z3_ram", "cpu_compatible",
    "cpu_exact", "fast_copper", "jit", "ntsc", "primary_control", "port0",
    "port1", "screen_autoheight", "screen_height", "screen_width",
    "screen_centerh", "screen_centerv", "screen_offseth", "screen_offsetv",
})


def _strip_media_ext(name: str) -> str:
    """Horace's check_list ignores these extensions on the game name."""
    for ext in (".iso", ".cue", ".adf", ".hdf"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name


def _read_lines(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


class Settings:
    """Loaded builder/settings and builder/customcontrols data."""

    def __init__(self, builder_dir: str = DEFAULT_BUILDER_DIR):
        self.builder_dir = builder_dir
        self.settings_dir = os.path.join(builder_dir, "settings")
        self.customcontrols_dir = os.path.join(builder_dir, "customcontrols")
        self._lists: dict[str, set[str]] = {}
        self._values: dict[str, dict[str, str]] = {}

    def lines(self, filename: str) -> list[str]:
        path = os.path.join(self.settings_dir, filename)
        return _read_lines(path) if os.path.isfile(path) else []

    def listed(self, filename: str, subpath: str) -> bool:
        entries = self._lists.get(filename)
        if entries is None:
            entries = self._lists[filename] = set(self.lines(filename))
        return _strip_media_ext(subpath) in entries

    def value(self, filename: str, key: str) -> str:
        values = self._values.get(filename)
        if values is None:
            values = {}
            for line in self.lines(filename):
                parts = line.split()
                if len(parts) >= 2 and parts[0] not in values:
                    values[parts[0]] = parts[1]
            self._values[filename] = values
        return values.get(key, "")

    def custom_controls(self, subpath: str) -> list[str] | None:
        """Mapping lines for a game, or None when it has no customcontrols file.

        An existing but empty file yields [] and clears upstream mappings.
        """
        path = os.path.join(self.customcontrols_dir, subpath)
        if not os.path.isfile(path):
            return None
        return [line for line in _read_lines(path) if "amiberry_custom" in line]

    def archive_value(self, filename: str, entry: dict, suffix: str = "") -> str:
        """Value for an archive-keyed file: SHA1 key first, then filename."""
        return (self.value(filename, entry.get("sha1", "") + suffix)
                or self.value(filename, entry.get("filename", "") + suffix))

    def default_slave(self, entry: dict) -> str:
        return self.archive_value("WHD_DefaultSlave.txt", entry)

    def datapath(self, entry: dict, slave: str) -> str:
        """SHA1 keys beat filename keys; within each, `/slave` beats archive-wide."""
        sha1, filename = entry.get("sha1", ""), entry.get("filename", "")
        for key in (f"{sha1}/{slave}", sha1, f"{filename}/{slave}", filename):
            value = self.value("WHD_DataPath.txt", key)
            if value:
                return value
        return ""


def _offset(raw: str, bounds: tuple[int, int]) -> int | None:
    if not re.fullmatch(r"-?\d+", raw):
        return None
    return max(bounds[0], min(bounds[1], int(raw)))


def settings_hardware(filename: str, subpath: str, settings: Settings) -> dict:
    """Hardware settings for a game, following Horace's builder rules."""
    listed = lambda name: settings.listed(name, subpath)  # noqa: E731
    hw: dict = {}

    if listed("Chipset_ImmediateBlitter.txt"):
        hw["blitter"] = "immediate"

    cd32_both = listed("Control_CD32.txt") or "_CD32" in filename
    if "_AGA" in filename or "_CD32" in filename or listed("Chipset_AGA.txt"):
        hw["chipset"] = "aga"

    for name, value in CLOCK_SPEEDS:
        if listed(f"CPU_ClockSpeed_{name}.txt"):
            hw["clock"] = value

    for model in CPU_MODELS:
        if listed(f"CPU_Model_{model}.txt"):
            hw["cpu"] = model
            break

    z3 = next((size for size in Z3_SIZES if listed(f"Memory_Z3Ram_{size}.txt")), 0)
    if z3:
        hw["cpu_24bitaddressing"] = False
    if listed("CPU_NoCompatible.txt"):
        hw["cpu_compatible"] = False
    if listed("CPU_CycleExact.txt"):
        hw["cpu_exact"] = True
    if listed("CPU_ForceJIT.txt"):
        hw["jit"] = True
    if listed("Chipset_ForceNTSC.txt") or "NTSC" in filename:
        hw["ntsc"] = True

    mouse0 = listed("Control_Port0_Mouse.txt")
    mouse1 = listed("Control_Port1_Mouse.txt")
    hw["primary_control"] = "mouse" if mouse0 else "joystick"
    hw["port0"] = "mouse" if mouse0 else "cd32" if cd32_both or listed("Control_Port0_CD32.txt") else "joy"
    hw["port1"] = "mouse" if mouse1 else "cd32" if cd32_both or listed("Control_Port1_CD32.txt") else "joy"

    height = next((h for h in SCREEN_HEIGHTS if listed(f"Screen_Height_{h}.txt")), "")
    width = next((w for w in SCREEN_WIDTHS if listed(f"Screen_Width_{w}.txt")), DEFAULT_SCREEN_WIDTH)
    hw["screen_autoheight"] = not height
    if height:
        hw["screen_height"] = int(height)
    if height or width != DEFAULT_SCREEN_WIDTH:
        hw["screen_width"] = int(width)

    offset_h = _offset(settings.value("Screen_Offset_H.txt", subpath), OFFSET_H_RANGE)
    offset_v = _offset(settings.value("Screen_Offset_V.txt", subpath), OFFSET_V_RANGE)
    hw["screen_centerh"] = "none" if offset_h is not None or listed("Screen_NoCenter_H.txt") else "smart"
    hw["screen_centerv"] = "none" if offset_v is not None or listed("Screen_NoCenter_V.txt") else "smart"
    if offset_h is not None:
        hw["screen_offseth"] = offset_h
    if offset_v is not None:
        hw["screen_offsetv"] = offset_v
    if z3:
        hw["z3_ram"] = z3

    return hw


def merge_hardware(current: dict, computed: dict) -> dict:
    """Replace settings-controlled keys; keep keys settings cannot express.

    chipset and cpu are not controlled: they can also come from slave headers
    or hand-written snippets, so a settings value wins but its absence keeps
    the upstream value.
    """
    merged = dict(computed)
    for key, value in current.items():
        if key not in CONTROLLED_HARDWARE_KEYS and key not in merged:
            merged[key] = value
    return merged


def resolve_slave(requested: str, slaves: list[dict]) -> str:
    """Match a default-slave override against the archive's slaves.

    Exact (case-insensitive) match first, then substring, like both builders.
    """
    names = [s.get("filename", "") for s in slaves]
    lowered = requested.lower()
    for name in names:
        if name.lower() == lowered:
            return name
    for name in names:
        if requested in name:
            return name
    return ""


def apply_overrides(entry: dict, settings: Settings) -> None:
    """Apply all overrides to one game entry in place."""
    filename = entry.get("filename", "")
    subpath = entry.get("subpath", "")

    entry["hardware"] = merge_hardware(entry.get("hardware", {}), settings_hardware(filename, subpath, settings))
    entry["slave_libraries"] = settings.listed("WHD_Libraries.txt", subpath)

    controls = settings.custom_controls(subpath)
    if controls is not None:
        if controls:
            entry["custom_controls"] = controls
        else:
            entry.pop("custom_controls", None)

    slaves = entry.get("slaves", [])
    requested = settings.default_slave(entry)
    if requested:
        resolved = resolve_slave(requested, slaves)
        if resolved:
            entry["slave_default"] = resolved

    for slave in slaves:
        override = settings.datapath(entry, slave.get("filename", ""))
        if override:
            slave["datapath"] = override
