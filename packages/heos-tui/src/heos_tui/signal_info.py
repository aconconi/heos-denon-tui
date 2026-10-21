"""Audio/video signal info (format, sample rate, resolution) from the receiver.

denonavr has no public API for this. These are the AppCommand requests Denon's own app sends
for its Info screen (GetAudioInfo, GetVideoInfo; see denonavr's doc/XML_data_dump.txt), sent
through denonavr's HTTP client. That means using its internal ``_device`` attribute, so this
module may need updating after a denonavr upgrade. The response layout is not documented, so the
parser accepts both ``<param name="x">v</param>`` and ``<x>v</x>`` styles and keeps only known keys.
"""

from xml.etree.ElementTree import Element

from denonavr import DenonAVR
from denonavr.appcommand import AppCommandCmd, AppCommandCmdParam

AUDIO_FIELDS = ("inputmode", "output", "signal", "sound", "fs")
VIDEO_FIELDS = ("videooutput", "hdmisigin", "hdmisigout")


def _command(name: str, fields: tuple[str, ...]) -> AppCommandCmd:
    return AppCommandCmd(
        cmd_id="3", name=name, param_list=tuple(AppCommandCmdParam(f) for f in fields)
    )


def parse_response(root: Element, fields: tuple[str, ...]) -> dict[str, str]:
    """Collect the known fields from an AppCommand response, whichever way they are tagged."""
    found: dict[str, str] = {}
    for element in root.iter():
        key = (element.get("name") or element.tag).lower()
        text = (element.text or "").strip()
        if key in fields and len(element) == 0 and text:
            found[key] = text
    return found


async def fetch_signal_info(avr: DenonAVR) -> dict[str, str]:
    """Ask the receiver for its current audio and video signal details."""
    device = avr._device  # noqa: SLF001 - see module docstring
    info: dict[str, str] = {}
    for name, fields in (("GetAudioInfo", AUDIO_FIELDS), ("GetVideoInfo", VIDEO_FIELDS)):
        root = await device.api.async_post_appcommand(
            device.urls.appcommand0300, (_command(name, fields),)
        )
        info.update(parse_response(root, fields))
    return info
