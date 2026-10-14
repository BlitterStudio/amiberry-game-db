"""Game names from subpaths, ported from Horace's utils/text_utils.make_full_name.

Kept deliberately close to the original (including its 1-based AMOS-style
string helpers) so names match the upstream XML for the same subpath and
WHD_Longname_Fixes.txt.
"""


def _left(s: str, amount: int) -> str:
    return s[:amount]


def _right(s: str, amount: int) -> str:
    return s[-amount:]  # amount 0 returns the whole string, as upstream does


def _mid_amos(s: str, point: int, amount: int) -> str:
    if point == 0:
        point = 1
    return s[point - 1:point - 1 + amount]


def _add_space(s: str, pos: int) -> str:
    return _left(s, pos - 1) + " " + _right(s, len(s) - pos + 1)


_SUFFIX_FIXES = (
    ("  ", " "), ("___", ""), ("CD 32", "CD32"), (" CD32", " [CD32]"), (" CDTV", " [CDTV]"),
    (" AGA", " [AGA]"), (" 512 Kb", " (512Kb)"), (" 512 KB", " (512Kb)"), (" 512k", " (512Kb)"),
    (" 1 MB", " (1MB)"), (" 2 MB", " (2MB)"), (" 4 MB", " (4MB)"), (" 8 MB", " (8MB)"),
    (" 1 Disk", " (1 Disk)"), (" 2 Disk", " (2 Disk)"), (" 3 Disk", " (3 Disk)"), (" 4 Disk", " (4 Disk)"),
    (" Files", " (Files)"), (" Image", " (Image)"), (" Chip", " (Chip)"), (" Fast", " (Fast)"),
    ("(Fast) Break", "Fast Break"), ("R³sselsheim", "Russelsheim"), (" NTSC", " (NTSC)"),
)

_LANGUAGES = {
    " De": " (Deutsch)", " Pl": " (Polski)", " It": " (Italiano)", " Dk": " (Dansk)",
    " Es": " (Espanol)", " Fr": " (Francais)", " Cz": " (Czech)", " Se": " (Svenska)",
    " Fi": " (Finnish)",
}


def make_full_name(subpath: str, longname_fixes: list[str]) -> str:
    """Display name for a subpath; `longname_fixes` are WHD_Longname_Fixes.txt lines."""
    name = subpath.replace("'n'", " 'n'").replace("+", " +").replace("&", " &")

    old_name = name
    name += "___"
    first_length = len(name)
    a, b = 1, len(old_name)
    while a < len(name) and a < b:
        a += 1
        prev_char_2 = ord(_mid_amos(name, a - 2, 1))
        prev_char = ord(_mid_amos(name, a - 1, 1))
        this_char = ord(_mid_amos(name, a, 1))
        next_char = ord(_mid_amos(name, a + 1, 1))

        if 65 <= this_char <= 90:  # capital letter
            if chr(this_char) == "M" and chr(next_char) == "B" and 48 <= this_char <= 57:
                pass  # upstream's "MB" rule; the digit test means it never fires
            elif prev_char == 95 and prev_char_2 == 95:
                pass
            elif prev_char == 92 and prev_char_2 == 92:
                pass
            elif prev_char == 65 and this_char != 71 and next_char != 65:
                name = _add_space(name, a)
                a += 1
                b += 1
            elif prev_char != 32 and prev_char != 45 and not (65 <= prev_char <= 90):
                name = _add_space(name, a)
                a += 1
                b += 1
        elif 48 <= this_char <= 57:  # digit
            if not (48 <= prev_char <= 57) and prev_char != 32:
                name = _add_space(name, a)
                a += 1
                b += 1

        if a > first_length:
            break

    for find, replace in _SUFFIX_FIXES:
        name = name.replace(find, replace)

    for line in longname_fixes:
        if "|" in line:
            sep = line.find("|")
            find, replace = _left(line, sep), _right(line, len(line) - sep - 1)
            if name == find:
                name = replace

    language = _right(name, 3)
    if language in _LANGUAGES:
        name = _left(name, len(name) - 3) + _LANGUAGES[language]
    return name
