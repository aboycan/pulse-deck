# Theme format

A PulseDeck theme is a JSON file. Put your own themes in the `themes` folder
inside your PulseDeck configuration directory (*Settings > Interface > Theme
Folder…* opens it):

| OS | Folder |
|---|---|
| Windows | `%APPDATA%\PulseDeck\themes` |
| macOS | `~/Library/Application Support/PulseDeck/themes` |
| Linux | `~/.config/pulsedeck/themes` |

Restart PulseDeck or reopen Settings to see new themes. A user theme with the
same `id` as a built-in theme replaces it.

## Example

```json
{
  "format": "pulsedeck-theme",
  "version": 1,
  "id": "midnight_orange",
  "name": "Midnight Orange",
  "radius": 4,
  "font_family": "",
  "colors": {
    "window": "#15161a", "panel": "#1d1f24", "base": "#111216", "alt_base": "#17181d",
    "text": "#e7e7ea", "muted": "#8b8d96", "accent": "#ff8a3d", "accent_text": "#1a0d03",
    "border": "#2c2e35", "highlight": "#4a2e1c", "display_bg": "#0d0d10", "display_text": "#ffb37a",
    "display_dim": "#9a6a48", "groove": "#2f3138", "danger": "#ff5c5c",
    "button": "#24262c", "button_hover": "#2e3038"
  }
}
```

## Fields

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique identifier (letters, digits, `_`). |
| `name` | no | Name shown in Settings. Defaults to `id`. |
| `radius` | no | Corner radius in pixels, 0-16 (default 4). |
| `font_family` | no | Font family name; empty uses the system font. |
| `colors` | yes | All keys below, each `#RRGGBB` or `#RRGGBBAA`. |

| Colour key | Used for |
|---|---|
| `window` | Window background |
| `panel` | Menus, headers, tabs |
| `base` / `alt_base` | Lists and tables (alternating rows), text fields |
| `text` / `muted` | Main and secondary text; icons use `text` |
| `accent` / `accent_text` | Highlights, slider fill, playing track, play button; text drawn on the accent |
| `border` | Outlines and separators |
| `highlight` | Selected rows and pressed buttons |
| `display_bg`, `display_text`, `display_dim` | The player "display" panel |
| `groove` | Slider and scrollbar tracks |
| `danger` | Warnings |
| `button` / `button_hover` | Buttons |

The user's custom accent colour (Settings > Interface) overrides `accent` and
computes a readable `accent_text` automatically.

Themes may not include images, so they cannot reproduce third-party skins.
Please don't publish themes that imitate a proprietary product's branding.
