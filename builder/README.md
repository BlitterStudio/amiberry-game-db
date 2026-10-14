# Amiberry Game Database Builder

Scans WHDLoad LHA archives and builds the `whdload_db.json` game database.

> **Not used by the published database.** `whdload_db.json` on `main` is built by `.github/workflows/sync.yml` from Horace's XML (see [CONTRIBUTING.md](../CONTRIBUTING.md)). The cron job below commits `whdload_db.json` too, and the next sync run would overwrite it. To switch to this builder, change `sync.yml` first. Known differences from the current output:
> - Game names are formatted differently (`Pinball Illusions AGA` instead of `Pinball Illusions [AGA]`, `Battle Squadron NTSC` instead of `Battle Squadron (NTSC)`).
> - `cpu: 68020` is added from slave headers.
>
> Checked against 18 archives; hardware, slaves and default slaves otherwise match.

## Quick Start

### 1. Install dependencies

```bash
cd builder
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run a full build

```bash
python3 build_db.py --scandir /path/to/your/lha/games --output ../whdload_db.json --full-refresh
```

### 3. Run an incremental update

After the first full build, subsequent runs skip unchanged files (by SHA1):

```bash
python3 build_db.py --scandir /path/to/your/lha/games --output ../whdload_db.json --existing ../whdload_db.json
```

## Command Line Options

| Flag | Description |
|------|-------------|
| `--scandir`, `-s` | Directory containing WHDLoad LHA files (scanned recursively) |
| `--output`, `-o` | Output JSON file (default: `whdload_db.json`) |
| `--builder-dir`, `-d` | Directory containing `settings/` and `customcontrols/` (default: script directory) |
| `--existing`, `-e` | Path to existing database for incremental updates |
| `--full-refresh`, `-n` | Force full rebuild, ignore existing database |

## Setup on TrueNAS (Cron Job)

### One-time setup

```bash
# Clone the repo
cd /mnt/pool/tools  # or wherever you keep scripts
git clone https://github.com/BlitterStudio/amiberry-game-db.git
cd amiberry-game-db/builder

# Create virtual environment
python3 -m venv venv
# TrueNAS defaults to csh/tcsh — use bash first:
bash
source venv/bin/activate
# (or if staying in csh: source venv/bin/activate.csh)
pip install -r requirements.txt
```

### Create the update script

Save as `/mnt/pool/tools/amiberry-game-db/update_db.sh`:

```sh
#!/usr/bin/env sh
set -eu

REPO_DIR="/mnt/pool/tools/amiberry-game-db"
LHA_DIR="/mnt/pool/data/amiga/games"  # adjust to your LHA path
DB_FILE="$REPO_DIR/whdload_db.json"

cd "$REPO_DIR"

# Pull latest settings/customcontrols from repo
git pull --ff-only

# Activate venv and run builder
. builder/venv/bin/activate
python3 builder/build_db.py \
    --scandir "$LHA_DIR" \
    --output "$DB_FILE" \
    --existing "$DB_FILE" \
    --builder-dir builder

# Commit and push if changed
if ! git diff --quiet "$DB_FILE" 2>/dev/null; then
    GAME_COUNT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["game_count"])' "$DB_FILE")
    git add "$DB_FILE"
    git commit -m "sync: update WHDLoad database (${GAME_COUNT} games)"
    git push
    echo "Database updated and pushed"
else
    echo "No changes detected"
fi
```

```bash
chmod +x /mnt/pool/tools/amiberry-game-db/update_db.sh
```

### Add the cron job

In TrueNAS UI: **Tasks → Cron Jobs → Add**

| Field | Value |
|-------|-------|
| Description | Update Amiberry Game DB |
| Command | `/mnt/pool/tools/amiberry-game-db/update_db.sh` |
| Run As User | Your user (needs git push access) |
| Schedule | `0 6 * * *` (daily at 6 AM, or adjust) |

Or via CLI:

```bash
crontab -e
# Add:
0 6 * * * /mnt/pool/tools/amiberry-game-db/update_db.sh >> /var/log/amiberry-db-update.log 2>&1
```

### Git authentication for push

The cron job needs push access to the repo. Options:

1. **SSH key** (recommended): Add a deploy key with write access to the repo
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/amiberry-game-db -N ""
   # Add the public key to repo Settings → Deploy keys (check "Allow write access")
   # Configure git to use it:
   git config core.sshCommand "ssh -i ~/.ssh/amiberry-game-db"
   ```

2. **Personal access token**: Create a fine-grained PAT with Contents write access
   ```bash
   git remote set-url origin https://x-access-token:YOUR_TOKEN@github.com/BlitterStudio/amiberry-game-db.git
   ```

## Data Files

Both `build_db.py` and the daily converter (`converter/xml_to_json.py`) share override logic in `converter/overrides.py`. Settings and custom controls apply to every database entry on every run, not only newly scanned archives.

### `settings/`

Override files that apply hardware settings to games. Most files are plain text lists keyed by subpath (one game per line); value files use `<key> <value>`.

See the [Settings Reference in CONTRIBUTING.md](../CONTRIBUTING.md#settings-reference) for the full list of supported settings files, value file formats, and exclusive groups.

### `customcontrols/`

Per-game controller mapping files named by game subpath. Contents are `amiberry_custom` configuration lines. An empty file clears upstream mappings.

### `snippets/`

XML snippet files for games that cannot be auto-scanned or are missing from upstream. These are parsed and merged into the database by SHA1.

## Migrating from Horace's Builder

This builder is a rewrite of [HoraceAndTheSpider's Amiberry-XML-Builder](https://github.com/HoraceAndTheSpider/Amiberry-XML-Builder). Key differences:

- Outputs JSON directly without an XML intermediate.
- Self-contained slave header parser (no external `whdload_slave` module).
- Incremental updates by SHA1 rather than filename matching.
- Shared override engine: `build_db.py` and `converter/xml_to_json.py` use the same rules in `converter/overrides.py`.
- Settings and custom controls apply to every entry on every run, rather than only newly scanned archives.
- The LHA builder preserves AGA and 68020 hardware requirements parsed from slave headers unless explicitly overridden.
- Settings and custom controls use the same file formats as Horace's builder.
