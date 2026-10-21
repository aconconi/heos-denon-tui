"""The HEOS terminal app."""

from collections.abc import Awaitable
from typing import Any, TypeVar

from denonavr import DenonAVR
from denonavr.exceptions import DenonAvrError
from heos_discovery import discover
from pyheos import (
    Heos,
    HeosError,
    HeosOptions,
    HeosPlayer,
    PlayState,
    RepeatType,
    SignalHeosEvent,
    SignalType,
    const,
)
from pyheos.const import SERVICE_OPTION_THUMBS_DOWN, SERVICE_OPTION_THUMBS_UP
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, TabbedContent, TabPane

from .avr import AvrPanel
from .screens import AccountScreen, ChoiceScreen
from .widgets import BrowseView, NowPlayingBar, QueueView, state_icon

T = TypeVar("T")
_NEXT_REPEAT = {
    RepeatType.OFF: RepeatType.ON_ALL,
    RepeatType.ON_ALL: RepeatType.ON_ONE,
    RepeatType.ON_ONE: RepeatType.OFF,
}


class HeosTui(App):
    TITLE = "HEOS"
    CSS = """
    NowPlayingBar { height: auto; border-top: solid $primary; padding: 0 1; }
    BrowseView, #players, #queue-table, #browse-table { height: 1fr; }
    """
    BINDINGS = [
        Binding("space", "toggle_play", "Play/Pause"),
        Binding("n", "next_track", "Next"),
        Binding("p", "previous_track", "Prev"),
        Binding("plus,equals_sign", "volume_up", "Vol+"),
        Binding("minus", "volume_down", "Vol-"),
        Binding("m", "toggle_mute", "Mute"),
        Binding("s", "toggle_shuffle", "Shuffle"),
        Binding("r", "cycle_repeat", "Repeat"),
        Binding("o", "options", "Options"),
        Binding("l", "account", "Account"),
        Binding("left_square_bracket", "room(-1)", "Prev room"),
        Binding("right_square_bracket", "room(1)", "Next room"),
        Binding("1", "show_tab('rooms')", "Rooms"),
        Binding("2", "show_tab('queue')", "Queue"),
        Binding("3", "show_tab('browse')", "Browse"),
        Binding("4", "show_tab('amp')", "Amp"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, host: str | None = None, avr_host: str | None = None) -> None:
        super().__init__()
        self.host = host
        self.avr_host = avr_host
        self.avr_panel: AvrPanel | None = None
        self._closing = False
        self.heos: Heos = None  # type: ignore[assignment]  # created once the event loop runs
        self.current_pid: int | None = None
        self.account: str | None = None

    @property
    def player(self) -> HeosPlayer | None:
        if self.heos is None or self.current_pid is None:
            return None
        return self.heos.players.get(self.current_pid)

    # ---- layout ---------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs", initial="queue"):
            with TabPane("Rooms [1]", id="rooms"):
                yield DataTable(id="players", cursor_type="row", zebra_stripes=True)
            with TabPane("Queue [2]", id="queue"):
                yield QueueView()
            with TabPane("Browse [3]", id="browse"):
                yield BrowseView()
        yield NowPlayingBar()
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#players", DataTable)
        table.add_column("", key="state", width=2)
        table.add_column("Room", key="name")
        table.add_column("Model", key="model")
        table.add_column("Volume", key="vol", width=10)
        self.query_one(NowPlayingBar).show(None)
        self.connect_and_load()

    # ---- connection and loading -----------------------------------------------------

    async def guard(self, awaitable: Awaitable[T]) -> T | None:
        """Await a library call; show HEOS errors as notifications and return None."""
        try:
            return await awaitable
        except (HeosError, ValueError) as exc:
            self.notify(str(exc), title="HEOS", severity="error")
        return None

    @work(exclusive=True, group="connect")
    async def connect_and_load(self) -> None:
        host = self.host
        if host is None:
            self.sub_title = "searching for a HEOS device..."
            found = await discover(timeout=5, stop_after_first=True)
            if not found:
                self.exit(
                    message="No HEOS device found. Pass --host or set HEOS_HOST.", return_code=1
                )
                return
            host = found[0].host
        self.sub_title = f"connecting to {host}..."
        self.host = host
        # pyheos sends heart beats, re-signs in and reloads state after reconnecting.
        self.heos = Heos(HeosOptions(host, auto_reconnect=True))
        self.heos.add_on_heos_event(self.on_heos_event)
        self.heos.add_on_controller_event(self.on_controller_event)
        self.heos.dispatcher.connect(SignalType.PLAYER_EVENT, self.on_player_event)
        try:
            await self.heos.connect()
            await self.heos.get_players()
        except HeosError as exc:
            self.exit(message=str(exc), return_code=1)
            return
        self.set_account(self.heos.signed_in_username)
        self.rebuild_players()
        self.query_one(BrowseView).show_sources()
        self.connect_avr()

    @work(exclusive=True, group="avr")
    async def connect_avr(self) -> None:
        """Add the Amp tab if a Denon AVR answers: at --avr-host, else at the HEOS device's own address.

        The auto-detect probe is silent when it fails (most HEOS speakers are not AVRs).
        """
        explicit = self.avr_host is not None
        host = self.avr_host or self.host
        if host is None:
            return
        avr = DenonAVR(host, timeout=3.0)
        try:
            await avr.async_setup()
            await avr.async_update()
            try:
                await avr.async_update_audyssey()
            except DenonAvrError:
                pass  # not every model supports Audyssey
            try:
                await (
                    avr.async_telnet_connect()
                )  # live events; the receiver allows one telnet client
            except Exception:
                self.notify(
                    "Amp live events unavailable (telnet busy?); polling instead.",
                    severity="warning",
                )
        except Exception as exc:  # noqa: BLE001 - the probe must never take the TUI down
            if explicit:
                self.notify(f"No Denon AVR at {host}: {exc}", title="Amp", severity="error")
            return
        self.avr_panel = AvrPanel(avr)
        await self.query_one(TabbedContent).add_pane(TabPane("Amp [4]", self.avr_panel, id="amp"))
        await self.load_quick_select_names(host)

    async def load_quick_select_names(self, avr_host: str) -> None:
        """Quick Select names live in HEOS: ask the HEOS player that is the amp (matched by address)."""
        players = list(self.heos.players.values())
        match = [p for p in players if p.ip_address == avr_host] or (
            players if len(players) == 1 else []
        )
        if not match or self.avr_panel is None:
            return
        try:
            names = await match[0].get_quick_selects()
        except (HeosError, ValueError):
            return  # not every HEOS device supports Quick Selects; the rows keep their default names
        self.avr_panel.set_preset_names(names)

    def set_account(self, username: str | None) -> None:
        self.account = username
        self.sub_title = f"{self.host} · {username or 'not signed in (press l)'}"

    # ---- player list ----------------------------------------------------------------

    @staticmethod
    def _player_cells(player: HeosPlayer) -> tuple[str, Text, Text, Text]:
        if not player.available:
            return (
                "!",
                Text(player.name, style="dim"),
                Text(player.model, style="dim"),
                Text("offline", style="dim"),
            )
        vol = f"{player.volume}{' 🔇' if player.is_muted else ''}"
        return state_icon(player), Text(player.name), Text(player.model, style="dim"), Text(vol)

    def rebuild_players(self) -> None:
        table = self.query_one("#players", DataTable)
        table.clear()
        for pid, player in self.heos.players.items():
            table.add_row(*self._player_cells(player), key=str(pid))
        if self.current_pid in self.heos.players:
            table.move_cursor(row=list(self.heos.players).index(self.current_pid))
        elif self.heos.players:
            self.current_pid = next(iter(self.heos.players))

    def render_player(self, pid: int) -> None:
        player = self.heos.players.get(pid)
        if player is None:
            return
        table = self.query_one("#players", DataTable)
        for column, cell in zip(
            ("state", "name", "model", "vol"), self._player_cells(player), strict=True
        ):
            try:
                table.update_cell(str(pid), column, cell)
            except Exception:  # row not built yet
                return
        if pid == self.current_pid:
            self.query_one(NowPlayingBar).show(player, self.size.width, len(self.heos.players))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "players" and event.row_key.value is not None:
            self.current_pid = int(event.row_key.value)
            self.load_selected()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "players":  # Enter on a room: go and look at its queue
            self.action_show_tab("queue")

    def action_room(self, delta: int) -> None:
        """Switch the active room from any tab."""
        table = self.query_one("#players", DataTable)
        if table.row_count:
            table.move_cursor(row=(table.cursor_row + delta) % table.row_count)

    @work(exclusive=True, group="select")
    async def load_selected(self) -> None:
        if (pid := self.current_pid) is not None:
            self.render_player(pid)
            await self.reload_queue()

    async def reload_queue(self) -> None:
        player = self.player
        if player is None:
            return
        items = await self.guard(player.get_queue())
        if items is not None and player.player_id == self.current_pid:
            self.query_one(QueueView).load(items, player.now_playing_media.queue_id)

    # ---- change events (pyheos has already updated the player objects) --------------

    async def on_player_event(self, player_id: int, event: str) -> None:
        if self._closing:
            return
        self.render_player(player_id)
        if player_id != self.current_pid:
            return
        player = self.heos.players[player_id]
        if event == const.EVENT_PLAYER_QUEUE_CHANGED:
            await self.reload_queue()
        elif event == const.EVENT_PLAYER_NOW_PLAYING_CHANGED:
            self.query_one(QueueView).mark_current(player.now_playing_media.queue_id)
        elif event == const.EVENT_PLAYER_PLAYBACK_ERROR and player.playback_error:
            self.notify(player.playback_error, title=player.name, severity="error")

    async def on_controller_event(self, event: str, data: Any) -> None:
        if self._closing:
            return
        if event == const.EVENT_PLAYERS_CHANGED:
            self.rebuild_players()
        elif event == const.EVENT_SOURCES_CHANGED:
            self.query_one(BrowseView).show_sources(refresh=True)
        elif event == const.EVENT_USER_CHANGED:
            self.set_account(self.heos.signed_in_username)

    async def on_heos_event(self, event: str) -> None:
        if self._closing:
            return
        if event == SignalHeosEvent.DISCONNECTED:
            self.sub_title = f"{self.host} · disconnected, reconnecting..."
            self.rebuild_players()
        elif event == SignalHeosEvent.CONNECTED and self.heos.players:
            self.set_account(self.heos.signed_in_username)
            self.rebuild_players()
        elif event == SignalHeosEvent.USER_CREDENTIALS_INVALID:
            self.notify("HEOS account sign-in is no longer valid (press l).", severity="warning")
            self.set_account(None)

    # ---- actions --------------------------------------------------------------------

    def _selected(self) -> HeosPlayer | None:
        if (player := self.player) is None:
            self.notify("No player selected.", severity="warning")
        return player

    async def action_toggle_play(self) -> None:
        if player := self._selected():
            await self.guard(player.pause() if player.state is PlayState.PLAY else player.play())

    async def action_next_track(self) -> None:
        if player := self._selected():
            await self.guard(player.play_next())

    async def action_previous_track(self) -> None:
        if player := self._selected():
            await self.guard(player.play_previous())

    async def action_volume_up(self) -> None:
        if self.amp_active:
            await self.avr_panel.volume_up()
        elif player := self._selected():
            await self.guard(player.volume_up())

    async def action_volume_down(self) -> None:
        if self.amp_active:
            await self.avr_panel.volume_down()
        elif player := self._selected():
            await self.guard(player.volume_down())

    async def action_toggle_mute(self) -> None:
        if self.amp_active:
            await self.avr_panel.toggle_mute()
        elif player := self._selected():
            await self.guard(player.toggle_mute())

    async def action_toggle_shuffle(self) -> None:
        if player := self._selected():
            await self.guard(player.set_play_mode(player.repeat, not player.shuffle))

    async def action_cycle_repeat(self) -> None:
        if player := self._selected():
            await self.guard(player.set_play_mode(_NEXT_REPEAT[player.repeat], player.shuffle))

    def action_show_tab(self, tab: str) -> None:
        if tab == "amp":
            if self.avr_panel is None:
                self.notify("No Denon AVR connected (use --avr-host).", severity="warning")
                return
            self.query_one(TabbedContent).active = "amp"
            self.avr_panel.focus_first()
            return
        self.query_one(TabbedContent).active = tab
        focus = {"rooms": "#players", "queue": "#queue-table", "browse": "#browse-table"}[tab]
        self.query_one(focus).focus()

    @property
    def amp_active(self) -> bool:
        return self.avr_panel is not None and self.query_one(TabbedContent).active == "amp"

    @work
    async def action_options(self) -> None:
        """Options for the playing media: thumbs up/down and add station to Favorites."""
        if not (player := self._selected()):
            return
        np = player.now_playing_media
        options = [o for o in np.options if o.context == "play"]
        if not options:
            self.notify("No options for the current media.")
            return
        chosen = await self.push_screen_wait(
            ChoiceScreen("Options", [(o.name, o) for o in options])
        )
        if chosen is None:
            return
        # Spec 4.4.19: thumbs up/down need the source id too; "add to Favorites" takes only the player.
        kwargs: dict[str, Any] = {"player_id": player.player_id}
        if chosen.id in (SERVICE_OPTION_THUMBS_UP, SERVICE_OPTION_THUMBS_DOWN):
            kwargs["source_id"] = np.source_id
        try:
            await self.heos.set_service_option(chosen.id, **kwargs)
        except (HeosError, ValueError) as exc:
            self.notify(str(exc), title="HEOS", severity="error")
        else:
            self.notify(chosen.name)

    @work
    async def action_account(self) -> None:
        result: Any = await self.push_screen_wait(AccountScreen(self.account))
        if not result:
            return
        if result[0] == "in":
            username = await self.guard(self.heos.sign_in(result[1], result[2]))
            if username is not None:
                self.set_account(username)
                self.notify(
                    f"Signed in as {username}. Services linked to your account are under Browse."
                )
        else:
            await self.guard(self.heos.sign_out())
            self.set_account(None)
        # Spec 2.1.2.2: sources only reflect the account after (re-)signing in.
        self.query_one(BrowseView).show_sources(refresh=True)

    async def on_unmount(self) -> None:
        self._closing = True  # pyheos reports the disconnect below; the screen is already gone
        if self.avr_panel is not None:
            await self.avr_panel.avr.async_telnet_disconnect()
        if self.heos is not None:
            await self.heos.disconnect()
