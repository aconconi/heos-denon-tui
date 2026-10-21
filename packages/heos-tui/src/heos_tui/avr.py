"""Amp tab: an interactive dashboard for a Denon AVR, through the denonavr library."""

import asyncio
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, TypeVar, cast, get_args

from denonavr import DenonAVR
from denonavr.const import (
    COMMAND_QUICK_SELECT_MODE,
    COMMAND_SMART_SELECT_MODE,
    DynamicVolumeSettings,
    MultiEQModes,
    ReferenceLevelOffsets,
)
from denonavr.exceptions import DenonAvrError
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical, VerticalScroll
from textual.widgets import RichLog, Static

from .controls import ROW_WIDTH, AmpSlider, OptionCycler, PresetRow, ToggleControl
from .info_tiles import INFO_FIELDS, InfoTile, columns_for, info_values
from .signal_info import fetch_signal_info
from .telnet_codes import describe, describe_zone

if TYPE_CHECKING:
    from .app import HeosTui

T = TypeVar("T")

# Dialog enhancer is not part of denonavr's API; it is sent as a raw telnet command (PSDEH).
DIALOG_LEVELS = ("OFF", "LOW", "MED", "HIGH")
POLL_SECONDS = 10
PRESET_RELOAD_DELAYS = (0.0, 1.5, 4.0)  # seconds after a preset is recalled
SIGNAL_EVENTS = {"SI", "MS", "SD", "DC", "SV"}  # telnet events that can change the signal info
QUICK_SELECTS = 4  # Denon AVRs have four Quick Select presets
QUICK_SELECT_TITLE = "Quick Select"
TONE_CENTRE = 6  # the receiver reports bass/treble as 0..12; 6 is flat (0 dB)


def format_title(avr: DenonAVR) -> Text:
    text = Text()
    text.append(avr.name or "Denon AVR", style="bold")
    model = avr.model_name or ""
    detail = f"{model} · {avr.host}" if model and model != avr.name else str(avr.host)
    text.append(f"   {detail}", style="dim")
    return text


class AvrPanel(VerticalScroll):
    DEFAULT_CSS = """
    AvrPanel { padding: 1 2; }
    AvrPanel #amp-title { margin-bottom: 1; }
    AvrPanel #amp-columns { grid-size: 2; grid-gutter: 0 2; grid-rows: auto; height: auto; }
    AvrPanel .block { height: auto; }
    AvrPanel .section { margin-top: 1; text-style: bold; color: $accent; }
    AvrPanel .first { margin-top: 0; }
    AvrPanel #amp-columns.narrow { grid-size: 1; }
    AvrPanel #amp-info { grid-size: 3; grid-gutter: 0 2; grid-rows: 2; height: auto; }
    AvrPanel #amp-log-title { margin-top: 1; }
    AvrPanel #amp-log { height: 8; }
    """
    BINDINGS = [
        Binding("down", "focus_next_control", "Next", show=False),
        Binding("up", "focus_previous_control", "Previous", show=False),
        Binding("w", "toggle('amp-power')", "Power"),
        Binding("e", "toggle('amp-dyneq')", "Dynamic EQ"),
        Binding("t", "toggle('amp-tone')", "Tone"),
        Binding("i", "choose('amp-input')", "Input"),
        Binding("d", "choose('amp-soundmode')", "Sound mode"),
        Binding("a", "focus_control('amp-multieq')", "Audyssey"),
        Binding("h", "choose('amp-dialog')", "Dialog enh."),
        Binding("u", "focus_control('amp-quick-1')", "Presets"),
    ]

    def __init__(self, avr: DenonAVR) -> None:
        super().__init__(id="avr-panel")
        self.avr = avr
        self.dialog: str | None = None
        self.signal: dict[str, str] = {}  # audio/video signal info, refreshed with the poll

    @property
    def tui(self) -> "HeosTui":
        return cast("HeosTui", self.app)

    def compose(self) -> ComposeResult:
        yield Static(id="amp-title")
        tone = lambda v: f"{v - TONE_CENTRE:+.0f} dB"  # noqa: E731
        # A two-column grid: Receiver | Quick Select, then Audyssey | Tone and dialog, so that
        # the headings of the second row line up. One column when the terminal is narrow.
        with Grid(id="amp-columns"):
            with Vertical(classes="block"):
                yield Static("Receiver", classes="section first", id="amp-receiver-title")
                yield ToggleControl("Power", id="amp-power")
                yield ToggleControl("Mute", id="amp-mute")
                yield OptionCycler("Input", id="amp-input")
                yield OptionCycler("Sound mode", id="amp-soundmode")
                yield AmpSlider(
                    "Volume", -80.0, 18.0, 0.5, lambda v: f"{v:+.1f} dB", id="amp-volume"
                )
            with Vertical(classes="block"):
                yield Static(QUICK_SELECT_TITLE, classes="section first", id="amp-quick-title")
                for slot in range(1, QUICK_SELECTS + 1):
                    yield PresetRow(slot, f"Quick Select {slot}", id=f"amp-quick-{slot}")
            with Vertical(classes="block"):
                yield Static("Audyssey", classes="section", id="amp-audyssey-title")
                yield OptionCycler("MultiEQ XT32", id="amp-multieq")
                yield ToggleControl("Dynamic EQ", id="amp-dyneq")
                yield OptionCycler("Reference Level Offset", id="amp-reflevel")
                yield OptionCycler("Dynamic Volume", id="amp-dynvol")
                yield ToggleControl("Audyssey LFC", id="amp-lfc")
            with Vertical(classes="block"):
                yield Static("Tone and dialog", classes="section", id="amp-tone-title")
                yield ToggleControl("Tone control", id="amp-tone")
                yield AmpSlider("Bass", 0, 12, 1, tone, id="amp-bass")
                yield AmpSlider("Treble", 0, 12, 1, tone, id="amp-treble")
                yield OptionCycler("Dialog enhancer", id="amp-dialog")
        yield Static("AVR Info", classes="section")
        with Grid(id="amp-info"):
            for key, label in INFO_FIELDS:
                yield InfoTile(label, id=f"info-{key}")
        yield Static(
            Text(
                "Telnet events: zone · code · parameter · meaning\n"
                + " · ".join(f"{z} = {describe_zone(z)}" for z in ("Main", "All")),
                style="dim",
            ),
            id="amp-log-title",
        )
        yield RichLog(id="amp-log", max_lines=200, markup=False, wrap=False)

    def on_resize(self) -> None:
        # Two columns of ROW_WIDTH need room for both plus padding; below that stack them.
        self.query_one("#amp-columns").set_class(self.size.width < 2 * ROW_WIDTH + 8, "narrow")
        # The AVR Info tiles reflow: three across an 80-column terminal, more when wider.
        self.query_one("#amp-info", Grid).styles.grid_size_columns = columns_for(self.size.width)

    def on_mount(self) -> None:
        self.avr.register_callback("ALL", self._on_telnet_event)
        self.set_interval(POLL_SECONDS, self.refresh_from_device)
        self.sync()
        self.refresh_from_device()  # first read of the audio/video info
        if self.avr.telnet_connected:
            self.avr.send_telnet_commands("PSDEH ?")  # ask for the dialog enhancer state

    def on_unmount(self) -> None:
        self.avr.unregister_callback("ALL", self._on_telnet_event)

    def focus_first(self) -> None:
        self.query_one("#amp-power").focus()

    # ---- device state -> controls ---------------------------------------------------

    def sync(self) -> None:
        """Copy the receiver's state into the controls without triggering commands."""
        avr = self.avr
        self.query_one("#amp-title", Static).update(format_title(avr))
        for key, value in info_values(avr, self.signal).items():
            self.query_one(f"#info-{key}", InfoTile).set_value(value)
        switches = {
            "amp-power": ((avr.power or "").upper() == "ON", True),
            "amp-mute": (bool(avr.muted), avr.muted is not None),
            "amp-dyneq": (bool(avr.dynamic_eq), avr.dynamic_eq is not None),
            # LFC is only reported over telnet, so it stays disabled without it
            "amp-lfc": (bool(avr.audyssey.lfc), avr.audyssey.lfc is not None),
            "amp-tone": (bool(avr.tone_control_status), bool(avr.support_tone_control)),
        }
        for toggle_id, (value, available) in switches.items():
            toggle = self.query_one(f"#{toggle_id}", ToggleControl)
            toggle.set_value(value)
            toggle.disabled = not available
        modes = list(avr.sound_mode_list) if avr.support_sound_mode else []
        cyclers = {
            "amp-input": (list(avr.input_func_list), avr.input_func),
            "amp-soundmode": (modes, avr.sound_mode),
            "amp-multieq": (list(get_args(MultiEQModes)), avr.multi_eq),
            "amp-reflevel": (list(get_args(ReferenceLevelOffsets)), avr.reference_level_offset),
            "amp-dynvol": (list(get_args(DynamicVolumeSettings)), avr.dynamic_volume),
            "amp-dialog": (list(DIALOG_LEVELS), self.dialog),
        }
        for cycler_id, (options, value) in cyclers.items():
            cycler = self.query_one(f"#{cycler_id}", OptionCycler)
            cycler.set_state(options, value)
            cycler.disabled = (
                not options or value is None and cycler_id not in ("amp-dialog", "amp-input")
            )
        self.query_one("#amp-dialog", OptionCycler).disabled = not avr.telnet_connected
        self.query_one("#amp-volume", AmpSlider).set_value(avr.volume)
        # The receiver ignores tone changes while Dynamic EQ is on.
        tone_ok = bool(avr.support_tone_control) and not avr.dynamic_eq
        for slider_id, value in (("amp-bass", avr.bass), ("amp-treble", avr.treble)):
            slider = self.query_one(f"#{slider_id}", AmpSlider)
            slider.set_value(value)
            slider.disabled = not tone_ok

    @work(exclusive=True, group="avr-poll")
    async def refresh_from_device(self) -> None:
        await self._reload()

    async def _reload(self) -> None:
        """Re-read everything the dashboard shows: receiver state, Audyssey, signal info, dialog."""
        await self.call(self.avr.async_update(), quiet=True)
        await self.call(self.avr.async_update_audyssey(), quiet=True)
        try:
            signal = await fetch_signal_info(self.avr)
        except (DenonAvrError, AttributeError):
            signal = self.signal  # keep what we had; not every model answers these
        if signal != self.signal:
            self.signal = signal
            self.query_one("#amp-log", RichLog).write(f"{'HTTP':8} {'INFO':6} {signal}")
        if self.avr.telnet_connected:
            self.avr.send_telnet_commands(
                "PSDEH ?"
            )  # the dialog enhancer is only readable over telnet
        self.sync()

    @work(exclusive=True, group="avr-settle")  # a second recall restarts the sequence
    async def reload_until_settled(self) -> None:
        """Re-read after a preset: the receiver applies its settings over a second or two."""
        for delay in PRESET_RELOAD_DELAYS:
            await asyncio.sleep(delay)
            await self._reload()

    def _on_telnet_event(self, zone: str, event: str, parameter: str) -> None:
        line = Text(f"{zone:6} {event:5} {parameter:26}")
        line.append(f"  {describe(zone, event, parameter)}", style="dim")
        self.query_one("#amp-log", RichLog).write(line)
        if event == "PS" and parameter.startswith("DEH "):
            self.dialog = parameter[4:].strip()
        elif event in SIGNAL_EVENTS:
            self.refresh_from_device()  # input, mode or signal changed: re-read the Info screen
        self.sync()

    async def call(self, awaitable: Awaitable[T], *, quiet: bool = False) -> T | None:
        """Await a denonavr call; show receiver errors as notifications unless ``quiet``."""
        try:
            return await awaitable
        except DenonAvrError as exc:
            if not quiet:
                self.app.notify(str(exc), title="Amp", severity="error")
        return None

    async def _apply(self, awaitable: Awaitable[Any]) -> None:
        """Run a command, then re-read the receiver so the dashboard shows what it did."""
        await self.call(awaitable)
        await self.call(self.avr.async_update())
        await self.call(
            self.avr.async_update_audyssey(), quiet=True
        )  # not every model has Audyssey
        self.sync()

    # ---- the app's +, - and m keys target this tab when it is active -------------------

    async def volume_up(self) -> None:
        await self._apply(self.avr.async_volume_up())

    async def volume_down(self) -> None:
        await self._apply(self.avr.async_volume_down())

    async def toggle_mute(self) -> None:
        await self._apply(self.avr.async_mute(not self.avr.muted))

    # ---- user changes -> commands ---------------------------------------------------

    async def on_toggle_control_changed(self, event: ToggleControl.Changed) -> None:
        event.stop()
        avr, want = self.avr, event.value
        match event.toggle.id:
            case "amp-power" if want != ((avr.power or "").upper() == "ON"):
                await self._apply(avr.async_power_on() if want else avr.async_power_off())
            case "amp-mute" if want != bool(avr.muted):
                await self._apply(avr.async_mute(want))
            case "amp-dyneq" if want != bool(avr.dynamic_eq):
                await self._apply(avr.async_dynamic_eq_on() if want else avr.async_dynamic_eq_off())
            case "amp-lfc" if want != bool(avr.audyssey.lfc):
                lfc = avr.audyssey
                await self._apply(lfc.async_lfc_on() if want else lfc.async_lfc_off())
            case "amp-tone" if want != bool(avr.tone_control_status):
                await self._apply(
                    avr.async_enable_tone_control() if want else avr.async_disable_tone_control()
                )

    async def on_option_cycler_changed(self, event: OptionCycler.Changed) -> None:
        event.stop()
        avr, value = self.avr, event.value
        match event.cycler.id:
            case "amp-input":
                await self._apply(avr.async_set_input_func(value))
            case "amp-soundmode":
                await self._apply(avr.async_set_sound_mode(value))
            case "amp-multieq":
                await self._apply(avr.async_set_multieq(value))
            case "amp-reflevel":
                await self._apply(avr.async_set_reflevoffset(value))
            case "amp-dynvol":
                await self._apply(avr.async_set_dynamicvol(value))
            case "amp-dialog":
                self.dialog = value
                await self.call(avr.async_send_telnet_commands(f"PSDEH {value}"))

    def set_preset_names(self, names: dict[int, str]) -> None:
        """Show custom Quick Select names (known to HEOS, not to denonavr) on the preset rows."""
        for slot in range(1, QUICK_SELECTS + 1):
            if name := names.get(slot):
                self.query_one(f"#amp-quick-{slot}", PresetRow).set_name(name)

    async def on_preset_row_changed(self, event: PresetRow.Changed) -> None:
        event.stop()
        # Denon calls these Quick Select (MSQUICKn); Marantz calls them Smart Select (MSSMARTn).
        template = (
            COMMAND_SMART_SELECT_MODE
            if (self.avr.manufacturer or "").lower().startswith("marantz")
            else COMMAND_QUICK_SELECT_MODE
        )
        # A preset is an action that sets many parameters at once; the receiver keeps no "current
        # preset" once they are changed, so confirm the recall and re-read all the real values,
        # repeatedly, because the receiver applies the settings gradually.
        await self.call(self.avr.async_get_command(template.format(number=event.slot)))
        self.app.notify(f"Recalled {event.preset_row.label}", title=QUICK_SELECT_TITLE)
        self.reload_until_settled()

    @work(exclusive=True, group="avr-slider")  # holding a key sends only the latest value
    async def on_amp_slider_changed(self, event: AmpSlider.Changed) -> None:
        event.stop()
        avr, value = self.avr, event.value
        match event.slider.id:
            case "amp-volume":
                await self._apply(avr.async_set_volume(value))
            case "amp-bass":
                await self._apply(avr.async_set_bass(int(value)))
            case "amp-treble":
                await self._apply(avr.async_set_treble(int(value)))

    # ---- keyboard navigation and shortcuts ------------------------------------------

    def action_focus_next_control(self) -> None:
        self.screen.focus_next()

    def action_focus_previous_control(self) -> None:
        self.screen.focus_previous()

    def action_toggle(self, toggle_id: str) -> None:
        toggle = self.query_one(f"#{toggle_id}", ToggleControl)
        if not toggle.disabled:
            toggle.action_toggle()

    def action_choose(self, cycler_id: str) -> None:
        cycler = self.query_one(f"#{cycler_id}", OptionCycler)
        cycler.focus()
        if not cycler.disabled:
            cycler.action_choose()

    def action_focus_control(self, control_id: str) -> None:
        self.query_one(f"#{control_id}").focus()
