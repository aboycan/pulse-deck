# PulseDeck user guide

## The player window

The display shows album artwork, the title, artist and album, the elapsed
time and the file format (codec, sample rate, bitrate, channels). It also
shows the playback state and whether shuffle and repeat are on.

- Click the time to switch between elapsed and remaining time.
- Click the artwork to view it full size.
- Click anywhere on the seek bar to jump to that point, or drag the handle.
- Hold the fast-forward or rewind button to keep skipping. The step size is
  set in *Settings > Audio*.
- Previous restarts the current track if more than 3 seconds have played.
  Press it again to go to the previous track.
- Repeat cycles through off, all and one. Repeat-one only replays the track
  when it ends; pressing Next still moves on.
- The buttons under the transport controls open the Playlist, Equalizer,
  Library and Info panels. There are also buttons for always on top,
  compact mode and Settings.
- Drop files, folders or playlists onto the window to add them and start
  playing.

Each panel is a separate window. PulseDeck remembers where each one was,
how big it was and whether it was open.

## Playlists

- The left column lists your playlists. Double-click one to play it, drag to
  reorder them, and right-click for Play, Shuffle, Rename, Duplicate, Export,
  Clear and Delete.
- The track list supports drag and drop to reorder. You can also use the ▲ ▼
  buttons or Alt+Up and Alt+Down. Press Delete to remove the selected
  tracks, and drop files from your file manager or the Library onto it.
- Click a column header to sort by that column. Click again to reverse the
  order.
- In the search box, plain words match the title, artist, album or genre.
  Use `artist:`, `album:`, `genre:` or `year:` to search one field, and put
  quotes around phrases.
- Missing files are shown crossed out. *More > Remove missing files* removes
  them, and *More > Find moved files…* searches your library folders, plus
  a folder you choose, for files with the same name.
- *File > Save Playlist* and *Export* write M3U8, M3U or PulseDeck JSON.
  Playlists are saved relative to the playlist file where possible, so they
  still work if you move the whole folder.

## Equalizer

- **Enabled:** when unchecked, the audio isn't processed at all.
- **Bypass:** a quick A/B switch to hear the original audio. Your settings
  are kept.
- **Auto preamp:** lowers the level by the amount of the largest boost so
  boosted bands can't clip. The status line shows the result.
- **Preamp:** manual level from -12 to +12 dB.
- **Reset:** sets every band and the preamp to 0 dB. Double-click a single
  slider to reset just that one.
- **Presets:** choose a built-in preset or one of your own. *Save As…* stores
  the current curve. Rename and Delete only work on presets you made.
  *Import…* accepts one preset or a bundle (`{"presets": [...]}`), and
  *Export…* writes a preset file you can share.

There is also a limiter at the end of the chain (*Settings > Audio > Clip
protection*) as a final safety net.

## Library

- *Add Folder…* adds a folder and scans it in the background. Use the
  *Folders* menu to rescan a folder or remove it. Removing a folder deletes
  nothing on disk.
- The tree on the left has the views (All Music, Favourites, Recently
  Played, Most Played, Recently Added) and browse lists for artists,
  albums, genres and years. Right-click an artist or album for Play All,
  Add to Playlist, View Albums and View Information.
- Double-click a track to add it to the current playlist and play it. You
  can also drag tracks into the playlist editor.
- Choose which columns to show in *Settings > Library*.
- Scanning only reads your files. Files that haven't changed are skipped
  on rescans. Files that can't be read are listed when the scan finishes.

## Track information and tag editing

Open the Info panel, or right-click a song and choose *View Song
Information* or *Edit Metadata…*. Click *Edit Tags*, change the fields you
want, and click *Save*. PulseDeck writes the new tags to a temporary copy,
checks the copy, and then replaces the file. The audio data isn't touched.
The tags the file had before your first edit are kept, so *Restore
Original Tags…* can undo your changes at any time.

## Settings

| Tab | Options |
|---|---|
| General | Startup behaviour, session restore, minimize or close to tray, notifications, delete confirmations, single instance, clear history |
| Audio | Output device, equalizer on/off, default preset, crossfade (0 means gapless), gapless, normalization, ReplayGain mode and preamp, clip protection, speed, balance, seek step |
| Library | Default music folder, auto-rescan on startup, duplicate detection, visible columns |
| Interface | Theme, accent colour, font size, compact mode, always on top, which panels open at startup |
| Keyboard | Change any shortcut. Conflicts are flagged. *Restore Defaults* resets them all. |

Changes take effect immediately.

## Media keys and the tray

Play/Pause, Next, Previous and Stop media keys work while PulseDeck is
focused on every platform. They also work system-wide on Windows, on Linux
desktops that support MPRIS (GNOME, KDE, Xfce and others), and on macOS
when the optional `pyobjc-framework-MediaPlayer` package is bundled (the
official macOS builds include it).

The tray icon menu has playback controls. Click the icon to show or hide
PulseDeck, and middle-click it to play or pause.

## Where your data lives

| OS | Settings | Playlists, library, logs |
|---|---|---|
| Windows | `%APPDATA%\PulseDeck` | `%LOCALAPPDATA%\PulseDeck` |
| macOS | `~/Library/Application Support/PulseDeck` | `~/Library/Application Support/PulseDeck/Data` |
| Linux | `~/.config/pulsedeck` | `~/.local/share/pulsedeck` |

The artwork thumbnail cache can be deleted at any time.
