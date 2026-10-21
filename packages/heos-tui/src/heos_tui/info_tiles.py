"""The AVR Info grid: small tiles (label above, value below) that reflow to the terminal width."""

from denonavr import DenonAVR
from rich.text import Text
from textual.widget import Widget

from .controls import VALUE_STYLE

MIN_TILE_WIDTH = 22  # three tiles fit an 80-column terminal
MAX_COLUMNS = 4

# (tile id suffix, label)
INFO_FIELDS = (
    ("audio-format", "Audio format"),
    ("sample-rate", "Sample rate"),
    ("audio-input", "Audio input mode"),
    ("audio-output", "Audio output"),
    ("video-input", "Video input"),
    ("video-output", "Video output"),
    ("video-mode", "Video output mode"),
    ("sound-raw", "Sound mode (raw)"),
    ("hdmi-output", "HDMI output"),
    ("hdmi-decode", "HDMI audio decode"),
    ("video-processing", "Video processing"),
)


def info_values(avr: DenonAVR, signal: dict[str, str]) -> dict[str, str | None]:
    """Tile values by id suffix. ``signal`` comes from ``fetch_signal_info``.

    Values are shown as the receiver reports them. "Sample rate" is the sampling frequency;
    Denon does not report a bit rate.
    """
    return {
        "audio-format": signal.get("signal"),
        "sample-rate": signal.get("fs"),
        "audio-input": signal.get("inputmode"),
        "audio-output": signal.get("output"),
        "video-input": signal.get("hdmisigin"),
        "video-output": signal.get("hdmisigout"),
        "video-mode": signal.get("videooutput"),
        "sound-raw": avr.sound_mode_raw,
        "hdmi-output": avr.hdmi_output,
        "hdmi-decode": avr.hdmi_audio_decode,
        "video-processing": avr.video_processing_mode,
    }


def columns_for(width: int) -> int:
    """How many tiles per row fit ``width`` cells."""
    return max(1, min(MAX_COLUMNS, width // MIN_TILE_WIDTH))


def _fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(width - 1, 0)] + "…"


class InfoTile(Widget):
    """A read-only two-line tile: dim label, bold value ("-" when unknown)."""

    DEFAULT_CSS = "InfoTile { height: 2; }"

    def __init__(self, label: str, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.label = label
        self.value: str | None = None

    def set_value(self, value: str | None) -> None:
        self.value = value
        self.refresh()

    def render(self) -> Text:
        width = self.size.width
        shown = "-" if self.value in (None, "") else str(self.value)
        text = Text(_fit(self.label, width), style="dim")
        text.append("\n")
        text.append(_fit(shown, width), style=VALUE_STYLE)
        return text
