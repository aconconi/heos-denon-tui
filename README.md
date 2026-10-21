# HEOS CLI and TUI (unofficial)

Command-line and terminal-UI clients for Denon HEOS devices, plus a dashboard for Denon AV receivers.

> Unofficial project. "Denon" and "HEOS" are trademarks of their respective owners; this project is
> not affiliated with or endorsed by them.

It is a small [uv](https://docs.astral.sh/uv/) workspace. The clients are built on two existing
libraries rather than re-implementing the protocols:

| Package | What it is |
|---|---|
| [`packages/heos-cli`](packages/heos-cli) | `heos-cli`: scriptable command-line client (Typer + Rich) |
| [`packages/heos-tui`](packages/heos-tui) | `heos-tui`: full-screen terminal app (Textual), including the Amp dashboard |
| [`packages/heos-discovery`](packages/heos-discovery) | SSDP discovery of HEOS devices (neither library provides it) |

Libraries used: [`pyheos`](https://github.com/andrewsayre/pyheos) for the HEOS CLI protocol
(Apache-2.0) and [`denonavr`](https://github.com/ol-iver/denonavr) for receiver control (MIT).
The clients depend only on those and on each other's shared package, never on one another.

## Status

Developed against one Denon AV receiver with HEOS built in. The automated tests use in-process
fake devices, so they check behaviour but not every quirk of real hardware. Expect rough edges,
especially around browsing streaming services and the receiver-specific features listed below.

## Requirements

- Python 3.11 or newer and [uv](https://docs.astral.sh/uv/)
- A HEOS device on the same network (the CLI port 1255 must be reachable)

## Setup

```bash
uv sync --all-packages
```

## `heos-cli`

Global options go before the command. `-H/--host` is the device address (or set `HEOS_HOST`; if
omitted, the first device found by discovery is used), `-p/--player` is a room name or id (or set
`HEOS_PLAYER`), and `--json` gives machine-readable output.

```bash
uv run heos-cli discover                    # find devices
export HEOS_HOST=192.168.1.50
uv run heos-cli players                     # list rooms
uv run heos-cli -p Kitchen status           # state, volume, now playing
uv run heos-cli -p Kitchen volume 30
uv run heos-cli favorites                   # then: heos-cli play-preset 2
uv run heos-cli sources                     # then: heos-cli browse <sid> [<cid>]
uv run heos-cli --json players
```

Commands: `players`, `status`, `play`, `pause`, `stop`, `next`, `prev`, `volume`, `up`, `down`,
`mute`, `mode`, `quickselect`, `groups` / `group …`, `queue …`, `sources`, `browse`, `favorites`,
`inputs`, `search-criteria`, `search`, `play-station`, `play-preset`, `play-input`, `play-url`,
`add`, `rename-playlist`, `delete-playlist`, `discover`, `watch`, `account`, `signin`, `signout`,
`check-update`, `reboot`, and `raw` (send any HEOS command, for debugging; it uses a pyheos
internal and may need updating after a pyheos upgrade). Run `heos-cli COMMAND --help` for details.

`signin` prompts for the password (or reads `HEOS_PASSWORD`); it is never taken as an argument.

## `heos-tui`

```bash
uv run heos-tui -H 192.168.1.50                      # or set HEOS_HOST; omit to discover
uv run heos-tui -H 192.168.1.50 --avr-host 192.168.1.60   # amp at another address (HEOS_AVR_HOST)
```

Tabs: **Rooms** `1`, **Queue** `2`, **Browse** `3`, and **Amp** `4`. The Amp tab appears when a Denon
AVR answers at `--avr-host`, or else at the HEOS device's own address (the probe is silent if it
is not an AVR). Mouse works everywhere.

| Key | Action |
|---|---|
| `Space` `n` `p` | play/pause, next, previous |
| `+` `-` `m` | volume up/down, mute (the amp's, while the Amp tab is active) |
| `s` `r` | shuffle, cycle repeat |
| `[` `]` | previous/next room, from any tab |
| `o` | options for the playing media (thumbs up/down, add station to Favorites) |
| `l` | HEOS account sign-in/out (services linked to the account appear under Browse) |
| `1`–`4` / `q` | switch tab / quit |

Queue: `Enter` plays, `x`/`Delete` removes, `c` clears, `w` saves as a playlist.
Browse: `Enter` opens or plays, `Backspace`/`Esc` goes back, `/` searches the current source, `a`
adds to the queue.

### Amp tab

An interactive dashboard: `↑`/`↓` or `Tab` move between controls, `Space`/`Enter` toggles,
`←`/`→` adjust a value, clicks work too.

- **Receiver**: power, mute, input, sound mode, volume.
- **Quick Select**: the four presets, named after your HEOS Quick Select names when available.
  Recalling one re-reads every value on screen. A preset is an action, so no "current preset" is shown.
- **Audyssey**: MultiEQ, Dynamic EQ, Reference Level Offset, Dynamic Volume, LFC.
- **Tone and dialog**: tone control, bass, treble, dialog enhancer.
- **AVR Info**: audio format, sample rate, input/output video, HDMI details.
- **Telnet events**: a live log of what the receiver reports, each line explained where the code is known.

Limitations worth knowing:

- Dialog enhancer and the live event log need the receiver's telnet connection, and a receiver
  allows only one telnet client. Without it the tab falls back to polling every 10 seconds.
- AVR Info uses the same requests as Denon's own app, through internals of `denonavr`, and the
  response layout is not documented; unrecognised fields show as `-`. Denon reports a sampling
  frequency, not a bit rate.
- Surround Level Compensation is not supported (neither `denonavr` nor this project knows its command).
- Bass and treble are shown relative to 6, assuming 6 is the flat position of the receiver's 0–12 scale.

## Layout and development

```
packages/
  heos-discovery/   SSDP discovery
  heos-cli/         the CLI (commands/ holds one module per area)
  heos-tui/         the TUI (app, widgets, Amp dashboard, controls, telnet code table)
```

```bash
uv run pytest        # all packages
uv run ruff check packages
uv run ruff format packages
```

The tests drive the real app and CLI against in-process fake devices connected through a socket
pair, so they need no network and no TCP ports.

## Protocol documents

The HEOS CLI protocol specification is vendor documentation and is not included in this repository.

## License

No license has been chosen yet.
