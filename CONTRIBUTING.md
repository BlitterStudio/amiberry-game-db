# Contributing to the Amiberry Game Database

This repository maintains `whdload_db.json`, the game compatibility database used by Amiberry's WHDLoad booter.

Do not edit `whdload_db.json` directly. CI rejects pull requests that touch it. The file is built automatically from upstream data and the override files in `builder/`.

## How Changes Flow

1. **Submit**: Open an issue using the [Game Settings Update](https://github.com/BlitterStudio/amiberry-game-db/issues/new?template=game-settings.yml) template, or open a pull request that edits files in `builder/`.
2. **Validate**: CI runs lint and schema checks, then posts an entry-level diff in the job summary.
3. **Merge**: A maintainer merges the pull request into `main`.
4. **Publish**: The sync workflow rebuilds `whdload_db.json`, commits it to `main`, and publishes it to GitHub Pages (`db.amiberry.com`).
5. **Distribution**: Users download the updated database inside Amiberry, or receive it bundled in the next Amiberry release.

## Ways to Contribute

### 1. Issue Form (Recommended)

Use the [Game Settings Update](https://github.com/BlitterStudio/amiberry-game-db/issues/new?template=game-settings.yml) issue template.

- Fill in the game name, archive filename (without `.lha`), and SHA1 hash.
- Amiberry logs the SHA1 on launch. You can also get it with `sha1sum <archive>.lha` or `Get-FileHash -Algorithm SHA1 <archive>.lha`.
- Only fill in fields that need to change. Leave unchanged fields at default.
- Submit one issue per archive.

A triage bot matches the archive against the database, posts the exact file changes needed, lists other versions of the same game that share the folder name, and tags duplicates.

### 2. Pull Request

Fork this repository, create a branch, edit files in `builder/`, and submit a pull request.

Valid files to edit:
- `builder/settings/*`: hardware and slave settings.
- `builder/customcontrols/*`: custom controller mappings.
- `builder/snippets/*`: XML snippets for missing games.

Pull requests must not touch `whdload_db.json`.

## Settings Reference

Settings files live in `builder/settings/`. Most files are plain text lists keyed by **subpath** (the game directory inside the archive, shared across all versions of that game). Put one subpath per line.

### Flag Files (One Subpath Per Line)

| File | Effect |
|---|---|
| `Chipset_AGA.txt` | Set chipset to AGA. |
| `Chipset_FastCopper.txt` | Set fast copper (Amiberry currently ignores this). |
| `Chipset_ForceNTSC.txt` | Force NTSC video mode. |
| `Chipset_ImmediateBlitter.txt` | Set blitter mode to immediate. |
| `Control_CD32.txt` | Set CD32 game pad on both port 0 and port 1. |
| `Control_Port0_CD32.txt` | Set CD32 game pad on port 0. |
| `Control_Port0_Mouse.txt` | Set mouse on port 0 and make mouse the primary control. |
| `Control_Port1_CD32.txt` | Set CD32 game pad on port 1. |
| `Control_Port1_Mouse.txt` | Set mouse on port 1. |
| `CPU_ClockSpeed_7.txt` | Set CPU clock to 7 MHz. |
| `CPU_ClockSpeed_14.txt` | Set CPU clock to 14 MHz. |
| `CPU_ClockSpeed_25.txt` | Set CPU clock to 25 MHz. |
| `CPU_ClockSpeed_28.txt` | Set CPU clock to 28 MHz. |
| `CPU_ClockSpeed_Max.txt` | Set CPU clock to maximum. |
| `CPU_CycleExact.txt` | Enable cycle-exact CPU mode. |
| `CPU_ForceJIT.txt` | Enable JIT compilation. |
| `CPU_Model_68000.txt` | Set CPU model to 68000. |
| `CPU_Model_68010.txt` | Set CPU model to 68010. |
| `CPU_Model_68020.txt` | Set CPU model to 68020. |
| `CPU_Model_68040.txt` | Set CPU model to 68040. |
| `CPU_NoCompatible.txt` | Disable CPU compatible mode. |
| `Memory_Z3Ram_1.txt` | Add 1 MB Zorro III RAM; turns off 24-bit addressing. |
| `Memory_Z3Ram_2.txt` | Add 2 MB Zorro III RAM; turns off 24-bit addressing. |
| `Memory_Z3Ram_4.txt` | Add 4 MB Zorro III RAM; turns off 24-bit addressing. |
| `Memory_Z3Ram_8.txt` | Add 8 MB Zorro III RAM; turns off 24-bit addressing. |
| `Memory_Z3Ram_16.txt` | Add 16 MB Zorro III RAM; turns off 24-bit addressing. |
| `Memory_Z3Ram_32.txt` | Add 32 MB Zorro III RAM; turns off 24-bit addressing. |
| `Memory_Z3Ram_64.txt` | Add 64 MB Zorro III RAM; turns off 24-bit addressing. |
| `Memory_Z3Ram_128.txt` | Add 128 MB Zorro III RAM; turns off 24-bit addressing. |
| `Screen_Height_400.txt` | Force screen height to 400. |
| `Screen_Height_432.txt` | Force screen height to 432. |
| `Screen_Height_480.txt` | Force screen height to 480. |
| `Screen_Height_512.txt` | Force screen height to 512. |
| `Screen_Height_524.txt` | Force screen height to 524. |
| `Screen_Height_540.txt` | Force screen height to 540. |
| `Screen_Height_568.txt` | Force screen height to 568. |
| `Screen_NoCenter_H.txt` | Disable horizontal screen centering. |
| `Screen_NoCenter_V.txt` | Disable vertical screen centering. |
| `Screen_Width_640.txt` | Force screen width to 640 (default is 720). |
| `Screen_Width_704.txt` | Force screen width to 704 (default is 720). |
| `WHD_Libraries.txt` | Indicate the game requires external WHDLoad libraries. |

### Value Files (`key value`)

Lines in these files contain two tokens separated by whitespace: `<key> <value>`.

| File | Key Type | Value | Effect |
|---|---|---|---|
| `Screen_Offset_H.txt` | subpath | Integer `-60` to `60` | Horizontal pixel offset; disables horizontal centering. |
| `Screen_Offset_V.txt` | subpath | Integer `-20` to `20` | Vertical pixel offset; disables vertical centering. |
| `WHD_DefaultSlave.txt` | archive | Slave filename | Default slave to execute for the archive. |
| `WHD_DataPath.txt` | archive, or `archive/slave` | Directory name | Data directory expected by the slave. |

An archive key is the archive filename without `.lha`. Some filenames belong to more than one archive (different SHA1s); use the archive's SHA1 as the key to target only one of them. A SHA1 key wins over a filename key, and the triage bot picks the SHA1 key automatically when the filename is shared.

### Builder-Only Files

| File | Format | Description |
|---|---|---|
| `WHD_Longname_Fixes.txt` | `generated name\|fixed name` | Name overrides used only by the self-hosted LHA scanner (`builder/build_db.py`). Upstream XML provides names during normal sync. |

### Exclusive Groups

A game subpath may appear in at most one file in each of these groups:

- **Screen height**: `Screen_Height_*.txt` (if none match, auto-height is enabled)
- **Screen width**: `Screen_Width_*.txt` (default is 720)
- **CPU clock**: `CPU_ClockSpeed_*.txt`
- **CPU model**: `CPU_Model_*.txt`
- **Z3 RAM**: `Memory_Z3Ram_*.txt`
- **Port 0 control**: `Control_Port0_Mouse.txt`, `Control_Port0_CD32.txt`
- **Port 1 control**: `Control_Port1_Mouse.txt`, `Control_Port1_CD32.txt`

### Automatic Rules and Hardware Inheritance

The converter applies these rules before settings files:
- Archives containing `_AGA` or `_CD32` in the filename are set to AGA chipset.
- Archives containing `_CD32` in the filename use CD32 pads on both ports.
- Archives containing `NTSC` in the filename are set to NTSC mode.
- Upstream hardware `chipset` and `cpu` values are preserved unless an explicit settings file overrides them.
- All other hardware keys (blitter, clock, JIT, centering, screen size, offsets, RAM, ports) are fully determined by settings files.

## Custom Controller Mappings

Place custom mapping files in `builder/customcontrols/<subpath>`. The filename must match the game's subpath.

Contents must follow the format Amiberry writes to `.uae` configuration files:

```text
joyport1_amiberry_custom_none_b=Joy2 Up
joyport1_amiberry_custom_none_x=Space
```

Rules:
- Lines must match `^joyport[0-3]_amiberry_custom_(axis_)?(none|hotkey)_[a-z0-9_]+=.+$`.
- An empty file is valid. It clears any controller mappings inherited from upstream for that subpath.

## Adding Missing Games (Snippets)

If an archive is missing from the database, add a snippet file under `builder/snippets/`.

Snippet files contain one or more bare `<game>` XML elements matching upstream format:

```xml
<game filename="DevilsTemple_v3.0_1222" sha1="1ded50d02c3ec51467f30f21fea3019edab00b5d">
	<name>Devils Temple</name>
	<subpath>DevilsTemple</subpath>
	<variant_uuid>2e0b87ca-1083-5709-bd80-e46242de331b</variant_uuid>
	<slave_count>1</slave_count>
	<slave_default>DevilsTemple.Slave</slave_default>
	<slave_libraries>False</slave_libraries>
	<slave number="1">
		<filename>DevilsTemple.Slave</filename>
		<datapath>data</datapath>
		<custom></custom>
	</slave>
	<hardware>
		CHIPSET=AGA
		PRIMARY_CONTROL=JOYSTICK
		PORT0=JOY
		PORT1=JOY
		SCREEN_AUTOHEIGHT=TRUE
		SCREEN_CENTERH=SMART
		SCREEN_CENTERV=SMART
	</hardware>
</game>
```

See `builder/snippets/DevilsTemple` for a reference file.

Snippets are matched by SHA1. The converter adds new entries or replaces matching entries from upstream, then applies all settings and custom controls on top.

## Duplicate Rules

- **Issues**: One issue per archive. If an open issue already targets the same archive, the triage bot flags it with the `duplicate` label.
- **Settings files**: One entry per game subpath or filename per file. Duplicate lines fail lint checks.
- **Exclusive groups**: A game cannot appear in multiple files of an exclusive group.
- **Database output**: Every entry must have a unique SHA1. The converter keeps the last entry if duplicate SHA1s appear in input data, and lint checks fail if duplicates remain.

## Continuous Integration Checks

The validation workflow (`.github/workflows/validate.yml`) runs on every pull request touching `builder/**`, `converter/**`, `schema/**`, or `whdload_db.json`.

CI checks:
1. **Rejects direct database edits**: Pull requests modifying `whdload_db.json` fail immediately.
2. **Builds database**: Builds base and PR databases from the latest upstream XML using `converter/xml_to_json.py`.
3. **Lints overrides and schema**: Runs `converter/check_overrides.py`:
   - Unknown file names in `builder/settings/`.
   - Duplicate lines or multi-word lines in list files.
   - Conflicts across exclusive groups.
   - Malformed value lines or offsets outside valid ranges.
   - Slaves listed in `WHD_DefaultSlave.txt` or `WHD_DataPath.txt` missing from the archive.
   - Invalid syntax in `builder/customcontrols/` files.
   - Duplicate SHA1 values in the generated database.
   - Schema conformance against `schema/whdload_db.schema.json`.
4. **Reports entry changes**: Generates a Markdown diff with `converter/diff_db.py` and writes it to the GitHub Actions job summary. Check the summary tab of the PR run to inspect all added, removed, or modified entries.

## Local Testing

Requirements:
- Python 3.10+
- `pip install jsonschema` (for schema verification)

Commands:

```bash
# 1. Download upstream XML
curl -fsSL -o whdload_db.xml https://raw.githubusercontent.com/HoraceAndTheSpider/Amiberry-XML-Builder/master/whdload_db.xml

# 2. Build the database with local overrides
python3 converter/xml_to_json.py whdload_db.xml out.json --report report.md

# 3. Check overrides and validate schema
python3 converter/check_overrides.py out.json --schema schema/whdload_db.schema.json

# 4. Compare output against the committed database
python3 converter/diff_db.py whdload_db.json out.json
```

## Maintainer Workflow

### Triaging Issues

When an issue is opened with the `game-update` label:
- `.github/workflows/triage.yml` runs `converter/triage_issue.py`.
- The bot looks up the archive by SHA1, falling back to filename.
- The bot posts or updates a comment with:
  - Current database entry details.
  - Proposed file edits in `builder/settings/` and `builder/customcontrols/`.
  - Resulting hardware configuration.
  - Other archives sharing the same subpath that will be affected.
- If another open issue targets the same archive, the bot adds the `duplicate` label.

### Applying an Issue

Maintainers apply accepted changes locally:

```bash
python3 converter/triage_issue.py --issue <N> --apply
```

This writes the settings and custom controller files directly. Commit the changes on a branch and open a pull request with `Fixes #N` in the description.

## How Updates Reach Amiberry Users

1. **Upstream sync**: Horace's builder scans new archives every 1–3 days. This repository runs `.github/workflows/sync.yml` daily at 08:00 UTC and on pushes to `main` touching builder, converter, or schema files.
2. **Publication**: The sync workflow commits updated `whdload_db.json` to `main` and deploys it to GitHub Pages (`https://db.amiberry.com/whdload_db.json`).
3. **Manual user update**: Inside Amiberry, click **Update WHDBooter files** in the **Paths** panel (or launch Amiberry with `--download-whdboot`). Amiberry downloads `whdload_db.json`, backing up the previous copy to `game-data/whdload_db.bak`.
4. **Bundled release update**: Each Amiberry release bundles a copy of `whdload_db.json` refreshed at release time. Starting with the next Amiberry release, Amiberry replaces an older user database with the newer bundled copy at startup, retaining a backup file.
5. **Runtime lookup**: When launching a game, Amiberry matches the archive SHA1 first. If the SHA1 is not found, Amiberry falls back to the last entry matching the archive filename.
