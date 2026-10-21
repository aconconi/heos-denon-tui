"""Now-playing bar, queue table and browse/search panel."""

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from pyheos import (
    AddCriteriaType,
    HeosPlayer,
    Media,
    MediaItem,
    MediaMusicSource,
    PlayState,
    QueueItem,
)
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static

from .screens import ChoiceScreen, ConfirmScreen, PromptScreen

if TYPE_CHECKING:
    from .app import HeosTui

_STATE_ICON = {PlayState.PLAY: "▶", PlayState.PAUSE: "⏸", PlayState.STOP: "■"}


def state_icon(player: HeosPlayer) -> str:
    return _STATE_ICON.get(player.state, " ") if player.state else " "


def fmt_ms(ms: int) -> str:
    seconds = max(ms, 0) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


class NowPlayingBar(Static):
    """Persistent mini-player: track, progress and player status."""

    def show(self, player: HeosPlayer | None, width: int = 60, rooms: int = 1) -> None:
        text = Text()
        if player is None:
            text.append("No player selected", style="dim")
            self.update(text)
            return
        text.append(f"Room: {player.name}", style="bold cyan")
        if rooms > 1:
            text.append("   [ / ] switch room", style="dim")
        text.append("\n")
        np = player.now_playing_media
        title = np.song or np.station
        text.append(f"{state_icon(player)} {title or 'Nothing playing'}\n", style="bold")
        detail = " · ".join(x for x in (np.artist, np.album) if x)
        if np.station and np.song:
            detail = f"{detail} · {np.station}" if detail else np.station
        text.append(f"{detail}\n", style="dim")
        if np.duration:
            position = np.current_position or 0
            bar_width = max(10, width - 14)
            filled = min(bar_width, position * bar_width // np.duration)
            text.append(f"{fmt_ms(position)} ")
            text.append("━" * filled, style="green")
            text.append("─" * (bar_width - filled), style="dim")
            text.append(f" {fmt_ms(np.duration)}\n")
        else:
            text.append("\n")
        flags = [f"vol {player.volume}{' (muted)' if player.is_muted else ''}"]
        flags.append(f"shuffle {'on' if player.shuffle else 'off'}")
        flags.append(f"repeat {player.repeat.value.removeprefix('on_')}")
        text.append("  ".join(flags), style="cyan")
        self.update(text)


class QueueView(DataTable):
    BINDINGS = [
        Binding("delete,x", "remove", "Remove"),
        Binding("c", "clear", "Clear queue"),
        Binding("w", "save", "Save as playlist"),
    ]

    def __init__(self) -> None:
        super().__init__(cursor_type="row", zebra_stripes=True, id="queue-table")

    @property
    def heos(self) -> "HeosTui":
        return cast("HeosTui", self.app)

    def on_mount(self) -> None:
        self.add_column("", key="mark", width=2)
        self.add_column("Title", key="song")
        self.add_column("Artist", key="artist")
        self.add_column("Album", key="album")

    def load(self, items: list[QueueItem], current_qid: int | None) -> None:
        cursor = self.cursor_row
        self.clear()
        for q in items:
            mark = "▶" if q.queue_id == current_qid else ""
            self.add_row(mark, Text(q.song), Text(q.artist), Text(q.album), key=str(q.queue_id))
        if items:
            self.move_cursor(row=min(cursor, len(items) - 1))

    def mark_current(self, current_qid: int | None) -> None:
        for row_key in list(self.rows):
            self.update_cell(row_key, "mark", "▶" if row_key.value == str(current_qid) else "")

    def selected_qid(self) -> int | None:
        if not self.row_count:
            return None
        return int(self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value)

    @work
    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        player, qid = self.heos.player, self.selected_qid()
        if player and qid is not None:
            await self.heos.guard(player.play_queue(qid))

    @work
    async def action_remove(self) -> None:
        player, qid = self.heos.player, self.selected_qid()
        if player and qid is not None:
            await self.heos.guard(player.remove_from_queue([qid]))
            await self.heos.reload_queue()

    @work
    async def action_clear(self) -> None:
        player = self.heos.player
        if player and await self.app.push_screen_wait(ConfirmScreen("Clear the whole queue?")):
            await self.heos.guard(player.clear_queue())
            await self.heos.reload_queue()

    @work
    async def action_save(self) -> None:
        player = self.heos.player
        if player is None:
            return
        name = await self.app.push_screen_wait(PromptScreen("Save queue as playlist named:"))
        if name:
            await self.heos.guard(player.save_queue(name))
            self.app.notify(f"Saved playlist {name!r}")


@dataclass
class Level:
    title: str
    source_id: int | None
    items: list[Media] = field(default_factory=list)
    total: int = 0
    search_container: str | None = None  # container prefix + text, for tracks found by search


def _browsable(item: Media) -> bool:
    return isinstance(item, MediaMusicSource) or (isinstance(item, MediaItem) and item.browsable)


def _playable(item: Media) -> bool:
    return isinstance(item, MediaItem) and item.playable


class BrowseView(Vertical):
    BINDINGS = [
        Binding("backspace,escape", "back", "Back"),
        Binding("slash", "focus_search", "Search"),
        Binding("a", "add", "Add to queue"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[Level] = []

    @property
    def heos(self) -> "HeosTui":
        return cast("HeosTui", self.app)

    def compose(self) -> ComposeResult:
        yield Static(id="crumb")
        yield Input(placeholder="Search current source (/)", id="search")
        yield DataTable(cursor_type="row", zebra_stripes=True, id="browse-table")
        yield Static(id="browse-status")

    def on_mount(self) -> None:
        table = self.query_one("#browse-table", DataTable)
        table.add_column("Name", key="name")
        table.add_column("Type", key="kind")
        table.add_column("Detail", key="detail")

    # ---- rendering ------------------------------------------------------------------

    def _show_level(self, focus: bool = True) -> None:
        level = self.stack[-1]
        crumb = " › ".join(lv.title for lv in self.stack)
        self.query_one("#crumb", Static).update(Text(crumb, style="bold"))
        table = self.query_one("#browse-table", DataTable)
        table.clear()
        for i, item in enumerate(level.items):
            prefix = "› " if _browsable(item) else ("♪ " if _playable(item) else "  ")
            if isinstance(item, MediaMusicSource):
                detail = "" if item.available else "sign in to HEOS account"
            else:
                detail = " · ".join(
                    x for x in (getattr(item, "artist", None), getattr(item, "album", None)) if x
                )
            table.add_row(Text(prefix + item.name), Text(item.type.value), Text(detail), key=str(i))
        shown = len(level.items)
        status = f"{shown} item(s)" + (f" of {level.total}" if level.total > shown else "")
        self.query_one("#browse-status", Static).update(Text(status, style="dim"))
        if focus:  # focusing the table also activates the Browse tab, so not when sources load
            table.focus()

    def _selected(self) -> Media | None:
        table = self.query_one("#browse-table", DataTable)
        if not table.row_count or not self.stack:
            return None
        return self.stack[-1].items[
            int(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        ]

    # ---- navigation -----------------------------------------------------------------

    @work(exclusive=True, group="browse")
    async def show_sources(self, refresh: bool = False) -> None:
        sources = await self.heos.guard(self.heos.heos.get_music_sources(refresh=refresh))
        if sources is not None:
            self.stack = [Level("Sources", None, list(sources.values()))]
            self._show_level(focus=False)

    async def _open(self, item: Media) -> None:
        result = await self.heos.guard(self.heos.heos.browse_media(item))
        if result is not None:
            self.stack.append(Level(item.name, item.source_id, list(result.items), result.count))
            self._show_level()

    def action_back(self) -> None:
        if len(self.stack) > 1:
            self.stack.pop()
            self._show_level()

    def _playable_item(self, item: MediaItem) -> MediaItem:
        """Tracks found by search carry no container id; derive it from the search."""
        search_container = self.stack[-1].search_container
        if item.container_id is None and search_container:
            return dataclasses.replace(item, container_id=search_container)
        return item

    @work(exclusive=True, group="browse")
    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        item, player = self._selected(), self.heos.player
        if item is None:
            return
        if isinstance(item, MediaMusicSource) and not item.available:
            self.app.notify("Sign in to your HEOS account first (press l).", severity="warning")
        elif _browsable(item):
            await self._open(item)
        elif player is None:
            self.app.notify("Select a player first.", severity="warning")
        elif isinstance(item, MediaItem) and item.playable:
            await self.heos.guard(player.play_media(self._playable_item(item)))
        else:
            self.app.notify("This item can't be played directly.", severity="warning")

    # ---- add to queue ---------------------------------------------------------------

    @work
    async def action_add(self) -> None:
        item, player = self._selected(), self.heos.player
        if player is None or not isinstance(item, MediaItem) or not item.playable:
            self.app.notify("Only playable items can be added to the queue.", severity="warning")
            return
        mode = await self.app.push_screen_wait(
            ChoiceScreen(
                f"Add {item.name}",
                [
                    ("Play now", AddCriteriaType.PLAY_NOW),
                    ("Play next", AddCriteriaType.PLAY_NEXT),
                    ("Add to end of queue", AddCriteriaType.ADD_TO_END),
                    ("Replace queue and play", AddCriteriaType.REPLACE_AND_PLAY),
                ],
            )
        )
        if mode is not None:
            await self.heos.guard(player.play_media(self._playable_item(item), mode))

    # ---- search ---------------------------------------------------------------------

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    @work(exclusive=True, group="browse")
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value.strip()
        sid = self.stack[-1].source_id if self.stack else None
        if not text:
            return
        if sid is None:
            self.app.notify("Open a source first, then search inside it.", severity="warning")
            return
        heos = self.heos.heos
        criteria = await self.heos.guard(heos.get_search_criteria(sid))
        if not criteria:
            if criteria is not None:
                self.app.notify("This source can't be searched.", severity="warning")
            return
        chosen = criteria[0]
        if len(criteria) > 1:
            chosen = await self.app.push_screen_wait(
                ChoiceScreen("Search by", [(c.name, c) for c in criteria])
            )
            if chosen is None:
                return
        result = await self.heos.guard(heos.search(sid, text, chosen.criteria_id))
        if result is not None:
            container = f"{chosen.container_id}{text}" if chosen.container_id else None
            self.stack.append(
                Level(f'Search "{text}"', sid, list(result.items), result.count, container)
            )
            self._show_level()
