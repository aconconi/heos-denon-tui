"""Human and JSON rendering."""

import dataclasses
import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from pyheos import (
    HeosGroup,
    HeosNowPlayingMedia,
    HeosPlayer,
    Media,
    MediaItem,
    MediaMusicSource,
    QueueItem,
    SearchCriteria,
)
from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


def to_jsonable(data: Any) -> Any:
    if dataclasses.is_dataclass(data) and not isinstance(data, type):
        return {f.name: to_jsonable(getattr(data, f.name)) for f in dataclasses.fields(data)}
    if isinstance(data, Mapping):
        return {str(k): to_jsonable(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [to_jsonable(i) for i in data]
    return data


def emit(state: Any, data: Any, render: Callable[[Any], None]) -> None:
    """Print ``data`` as JSON when --json is set, otherwise via ``render``."""
    if state.json:
        print(json.dumps(to_jsonable(data), indent=2, default=str))
    else:
        render(data)


def players_table(players: Iterable[HeosPlayer]) -> None:
    t = Table("PID", "Name", "Model", "Version", "Network", "State", "Group", header_style="bold")
    for p in players:
        state = p.state.value if p.state else "-"
        t.add_row(
            str(p.player_id), p.name, p.model, p.version or "", p.network.value, state,
            str(p.group_id or "-"),
        )  # fmt: skip
    console.print(t)


def groups_table(groups: Iterable[HeosGroup], names: Mapping[int, str]) -> None:
    groups = list(groups)
    if not groups:
        console.print("No groups.")
        return
    t = Table("GID", "Name", "Members", "Volume", header_style="bold")
    for g in groups:
        members = ", ".join(
            f"{names.get(pid, pid)}{' (leader)' if pid == g.lead_player_id else ''}"
            for pid in g.member_player_ids
        )
        t.add_row(str(g.group_id), g.name, members, f"{g.volume}{' (muted)' if g.is_muted else ''}")
    console.print(t)


def sources_table(sources: Iterable[MediaMusicSource]) -> None:
    t = Table("SID", "Name", "Type", "Available", "Account", header_style="bold")
    for s in sources:
        t.add_row(
            str(s.source_id), s.name, s.type.value, "yes" if s.available else "no",
            s.service_username or "",
        )  # fmt: skip
    console.print(t)


def media_table(items: Iterable[Media], start: int = 0) -> None:
    """Items from browse/search; the CID/MID columns are what you pass to other commands."""
    t = Table(
        "#", "Type", "Name", "Artist / Album", "B", "P", "SID", "CID", "MID", header_style="bold"
    )
    for i, m in enumerate(items, start):
        item = m if isinstance(m, MediaItem) else None
        detail = " / ".join(x for x in (item.artist, item.album) if x) if item else ""
        browsable = isinstance(m, MediaMusicSource) or bool(item and item.browsable)
        t.add_row(
            str(i), m.type.value, m.name, detail, "y" if browsable else "",
            "y" if item and item.playable else "", str(m.source_id),
            (item.container_id or "") if item else "", (item.media_id or "") if item else "",
        )  # fmt: skip
    console.print(t)


def queue_table(items: Iterable[QueueItem]) -> None:
    t = Table("QID", "Song", "Artist", "Album", header_style="bold")
    for q in items:
        t.add_row(str(q.queue_id), q.song, q.artist, q.album)
    console.print(t)


def criteria_table(criteria: Iterable[SearchCriteria]) -> None:
    t = Table("ID", "Name", "Wildcard", "Playable", header_style="bold")
    for c in criteria:
        t.add_row(
            str(c.criteria_id), c.name, "yes" if c.wildcard else "no", "yes" if c.playable else "no"
        )
    console.print(t)


def now_playing_line(np: HeosNowPlayingMedia) -> str:
    parts = [np.song or np.station or "(nothing)"]
    if np.artist:
        parts.append(f"by {np.artist}")
    if np.album:
        parts.append(f"on {np.album}")
    if np.station and np.song:
        parts.append(f"[{np.station}]")
    return " ".join(parts)
