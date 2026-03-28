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

### Submit game settings

Use the [Game Settings Update](../../issues/new?template=game-settings.yml) issue template to submit or update settings for a game.

### Direct contributions

1. Fork this repo
2. Edit `whdload_db.json` (or add an override in `overrides/`)
3. Submit a PR — CI will validate the JSON against the schema

## Data Source

The database is automatically synced from [HoraceAndTheSpider's Amiberry-XML-Builder](https://github.com/HoraceAndTheSpider/Amiberry-XML-Builder) and converted from XML to structured JSON. The sync runs daily.

## License

Database content: community-contributed game compatibility data.
Tooling: MIT License.
