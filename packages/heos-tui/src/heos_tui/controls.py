"""Controls for the Amp dashboard: a toggle, a value cycler, a slider and a preset row.

They share one fixed grid so that every row lines up whatever the terminal width:

    label (LABEL_WIDTH)  |  field (FIELD_WIDTH)  |  readout (READOUT_WIDTH)

All of them work from the keyboard and the mouse and post a ``Changed`` message on user input;
``set_*`` methods update them from the device without posting anything.
"""

from collections.abc import Callable, Sequence

from rich.text import Text
from textual import events, work
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget

from .screens import ChoiceScreen

LABEL_WIDTH = 24  # fits the longest Audyssey label, "Reference Level Offset"
GAP = 2
FIELD_X = LABEL_WIDTH + GAP  # where the field starts
FIELD_WIDTH = 26
READOUT_WIDTH = 10  # value text shown after a slider's bar
ARROWS_WIDTH = 3  # "◀ ▶"
ROW_WIDTH = FIELD_X + FIELD_WIDTH + GAP + READOUT_WIDTH
VALUE_STYLE = "cyan"  # the "data" colour, shared with the AVR Info values


class ControlRow(Widget, can_focus=True):
    """Base for the dashboard controls: one line, the label in a fixed column."""

    DEFAULT_CSS = """
    ControlRow { height: 1; }
    ControlRow:focus { background: $accent 30%; }
    ControlRow:hover { background: $accent 15%; }
    ControlRow:disabled { opacity: 0.45; }
    """

    def __init__(self, label: str, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.label = label

    def _label_text(self) -> Text:
        label = self.label
        if len(label) > LABEL_WIDTH:
            label = label[: LABEL_WIDTH - 1] + "…"
        return Text(label.ljust(FIELD_X))


class ToggleControl(ControlRow):
    """On/off: Space, Enter or a click flips it."""

    BINDINGS = [Binding("enter,space", "toggle", "Toggle", show=False)]

    class Changed(Message):
        def __init__(self, toggle: "ToggleControl", value: bool) -> None:
            super().__init__()
            self.toggle = toggle
            self.value = value

    def __init__(self, label: str, *, id: str | None = None) -> None:
        super().__init__(label, id=id)
        self.value = False

    def set_value(self, value: bool) -> None:
        self.value = value
        self.refresh()

    def render(self) -> Text:
        text = self._label_text()
        if self.value:
            text.append("● ON".ljust(FIELD_WIDTH), style="bold green")
        else:
            text.append("○ OFF".ljust(FIELD_WIDTH), style="dim")
        return text

    def action_toggle(self) -> None:
        self.value = not self.value
        self.refresh()
        self.post_message(self.Changed(self, self.value))

    def on_click(self, event: events.Click) -> None:
        self.action_toggle()


class OptionCycler(ControlRow):
    """Pick one of several values: Left/Right (or ◀ ▶) cycle, Enter/Space/click opens a list."""

    BINDINGS = [
        Binding("left", "step(-1)", "Previous", show=False),
        Binding("right", "step(1)", "Next", show=False),
        Binding("enter,space", "choose", "Choose", show=False),
    ]

    class Changed(Message):
        def __init__(self, cycler: "OptionCycler", value: str) -> None:
            super().__init__()
            self.cycler = cycler
            self.value = value

    def __init__(self, label: str, *, id: str | None = None) -> None:
        super().__init__(label, id=id)
        self.options: list[str] = []
        self.value: str | None = None

    def set_state(self, options: Sequence[str], value: str | None) -> None:
        self.options = list(options)
        self.value = value
        self.refresh()

    def render(self) -> Text:
        text = self._label_text()
        shown = self.value if self.value is not None else "-"
        text.append(shown.ljust(FIELD_WIDTH - ARROWS_WIDTH), style="bold cyan")
        text.append("◀ ▶", style="bold")  # the arrows sit together at the right edge of the field
        return text

    def _emit(self, value: str) -> None:
        self.value = value
        self.refresh()
        self.post_message(self.Changed(self, value))

    def action_step(self, delta: int) -> None:
        if not self.options:
            return
        index = self.options.index(self.value) if self.value in self.options else -1
        self._emit(self.options[(index + delta) % len(self.options)])

    @work
    async def action_choose(self) -> None:
        if not self.options:
            return
        chosen = await self.app.push_screen_wait(
            ChoiceScreen(self.label, [(o, o) for o in self.options])
        )
        if chosen is not None:
            self._emit(chosen)

    def on_click(self, event: events.Click) -> None:
        x = event.x - FIELD_X
        if x == FIELD_WIDTH - ARROWS_WIDTH:
            self.action_step(-1)
        elif x == FIELD_WIDTH - 1:
            self.action_step(1)
        else:
            self.action_choose()


class AmpSlider(ControlRow):
    """Left/Right (PageUp/PageDown for big steps), the mouse wheel, or a click on the bar."""

    BINDINGS = [
        Binding("left", "nudge(-1)", "Down", show=False),
        Binding("right", "nudge(1)", "Up", show=False),
        Binding("pagedown", "nudge(-5)", "Down a lot", show=False),
        Binding("pageup", "nudge(5)", "Up a lot", show=False),
        Binding("home", "jump(0)", "Minimum", show=False),
        Binding("end", "jump(1)", "Maximum", show=False),
    ]

    class Changed(Message):
        def __init__(self, slider: "AmpSlider", value: float) -> None:
            super().__init__()
            self.slider = slider
            self.value = value

    def __init__(
        self,
        label: str,
        minimum: float,
        maximum: float,
        step: float,
        fmt: Callable[[float], str],
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(label, id=id)
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.fmt = fmt
        self.value: float | None = None

    bar_width = FIELD_WIDTH  # the bar fills the field exactly, like the other controls

    def set_value(self, value: float | None) -> None:
        self.value = value
        self.refresh()

    def render(self) -> Text:
        text = self._label_text()
        width = self.bar_width
        if self.value is None:
            text.append("─" * width, style="dim")
            text.append(" " * GAP + "-")
            return text
        fraction = (self.value - self.minimum) / (self.maximum - self.minimum)
        filled = round(max(0.0, min(1.0, fraction)) * (width - 1))
        text.append("━" * filled, style="green")
        text.append("●", style="bold green")
        text.append("─" * (width - 1 - filled), style="dim")
        text.append(" " * GAP + self.fmt(self.value), style="bold cyan")
        return text

    def _emit(self, value: float) -> None:
        value = round(max(self.minimum, min(self.maximum, value)) / self.step) * self.step
        self.value = value
        self.refresh()
        self.post_message(self.Changed(self, value))

    def action_nudge(self, steps: int) -> None:
        if self.value is not None:
            self._emit(self.value + steps * self.step)

    def action_jump(self, fraction: float) -> None:
        self._emit(self.minimum + (self.maximum - self.minimum) * fraction)

    def on_click(self, event: events.Click) -> None:
        position = event.x - FIELD_X
        if 0 <= position < self.bar_width:
            self.action_jump(position / (self.bar_width - 1))

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self.action_nudge(1)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self.action_nudge(-1)


class PresetRow(ControlRow):
    """One numbered preset: shows its name; Enter, Space or a click recalls it.

    A preset is an action (it sets many parameters at once), so nothing here shows a "current" one.
    """

    BINDINGS = [Binding("enter,space", "recall", "Recall", show=False)]

    class Changed(Message):
        def __init__(self, preset_row: "PresetRow", slot: int) -> None:
            super().__init__()
            self.preset_row = preset_row
            self.slot = slot

    def __init__(self, slot: int, name: str, *, id: str | None = None) -> None:
        super().__init__(name, id=id)
        self.slot = slot

    def set_name(self, name: str) -> None:
        self.label = name
        self.refresh()

    def _label_text(self) -> Text:
        """The number, then the preset's name in the same style as the AVR Info values."""
        prefix = f"{self.slot}  "
        name = self.label
        if len(prefix) + len(name) > LABEL_WIDTH:
            name = name[: LABEL_WIDTH - len(prefix) - 1] + "…"
        text = Text(prefix)
        text.append(name, style=VALUE_STYLE)
        text.append(" " * (FIELD_X - len(prefix) - len(name)))
        return text

    def render(self) -> Text:
        text = self._label_text()
        text.append("▶ recall".ljust(FIELD_WIDTH), style="dim")
        return text

    def action_recall(self) -> None:
        self.post_message(self.Changed(self, self.slot))

    def on_click(self, event: events.Click) -> None:
        self.action_recall()
