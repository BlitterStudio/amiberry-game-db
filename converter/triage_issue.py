#!/usr/bin/env python3
"""Turn a "Game Settings Update" issue into concrete settings changes.

    triage_issue.py --issue N                            print the triage comment (Markdown)
    triage_issue.py --issue N --apply                    also write the changes to builder/
    triage_issue.py --issue N --apply --require-clean    write only if nothing needs a person
    triage_issue.py --list-duplicates                    open requests that should be labelled duplicate

Reads issues with the authenticated `gh` CLI. The comment lists the matched
database entry, every archive an "all versions" change would affect, the exact
file changes, the resulting hardware, and other open issues for the same
archive or game. Exit status 3 means an older open issue targets the same
archive (the workflow labels the issue `duplicate`); 4 means --require-clean
refused to apply.
"""

import argparse
import json
import os
import re
import subprocess
import sys

from check_overrides import CONTROL_LINE, JIT_CPUS
from overrides import (CLOCK_SPEEDS, CPU_MODELS, DEFAULT_BUILDER_DIR, DEFAULT_SCREEN_WIDTH, EXCLUSIVE_GROUPS,
                       SCREEN_HEIGHTS, SCREEN_WIDTHS, SHA1_KEY, VALUE_BOUNDS, VALUE_FILES, Z3_SIZES, Settings,
                       merge_hardware, resolve_slave, settings_hardware)

MARKER = "<!-- game-db-triage -->"
REPO_ROOT = os.path.dirname(DEFAULT_BUILDER_DIR)
EMPTY = {"", "_no response_", "no change", "none", "default", "ocs/ecs (default)"}
# Values written into "key value" settings lines: one token, no whitespace or line breaks.
SINGLE_TOKEN = re.compile(r"\S+")
# Amiberry puts the data path into the startup-sequence as DATA="<path>".
DATA_PATH = re.compile(r"[A-Za-z0-9_./:-]+")
# Game folders as used in settings files and builder/customcontrols paths.
SUBPATH_PART = re.compile(r"[A-Za-z0-9_!&+.-]+")

# Checkbox labels (current form and the first version of the form) -> settings file.
FLAG_LABELS = {
    "ntsc": "Chipset_ForceNTSC.txt",
    "ntsc mode required": "Chipset_ForceNTSC.txt",
    "immediate blitter": "Chipset_ImmediateBlitter.txt",
    "turn off horizontal centering": "Screen_NoCenter_H.txt",
    "turn off vertical centering": "Screen_NoCenter_V.txt",
    "needs extra libraries (e.g. xpk)": "WHD_Libraries.txt",
    "slave needs libraries": "WHD_Libraries.txt",
}
# CPU emulation dropdown options -> settings file. The modes exclude each other.
CPU_EMULATION_OPTIONS = {
    "cycle-exact (amiberry default)": "CPU_CycleExact.txt",
    "not cycle-exact": "CPU_NoCycleExact.txt",
    "not cycle-exact, cpu compatible off": "CPU_NoCompatible.txt",
    "jit (68020 or higher)": "CPU_ForceJIT.txt",
}
# The same modes as checkboxes in earlier versions of the form.
CPU_EMULATION_LABELS = {
    "cycle-exact cpu": "CPU_CycleExact.txt",
    "turn off cpu compatible mode": "CPU_NoCompatible.txt",
    "jit": "CPU_ForceJIT.txt",
    "jit recommended": "CPU_ForceJIT.txt",
}
PORT_FILES = ["Control_CD32.txt", "Control_Port0_Mouse.txt", "Control_Port0_CD32.txt",
              "Control_Port1_Mouse.txt", "Control_Port1_CD32.txt"]


# ---------------------------------------------------------------------------
# Issue parsing
# ---------------------------------------------------------------------------

# Exact form headings (lower-cased) -> section key. Current form, then the
# first version of the form. Anything else is an unknown section.
HEADING_KEYS = {
    "game name": "game name",
    "whdload archive filename": "whdload archive filename",
    "sha1 hash": "sha1 hash",
    "amiberry version tested": "amiberry version tested",
    "chipset (all versions)": "chipset",
    "cpu (all versions)": "cpu",
    "cpu clock speed (all versions)": "cpu clock speed",
    "zorro iii ram (all versions)": "zorro iii ram",
    "port 0 / mouse port (all versions)": "port 0",
    "port 1 / joystick port (all versions)": "port 1",
    "screen height (all versions)": "screen height",
    "screen width (all versions)": "screen width",
    "horizontal screen offset (all versions)": "horizontal screen offset",
    "vertical screen offset (all versions)": "vertical screen offset",
    "cpu emulation (all versions)": "cpu emulation",
    "turn on (all versions)": "turn on",
    "default slave (this archive)": "default slave",
    "data path (this archive)": "data path",
    "custom controller mappings (all versions)": "custom controller mappings",
    "additional notes": "additional notes",
    "chipset": "chipset",
    "cpu": "cpu",
    "primary control": "primary control",
    "cpu clock speed": "cpu clock speed",
    "additional settings": "additional settings",
    "screen height (if non-default)": "screen height",
    "screen width (if non-default)": "screen width",
    "custom controller mappings": "custom controller mappings",
}


def form_sections(body: str) -> tuple[str, list[tuple[str, str]]]:
    """(text before the first heading, [(section key, value), ...] in order).

    Unknown headings keep their raw (lower-cased) text as the key, so they are
    reported instead of being folded into a known section.
    """
    blocks = re.split(r"^### ", body or "", flags=re.M)
    sections = []
    for block in blocks[1:]:
        heading, _, value = block.partition("\n")
        raw = heading.strip().lower()
        value = value.strip()
        fenced = re.fullmatch(r"```\w*\n(.*?)\n?```", value, flags=re.S)
        sections.append((HEADING_KEYS.get(raw, raw), fenced.group(1).strip() if fenced else value))
    return blocks[0], sections


def parse_form(body: str) -> dict[str, str]:
    """Issue-form body -> {normalised heading: value}."""
    return dict(form_sections(body)[1])


# Raw HTML outside code blocks can hide text (a comment or a collapsed block)
# from the rendered issue while the parser still reads it.
RAW_HTML = re.compile(r"<(!--|/?[A-Za-z][A-Za-z0-9-]*(\s|/?>|$))")


def form_problems(body: str) -> list[str]:
    """Parts of the body that parse_form() would drop or overwrite, or that
    a maintainer reading the rendered issue would not see."""
    preamble, sections = form_sections(body)
    problems = []
    if preamble.strip():
        problems.append("The issue has text before the first form section; this has to be handled by hand.")
    seen: set[str] = set()
    for key, _ in sections:
        if key in seen:
            problems.append(f"The section `{key}` appears more than once; keep one.")
        seen.add(key)
    fenced = False
    for line in (body or "").splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and RAW_HTML.search(line):
            problems.append("The issue contains HTML outside a code block, which can hide text from the rendered "
                            "issue; this has to be handled by hand.")
            break
    return problems


def field(form: dict[str, str], *names: str) -> str:
    for name in names:
        value = form.get(name, "").strip()
        if value.lower() not in EMPTY:
            return value
    return ""


def checked(form: dict[str, str], *names: str) -> list[str]:
    labels = []
    for name in names:
        labels += [m.strip().lower() for m in re.findall(r"^\s*- \[[xX]\] (.+)$", form.get(name, ""), flags=re.M)]
    return labels


# ---------------------------------------------------------------------------
# Database lookup (same precedence as Amiberry: SHA1, then last filename match)
# ---------------------------------------------------------------------------

def request_archive(form: dict[str, str]) -> tuple[str, str]:
    """(archive filename without .lha, lowercase SHA1) as the request gives them.

    Every comparison of a request's archive goes through here so lookups,
    ambiguity checks and duplicate detection agree.
    """
    filename = field(form, "whdload archive filename")
    if filename.lower().endswith(".lha"):
        filename = filename[:-4]
    return filename, field(form, "sha1 hash").lower()


def find_entry(games: list[dict], filename: str, sha1: str) -> tuple[dict | None, str]:
    if sha1:
        for game in games:
            if game["sha1"] == sha1:
                return game, "SHA1"
    matches = [g for g in games if g["filename"] == filename]
    return (matches[-1], "filename") if matches else (None, "")


# ---------------------------------------------------------------------------
# Editable settings
# ---------------------------------------------------------------------------

class EditableSettings(Settings):
    """Settings with pending in-memory edits on top of the files on disk."""

    def __init__(self, builder_dir: str):
        super().__init__(builder_dir)
        self.files: dict[str, list[str]] = {}
        self.controls: dict[str, list[str]] = {}
        self.changes: list[str] = []

    def lines(self, filename: str) -> list[str]:
        if filename not in self.files:
            self.files[filename] = super().lines(filename)
        return self.files[filename]

    def custom_controls(self, subpath: str) -> list[str] | None:
        if subpath in self.controls:
            return self.controls[subpath]
        return super().custom_controls(subpath)

    def _touch(self) -> None:
        self._lists.clear()
        self._values.clear()

    def add(self, filename: str, key: str) -> None:
        if key not in self.lines(filename):
            self.lines(filename).append(key)
            self.changes.append(f"add `{key}` to `builder/settings/{filename}`")
            self._touch()

    def remove(self, filename: str, key: str) -> None:
        lines = self.lines(filename)
        old = [line for line in lines
               if (line.split()[:1] == [key] if filename in VALUE_FILES else line == key)]
        for line in old:
            lines.remove(line)
            self.changes.append(f"remove `{line}` from `builder/settings/{filename}`")
        if old:
            self._touch()

    def set_value(self, filename: str, key: str, value: str) -> None:
        lines = self.lines(filename)
        old = [line for line in lines if line.split()[:1] == [key]]
        new = f"{key} {value}"
        if old == [new]:
            return
        for line in old:
            lines.remove(line)
        lines.append(new)
        verb = "replace" if old else "add"
        self.changes.append(f"{verb} `{new}` in `builder/settings/{filename}`")
        self._touch()

    def set_controls(self, subpath: str, lines: list[str]) -> None:
        if self.custom_controls(subpath) != lines:
            self.controls[subpath] = lines
            shown = "".join(f"\n  {line}" for line in lines)
            self.changes.append(f"write these {len(lines)} mapping(s) to `builder/customcontrols/{subpath}`:\n"
                                f"  ```{shown}\n  ```")

    def exclusive(self, group: str, filename: str | None, key: str, value: str = "") -> None:
        """Make `filename` the only file of `group` naming `key` (None: none).

        `value` is the value for a `key value` file.
        """
        for name in EXCLUSIVE_GROUPS[group]:
            if name != filename:
                self.remove(name, key)
        if filename in VALUE_FILES:
            self.set_value(filename, key, value)
        elif filename:
            self.add(filename, key)

    def write(self) -> None:
        for filename, lines in self.files.items():
            path = os.path.join(self.settings_dir, filename)
            if lines == (super().lines(filename) if os.path.isfile(path) else []):
                continue
            if lines:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write("\n".join(lines) + "\n")
            elif os.path.isfile(path):
                os.remove(path)
        for subpath, lines in self.controls.items():
            path = os.path.realpath(os.path.join(self.customcontrols_dir, subpath))
            if not path.startswith(os.path.realpath(self.customcontrols_dir) + os.sep):
                raise ValueError(f"custom controls path outside builder/customcontrols: {subpath!r}")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("".join(line + "\n" for line in lines))


# ---------------------------------------------------------------------------
# Request -> changes
# ---------------------------------------------------------------------------

def effective_ports(entry: dict, settings: Settings) -> list[str]:
    hw = settings_hardware(entry["filename"], entry["subpath"], settings)
    return [hw["port0"], hw["port1"]]


def set_ports(settings: EditableSettings, subpath: str, wanted: list[str]) -> None:
    target = set()
    if wanted == ["cd32", "cd32"]:
        target.add("Control_CD32.txt")
    else:
        for n, mode in enumerate(wanted):
            if mode == "mouse":
                target.add(f"Control_Port{n}_Mouse.txt")
            elif mode == "cd32":
                target.add(f"Control_Port{n}_CD32.txt")
    for name in PORT_FILES:
        if name in target:
            settings.add(name, subpath)
        else:
            settings.remove(name, subpath)


def archive_key(entry: dict, games: list[dict]) -> str:
    """Key for archive-specific files: the SHA1 when the filename is shared."""
    shared = sum(1 for g in games if g["filename"] == entry["filename"]) > 1
    return entry["sha1"] if shared else entry["filename"]


# Section keys the request may contain.
KNOWN_HEADINGS = set(HEADING_KEYS.values())
# Free-text fields the bot does not interpret; anything beyond one line could
# hide an instruction, which belongs in Additional Notes instead.
SINGLE_LINE_HEADINGS = {"game name", "amiberry version tested", "whdload archive filename", "sha1 hash"}
PORT_NAMES = {"joystick": "joy", "mouse": "mouse", "cd32 pad": "cd32"}
# Exact chipset options (lower-cased), current form and the first one.
CHIPSET_OPTIONS = {"aga": "aga", "cd32": "cd32", "cd32 (aga with cd32 pads in both ports)": "cd32"}


def plan(form: dict[str, str], entry: dict, settings: EditableSettings, games: list[dict]) -> list[str]:
    """Apply the request to `settings`; return problems that need a human.

    Every value the request sets must be understood: anything unrecognised is a
    problem, so an unattended apply never silently drops part of a request.
    """
    problems: list[str] = []
    subpath, filename = entry["subpath"], entry["filename"]
    if not all(SUBPATH_PART.fullmatch(part) and part not in (".", "..") for part in subpath.split("/")):
        return [f"The entry's game folder `{subpath}` is not a plain folder name; this has to be handled by hand."]
    archive = archive_key(entry, games)

    for heading, value in form.items():
        if heading not in KNOWN_HEADINGS:
            problems.append(f"Unrecognised section `{heading}`; this has to be handled by hand.")
        elif heading in SINGLE_LINE_HEADINGS and "\n" in value.strip():
            problems.append(f"`{heading.capitalize()}` must be a single line; put anything else in Additional Notes.")

    chipset = field(form, "chipset").lower()
    current_ports = effective_ports(entry, settings)
    wanted_ports = list(current_ports)
    if chipset in CHIPSET_OPTIONS:
        settings.add("Chipset_AGA.txt", subpath)
        if CHIPSET_OPTIONS[chipset] == "cd32":
            wanted_ports = ["cd32", "cd32"]
    elif chipset:
        problems.append(f"Unsupported chipset `{chipset}` (supported: AGA, CD32).")

    cpu = field(form, "cpu")
    if cpu:
        if cpu in CPU_MODELS:
            settings.exclusive("CPU model", f"CPU_Model_{cpu}.txt", subpath)
        else:
            problems.append(f"Unsupported CPU `{cpu}` (supported: {', '.join(CPU_MODELS)}).")

    clock = field(form, "cpu clock speed").lower().replace(" mhz", "")
    if clock:
        name = next((n for n, v in CLOCK_SPEEDS if v == clock), None)
        if name:
            settings.exclusive("CPU clock", f"CPU_ClockSpeed_{name}.txt", subpath)
        else:
            problems.append(f"Unsupported clock speed `{clock}`.")

    z3 = field(form, "zorro iii ram").lower().replace(" mb", "")
    if z3:
        if re.fullmatch(r"[0-9]+", z3) and int(z3) in Z3_SIZES:
            settings.exclusive("Z3 RAM", f"Memory_Z3Ram_{z3}.txt", subpath)
        else:
            problems.append(f"Unsupported Z3 RAM size `{z3}`.")

    for n, heading in enumerate(("port 0", "port 1")):
        value = field(form, heading).lower()
        if value in PORT_NAMES:
            wanted_ports[n] = PORT_NAMES[value]
        elif value:
            problems.append(f"Unsupported {heading} setting `{value}` (supported: Joystick, Mouse, CD32 pad).")
    legacy_control = field(form, "primary control").lower()
    if legacy_control == "mouse":
        wanted_ports[0] = "mouse"
    elif legacy_control not in ("", "joystick"):
        problems.append(f"Unsupported primary control `{legacy_control}`.")
    if wanted_ports != current_ports:
        set_ports(settings, subpath, wanted_ports)
        effective = effective_ports(entry, settings)
        if effective != wanted_ports:
            problems.append(f"The archive name contains `_CD32`, so the ports end up as {effective[0]}/{effective[1]} "
                            f"instead of the requested {wanted_ports[0]}/{wanted_ports[1]}.")

    # Horace's fixed sizes keep their list files; any other size goes in the value file.
    for heading, name, fixed, default in (("screen height", "Screen_Height", SCREEN_HEIGHTS, "automatic"),
                                          ("screen width", "Screen_Width", SCREEN_WIDTHS, str(DEFAULT_SCREEN_WIDTH))):
        value = field(form, heading).lower()
        low, high = VALUE_BOUNDS[f"{name}.txt"]
        if value == default:
            settings.exclusive(heading, None, subpath)
        elif re.fullmatch(r"[0-9]+", value) and low <= int(value) <= high:
            value = str(int(value))
            if value in fixed:
                settings.exclusive(heading, f"{name}_{value}.txt", subpath)
            else:
                settings.exclusive(heading, f"{name}.txt", subpath, value)
        elif value:
            allowed = f"a whole number from {low} to {high}" + (", or Automatic" if default == "automatic" else "")
            problems.append(f"{heading.capitalize()} `{value}` must be {allowed}.")

    offset_headings = (("horizontal screen offset", "Screen_Offset_H.txt"),
                       ("vertical screen offset", "Screen_Offset_V.txt"))
    for heading, name in offset_headings:
        value = field(form, heading)
        low, high = VALUE_BOUNDS[name]
        if value:
            if re.fullmatch(r"-?[0-9]+", value) and low <= int(value) <= high:
                settings.set_value(name, subpath, str(int(value)))
            else:
                problems.append(f"{heading.capitalize()} `{value}` must be a whole number from {low} to {high}.")

    # Every line of a checkbox section must be a known option, ticked or not;
    # anything else (an added instruction) needs a person.
    known_options = set(FLAG_LABELS) | set(CPU_EMULATION_LABELS) | {"cpu compatible mode"}
    for heading in ("turn on", "additional settings"):
        for line in form.get(heading, "").splitlines():
            line = line.strip()
            if not line or line.lower() in EMPTY:
                continue
            row = re.fullmatch(r"- \[[ xX]\] (.+)", line)
            if not row or row.group(1).strip().lower() not in known_options:
                problems.append(f"Unrecognised line `{line}` under {heading.title()}.")

    ticked = checked(form, "turn on", "additional settings")
    for label in ticked:
        if label in FLAG_LABELS:
            settings.add(FLAG_LABELS[label], subpath)
        elif label == "cpu compatible mode":
            problems.append("\"CPU compatible mode\" is ambiguous (it is on by default); say whether it should be turned off.")

    # The dropdown, or the checkboxes of earlier forms.
    cpu_modes = [CPU_EMULATION_LABELS[label] for label in ticked if label in CPU_EMULATION_LABELS]
    cpu_emulation = field(form, "cpu emulation").lower()
    if cpu_emulation in CPU_EMULATION_OPTIONS:
        cpu_modes.append(CPU_EMULATION_OPTIONS[cpu_emulation])
    elif cpu_emulation:
        problems.append(f"Unsupported CPU emulation `{cpu_emulation}`.")
    if len(set(cpu_modes)) > 1:
        problems.append("Cycle-exact, not cycle-exact, CPU compatible off and JIT exclude each other; pick one.")
    elif cpu_modes:
        settings.exclusive("CPU emulation", cpu_modes[0], subpath)

    slave = field(form, "default slave")
    if slave:
        resolved = resolve_slave(slave, entry.get("slaves", [])) if SINGLE_TOKEN.fullmatch(slave) else ""
        if resolved:
            settings.set_value("WHD_DefaultSlave.txt", archive, resolved)
        else:
            names = ", ".join(f"`{s['filename']}`" for s in entry.get("slaves", []))
            problems.append(f"The archive has no slave `{slave}` (slaves: {names}).")

    datapath = field(form, "data path")
    if datapath:
        if not DATA_PATH.fullmatch(datapath):
            problems.append(f"Data path `{datapath}` must be one word of letters, digits and `_ . / : -`.")
        else:
            settings.set_value("WHD_DataPath.txt", archive, datapath)

    controls = field(form, "custom controller mappings")
    if controls:
        lines = [line.strip() for line in controls.splitlines() if line.strip()]
        bad = [line for line in lines if not CONTROL_LINE.match(line) or "`" in line]
        if bad:
            problems.append("Not valid mapping lines: " + ", ".join(f"`{b}`" for b in bad))
        else:
            settings.set_controls(subpath, lines)

    # Combinations Amiberry would silently ignore.
    after = merge_hardware(entry.get("hardware", {}), settings_hardware(filename, subpath, settings))
    if after.get("jit") and after.get("chipset") != "aga" and after.get("cpu") not in JIT_CPUS:
        problems.append("JIT needs a 68020 or higher, and this game runs on a 68000/68010; set CPU 68020 or "
                        "chipset AGA too, or pick another CPU emulation.")
    if after.get("chipset") == "aga" and after.get("cpu") in ("68000", "68010"):
        problems.append(f"AGA games run on a 68020 or higher in Amiberry, so CPU {after['cpu']} has no effect.")
    width = field(form, "screen width")
    if after["screen_autoheight"] and (width not in ("", str(DEFAULT_SCREEN_WIDTH))
                                       or any(field(form, heading) for heading, _ in offset_headings)):
        problems.append("Amiberry ignores the screen width and offsets while the screen height is Automatic, "
                        "because it crops automatically; set a screen height as well.")

    return problems


# ---------------------------------------------------------------------------
# Comment
# ---------------------------------------------------------------------------

def hardware_table(before: dict, after: dict) -> list[str]:
    rows = ["| Setting | Current | After this request |", "|---|---|---|"]
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key, ""), after.get(key, "")
        mark = "" if old == new else " **(changed)**"
        rows.append(f"| `{key}` | {old} | {new}{mark} |")
    return rows


def related_issues(number: int, filename: str, sha1: str, entry: dict | None, games: list[dict],
                   others: list[dict]) -> tuple[list[str], list[str], list[str]]:
    """Other open requests: (older, same archive), (newer, same archive), (same game)."""
    older, newer, same_game = [], [], []
    for issue in others:
        if issue["number"] == number:
            continue
        other_file, other_sha1 = request_archive(parse_form(issue.get("body", "")))
        ref = f"#{issue['number']}"
        # Filenames are shared by different archives; compare them only when
        # either request lacks a usable SHA1.
        if SHA1_KEY.fullmatch(sha1) and SHA1_KEY.fullmatch(other_sha1):
            same = sha1 == other_sha1
        else:
            same = bool(other_file) and other_file == filename
        if same:
            (older if issue["number"] < number else newer).append(ref)
            continue
        if entry:
            other, _ = find_entry(games, other_file, other_sha1)
            if other and other["subpath"] == entry["subpath"]:
                same_game.append(ref)
    return older, newer, same_game


def archive_identity_problems(filename: str, sha1: str, matched_by: str, games: list[dict]) -> list[str]:
    """Reasons the matched entry may not be the requester's archive."""
    if sha1 and not SHA1_KEY.fullmatch(sha1):
        return [f"The SHA1 `{sha1}` is not a 40-character hex value; please check it."]
    if sha1 and matched_by == "filename":
        return [f"No archive has the SHA1 `{sha1}`; the entry was found by filename only. "
                "Please check the SHA1 of your .lha file."]
    if not sha1 and sum(1 for g in games if g["filename"] == filename) > 1:
        return [f"Several archives are named `{filename}`; add the SHA1 of your .lha file "
                "so the right one is changed."]
    return []


def triage(issue: dict, others: list[dict], games: list[dict],
           builder_dir: str) -> tuple[str, bool, EditableSettings | None, list[str]]:
    """Return (comment, has an older duplicate, pending settings or None, problems)."""
    form = parse_form(issue.get("body", ""))
    filename, sha1 = request_archive(form)
    entry, matched_by = find_entry(games, filename, sha1)
    out = [MARKER, "Automated check of this request against the current database.", ""]
    if not filename:
        out += ["This issue does not use the Game Settings Update form (no archive filename), "
                "so there is nothing to check automatically."]
        return "\n".join(out) + "\n", False, None, []

    # Only the newer request of a pair is the duplicate; the oldest one stays open.
    older, newer, same_game = related_issues(issue["number"], filename, sha1, entry, games, others)
    if older:
        verb = "asks" if len(older) == 1 else "ask"
        out += [f"**Possible duplicate:** {', '.join(older)} already {verb} about this archive. "
                "Please add your findings there instead.", ""]
    if newer:
        out += [f"**Same archive:** later request(s) {', '.join(newer)}.", ""]
    if same_game:
        out += [f"**Related:** {', '.join(same_game)} change(s) the same game (other versions).", ""]

    if not entry:
        out += [f"`{filename}` {('(' + sha1 + ') ') if sha1 else ''}is not in the database. "
                "A maintainer needs to add it as a snippet in `builder/snippets/` "
                "(see CONTRIBUTING.md); the settings can then be applied.", ""]
        return "\n".join(out) + "\n", bool(older), None, []

    settings = EditableSettings(builder_dir)
    hardware = entry.get("hardware", {})
    before = merge_hardware(hardware, settings_hardware(entry["filename"], entry["subpath"], settings))
    problems = (form_problems(issue.get("body", "")) + archive_identity_problems(filename, sha1, matched_by, games)
                + plan(form, entry, settings, games))
    after = merge_hardware(hardware, settings_hardware(entry["filename"], entry["subpath"], settings))

    siblings = [g for g in games if g["subpath"] == entry["subpath"]]
    names = [g["filename"] for g in siblings]
    labels = [f"`{g['filename']}`" + (f" ({g['sha1'][:8]})" if names.count(g["filename"]) > 1 else "")
              for g in siblings]
    out += [f"**Archive:** `{entry['filename']}` (`{entry['sha1']}`), matched by {matched_by}.",
            f"**Game folder:** `{entry['subpath']}`. Settings marked \"all versions\" apply to "
            f"{len(siblings)} archive(s): {', '.join(labels)}.", ""]

    if settings.changes:
        out += ["### Changes needed", ""] + [f"- {c}" for c in settings.changes] + [""]
    else:
        out += ["### Changes needed", "", "None: the database already has these settings.", ""]

    out += ["### Hardware", ""] + hardware_table(before, after) + [""]
    if any("WHD_DefaultSlave" in c for c in settings.changes):
        out += [f"Default slave: `{entry.get('slave_default')}` -> "
                f"`{settings.default_slave(entry)}`", ""]
    controls = entry.get("custom_controls", [])
    if controls:
        out += ["Current controller mappings:", "", "```", *controls, "```", ""]
    if problems:
        out += ["### Needs a maintainer", ""] + [f"- {p}" for p in problems] + [""]
    if field(form, "additional notes"):
        out += ["### Additional notes", "",
                "The bot does not act on Additional Notes. The `accepted` label applies only the changes "
                "listed above and leaves this issue open, so anything else in the notes still needs a person.", ""]

    out += ["Maintainers: add the `accepted` label to apply these changes and publish them. "
            "Locally, `python3 converter/triage_issue.py --issue "
            f"{issue['number']} --apply` writes them under `builder/`."]
    return "\n".join(out) + "\n", bool(older), settings, problems


NOTHING_TO_CHANGE = "Nothing to change: the database already has these settings."


def refusal_reasons(duplicate: bool, settings: EditableSettings | None, problems: list[str]) -> list[str]:
    """Why a request cannot be applied unattended; empty when it can."""
    if settings is None:
        return ["The archive is not in the database (or the issue does not use the form). "
                "Add a snippet first (see CONTRIBUTING.md), then label the issue again."]
    reasons = []
    if duplicate:
        reasons.append("An older open request covers the same archive; apply or close that one first.")
    reasons += problems
    if not reasons and not settings.changes:
        reasons.append(NOTHING_TO_CHANGE)
    return reasons


def duplicate_numbers(issues: list[dict]) -> list[int]:
    """Open requests that have an older open request for the same archive."""
    result = []
    for issue in issues:
        form = parse_form(issue.get("body", ""))
        filename, sha1 = request_archive(form)
        if not filename:
            continue
        older, _, _ = related_issues(issue["number"], filename, sha1, None, [], issues)
        if older:
            result.append(issue["number"])
    return sorted(result)


def gh_json(*args: str):
    return json.loads(subprocess.run(["gh", *args], check=True, capture_output=True, text=True,
                                     encoding="utf-8").stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--issue", type=int)
    mode.add_argument("--list-duplicates", action="store_true",
                      help="print the open requests that should carry the duplicate label, one per line")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "BlitterStudio/amiberry-game-db"))
    parser.add_argument("--db", default=os.path.join(REPO_ROOT, "whdload_db.json"))
    parser.add_argument("--builder-dir", default=DEFAULT_BUILDER_DIR)
    parser.add_argument("--apply", action="store_true", help="write the changes to builder/")
    parser.add_argument("--require-clean", action="store_true",
                        help="with --apply: write nothing unless the request is unambiguous (in the database, "
                             "no older duplicate, nothing flagged for a maintainer); exit 5 if the database "
                             "already has the settings, 4 for any other refusal; the reasons go to --output")
    parser.add_argument("--body-file", help="use this issue body instead of fetching the current one")
    parser.add_argument("--notes-output", help="write the request's Additional Notes (if any) to this file")
    parser.add_argument("--pending-output",
                        help="write how many settings changes the request still needs, or 'unknown' if the "
                             "archive was not found")
    parser.add_argument("--output", help="also write the comment (or, on refusal, the reasons) to this file")
    args = parser.parse_args()

    others = gh_json("issue", "list", "-R", args.repo, "--state", "open", "--label", "game-update",
                     "--limit", "500", "--json", "number,body")
    if args.list_duplicates:
        print("\n".join(str(n) for n in duplicate_numbers(others)))
        return

    with open(args.db, encoding="utf-8") as f:
        games = json.load(f)["games"]
    issue = gh_json("issue", "view", str(args.issue), "-R", args.repo, "--json", "number,body")
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as f:
            issue["body"] = f.read()
    comment, duplicate, settings, problems = triage(issue, others, games, args.builder_dir)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.notes_output:
        with open(args.notes_output, "w", encoding="utf-8") as f:
            f.write(field(parse_form(issue.get("body", "")), "additional notes"))
    if args.pending_output:
        with open(args.pending_output, "w", encoding="utf-8") as f:
            f.write("unknown" if settings is None else str(len(settings.changes)))

    if args.apply and args.require_clean:
        reasons = refusal_reasons(duplicate, settings, problems)
        if reasons:
            text = "Not applied:\n\n" + "".join(f"- {r}\n" for r in reasons)
            print(text, end="")
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(text)
            sys.exit(5 if reasons == [NOTHING_TO_CHANGE] else 4)

    print(comment, end="")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(comment)
    if args.apply:
        if settings is None or not settings.changes:
            print("\nNothing to apply.", file=sys.stderr)
        else:
            settings.write()
            print(f"\nWrote {len(settings.changes)} change(s) under {args.builder_dir}.", file=sys.stderr)
    sys.exit(3 if duplicate else 0)


if __name__ == "__main__":
    main()
