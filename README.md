# Amiberry WHDLoad Game Database

Structured game compatibility database for [Amiberry](https://github.com/BlitterStudio/amiberry), the Amiga emulator.

Contains hardware settings, controller mappings, and WHDLoad slave metadata for **11,000+** games.

## Download

The database is available as a JSON file, served via GitHub Pages:

```
https://db.amiberry.com/whdload_db.json
```

## Format

The database uses JSON with structured, typed fields:

```json
{
  "schema_version": 2,
  "game_count": 11041,
  "games": [
    {
      "filename": "Turrican2_v1.3_Psygnosis",
      "sha1": "abc123...",
      "name": "Turrican II",
      "subpath": "Turrican2",
      "slave_default": "Turrican2.slave",
      "slaves": [
        {
          "filename": "Turrican2.slave",
          "datapath": "data",
          "custom_fields": []
        }
      ],
      "hardware": {
        "primary_control": "joystick",
        "port0": "joy",
        "port1": "joy",
        "screen_autoheight": true,
        "screen_centerh": "smart",
        "screen_centerv": "smart"
      }
    }
  ]
}
```

See [`schema/whdload_db.schema.json`](schema/whdload_db.schema.json) for the full JSON Schema.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for full instructions.

- **Suggest settings**: Use the [Game Settings Update](../../issues/new?template=game-settings.yml) issue template.
- **Direct contributions**: Open a pull request modifying files under `builder/settings/`, `builder/customcontrols/`, or `builder/snippets/`.

Do not edit `whdload_db.json` directly. It is generated automatically, and CI rejects pull requests modifying it.

## Building from Source

The database can be rebuilt from WHDLoad LHA archives using the included builder. See [`builder/README.md`](builder/README.md) for setup instructions, including automated cron job configuration.

## Data Source

The database is built in layers:
1. **Base layer**: downloaded from [HoraceAndTheSpider's Amiberry-XML-Builder](https://github.com/HoraceAndTheSpider/Amiberry-XML-Builder) `whdload_db.xml`.
2. **Snippets**: XML entries in `builder/snippets/` added or replaced by this repository.
3. **Overrides**: settings in `builder/settings/` and controller mappings in `builder/customcontrols/` applied to every entry.

The pipeline rebuilds `whdload_db.json` daily at 08:00 UTC and on every merge to `main` touching builder, converter, or schema files. A self-hosted builder that scans LHA archives directly (`builder/build_db.py`) is also included.

## License

Database content: community-contributed game compatibility data.
Tooling: MIT License.
