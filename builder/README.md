# Amiberry Game Database Builder

Scans WHDLoad LHA archives and builds the `whdload_db.json` game database.

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

### `settings/`

Override files that apply hardware settings to games by subpath. One game name per line.

| File | Effect |
|------|--------|
| `Chipset_AGA.txt` | Force AGA chipset |
| `Chipset_ForceNTSC.txt` | Force NTSC mode |
| `Chipset_ImmediateBlitter.txt` | Enable immediate blitter |
| `Chipset_FastCopper.txt` | Enable fast copper |
| `Control_CD32.txt` | Use CD32 pad |
| `Control_Port0_Mouse.txt` | Primary control = mouse |
| `Control_Port1_Mouse.txt` | Port 1 = mouse |
| `CPU_ClockSpeed_25.txt` | Force 25 MHz CPU clock |
| `CPU_ClockSpeed_Max.txt` | Force max CPU speed |
| `CPU_CycleExact.txt` | Enable cycle-exact CPU |
| `CPU_ForceJIT.txt` | Enable JIT |
| `CPU_NoCompatible.txt` | Disable CPU compatible mode |
| `Memory_Z3Ram_16.txt` | Add 16 MB Z3 RAM |
| `Screen_Height_*.txt` | Force specific screen height |
| `Screen_Width_*.txt` | Force specific screen width |
| `Screen_NoCenter_H.txt` | Disable horizontal centering |
| `Screen_NoCenter_V.txt` | Disable vertical centering |
| `Screen_Offset_H.txt` | Set horizontal offset (format: `GameName value`) |
| `Screen_Offset_V.txt` | Set vertical offset (format: `GameName value`) |
| `WHD_DataPath.txt` | Override slave datapath (format: `ArchiveName value` or `ArchiveName/SlaveName value`) |
| `WHD_DefaultSlave.txt` | Override default slave (format: `ArchiveName SlaveName`) |
| `WHD_Libraries.txt` | Game needs external libraries |
| `WHD_Longname_Fixes.txt` | Override auto-generated game name |

### `customcontrols/`

Per-game controller mapping files. Filename = game subpath. Contents are `amiberry_custom` config lines.

### `snippets/`

XML snippet files for games that can't be auto-scanned (e.g., not in standard LHA format). These are parsed and merged into the database.

## Migrating from Horace's Builder

This builder is a rewrite of [HoraceAndTheSpider's Amiberry-XML-Builder](https://github.com/HoraceAndTheSpider/Amiberry-XML-Builder). Key differences:

- Outputs JSON directly (no XML intermediate)
- Self-contained slave header parser (no external `whdload_slave` module)
- Incremental updates by SHA1 (faster than filename matching)
- Settings and customcontrols are identical format — copy directly from Horace's repo
