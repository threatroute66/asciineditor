# asciineditor

A command-line and GUI editor for [asciicast v2](https://docs.asciinema.org/manual/asciicast/v2/) (`.cast`) files — the recording format used by [asciinema](https://github.com/asciinema/asciinema).

**asciineditor** provides editing capabilities that are not built into asciinema, allowing you to split, join, cut, and change the playback speed of terminal recordings after they have been captured.

## Features

- **Split** — Split a recording into two files at a given timestamp or marker
- **Join** — Concatenate multiple recordings into a single file with configurable gaps
- **Cut** — Remove a section between two points (by timestamp or marker)
- **Speed** — Change playback speed of a specific section while keeping the rest unchanged
- **Add / Remove Markers** — Insert or delete named marker events in recordings
- **GUI with Terminal Playback** — Visual timeline, integrated terminal display with ANSI color rendering, and synchronized event list

## Installation

Requires Python 3.8+ (no external dependencies).

```bash
# Clone the repository
git clone https://github.com/threatroute66/asciineditor.git
cd asciineditor

# Install as a CLI tool
pip install -e .
```

This installs two commands:

| Command | Description |
|---------|-------------|
| `asciineditor` | CLI tool |
| `asciineditor-gui` | GUI application (tkinter) |

## CLI Usage

### Split

Split a recording at a timestamp or marker into two files.

```bash
# Split at 5 seconds
asciineditor split recording.cast --at 5.0

# Split at a named marker
asciineditor split recording.cast --at marker:chapter2

# Specify output file names
asciineditor split recording.cast --at 5.0 -o1 intro.cast -o2 rest.cast
```

### Join

Join multiple recordings into one.

```bash
# Join with default 0.5s gap
asciineditor join part1.cast part2.cast -o full.cast

# Join with custom gap
asciineditor join part1.cast part2.cast part3.cast -o full.cast --gap 1.0
```

### Cut

Remove a section between two points.

```bash
# Cut by timestamps
asciineditor cut recording.cast --start 3.0 --end 7.0 -o trimmed.cast

# Cut between named markers
asciineditor cut recording.cast --start marker:cut_start --end marker:cut_end -o trimmed.cast
```

### Speed

Change playback speed of a section. Events outside the section are unaffected.

```bash
# Speed up a section 2x
asciineditor speed recording.cast --start 2.0 --end 8.0 --factor 2.0 -o output.cast

# Slow down a section between markers
asciineditor speed recording.cast --start marker:slow_start --end marker:slow_end -f 0.5 -o output.cast
```

### Remove Markers

Remove marker events from a recording.

```bash
# Remove a specific marker by label
asciineditor remove-marker recording.cast --label section_start

# Remove marker at a specific timestamp
asciineditor remove-marker recording.cast --at 2.5

# Remove all markers
asciineditor remove-marker recording.cast --all
```

### Position Specifiers

All `--at`, `--start`, and `--end` arguments accept:

- **Seconds** — a numeric timestamp, e.g. `5.0`
- **Marker** — `marker:<label>` to reference the first marker event with that label

## GUI Usage

Launch the GUI:

```bash
asciineditor-gui
```

### Layout

```
+---------------------------------------------------------------+
| [Open] [Save As] [Undo]        [Join Files]                   |
+---------------------------------------------------------------+
| sample.cast | 80x24 | 10.00s | 13 events | 2 markers         |
+---------------------------------------------------------------+
| Timeline    [====|===m=====m====|========]                     |
+---------------------------------------------------------------+
| [Set Start] [Set End] [Clear]  [Play] [Stop] Speed: [==] 1.0x |
+---------------------------------------------------------------+
| [Split] [Cut] [Speed Up] [Slow Down] [Custom] [+Mkr] [-Mkr]  |
+---------------------------------------------------------------+
| Terminal Display          | Events                             |
| $ whoami                  | 0.5000  output  $ whoami           |
| user                      | 1.0000  output  user               |
| $ echo hello              | 2.0000  output  $ echo hello       |
| hello                     | 2.5000  marker  section_start      |
| $                         | 3.0000  output  hello               |
|                           | ...                                |
+---------------------------------------------------------------+
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+O` | Open file |
| `Ctrl+S` | Save As |
| `Ctrl+Z` | Undo |
| `Space` | Play / Pause |

### Workflow

1. **Open** a `.cast` file
2. **Play** the recording to preview it in the terminal display
3. **Click the timeline** to seek to any point (also renders the terminal at that moment)
4. Use **Set Start** / **Set End** to select a region on the timeline
5. Apply an operation: **Cut**, **Speed Up**, **Split**, etc.
6. **Undo** if needed (up to 30 levels)
7. **Save As** to write the result

## Setting Markers

Markers are special events in `.cast` files (event type `"m"`) that can be used as reference points for editing.

**During recording** — press `Ctrl+\` while recording with asciinema to insert a marker.

**After recording** — use the GUI's "Add Marker..." button, or manually add a line to the `.cast` file:

```json
[5.0, "m", "my_marker_label"]
```

## Credits

This project works with the [asciicast v2](https://docs.asciinema.org/manual/asciicast/v2/) file format created by [Marcin Kulik](https://github.com/ku1ik) as part of the [asciinema](https://asciinema.org) project.

- **asciinema** — [github.com/asciinema/asciinema](https://github.com/asciinema/asciinema)
- **Marcin Kulik** — [github.com/ku1ik](https://github.com/ku1ik)

asciineditor is an independent project and is not affiliated with or endorsed by the asciinema project.

## License

MIT
