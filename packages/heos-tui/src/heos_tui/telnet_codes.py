"""Plain-language explanations for the receiver's telnet events.

An event is (zone, code, parameter): denonavr splits each telnet message into a two-letter ``code``
and the rest as ``parameter``, and assigns the zone itself ("All" for codes that concern the whole
receiver, "Zone2"/"Zone3" for Z2/Z3 messages, otherwise "Main").

The meanings below come from denonavr's own command table (denonavr/const.py) where possible. Codes
that table does not cover are not guessed at: they are reported as not decoded.
"""

ZONES = {
    "Main": "main zone",
    "Zone2": "zone 2",
    "Zone3": "zone 3",
    "All": "whole receiver (not tied to one zone)",
}

# Two-letter code -> meaning.
CODES = {
    "PW": "power",
    "ZM": "main zone power",
    "Z2": "zone 2",
    "Z3": "zone 3",
    "MV": "master volume",
    "MU": "mute",
    "SI": "input source",
    "MS": "sound mode",
    "PS": "audio setting",
    "CV": "channel volume",
    "MN": "on-screen menu / setup",
    "NS": "network audio",
    "VS": "video setting",
    "DIM": "display dimmer",
    "ECO": "eco mode",
    "STBY": "auto standby",
    "SLP": "sleep timer",
    "TR": "trigger output",
    "SP": "speaker preset",
    "BT": "Bluetooth",
    "SY": "system (remote/panel lock, reset)",
    "SS": "setup and info values",
    "ILB": "illumination",
}

# code -> {parameter prefix: meaning}; the longest matching prefix wins.
SUBCODES = {
    "PS": {
        "NEURAL": "Neural:X",
        "IMAXAUD": "IMAX audio settings",
        "IMAXHPF": "IMAX high-pass filter",
        "IMAXLPF": "IMAX low-pass filter",
        "IMAXSWM": "IMAX subwoofer mode",
        "IMAXSWO": "IMAX subwoofer output",
        "IMAX": "IMAX mode",
        "CINEMA EQ": "Cinema EQ",
        "MULTEQ": "MultiEQ",
        "DYNEQ": "Dynamic EQ",
        "REFLEV": "Reference level offset",
        "DYNVOL": "Dynamic Volume",
        "TONE CTRL": "Tone control",
        "BAS": "Bass",
        "TRE": "Treble",
        "SWR": "Subwoofer on/off",
        "SWL": "Subwoofer level",
        "LFE": "LFE level",
        "DELAY": "Audio delay",
        "DEL": "Audio delay time",
        "AUROPR": "Auro-3D preset",
        "AUROST": "Auro-3D strength",
        "AUROMODE": "Auro-3D mode",
        "DIRAC": "Dirac filter",
        "LFC": "Audyssey LFC",
        "CNTAMT": "Audyssey LFC containment amount",
        "LOM": "Loudness management",
        "BSC": "Bass sync",
        "DEH": "Dialog enhancer",
        "DIC": "Dialog control",
        "CES": "Center spread",
        "RSZ": "Room size",
        "SPV": "Speaker virtualizer",
        "SP:": "Effect speaker selection",
        "DRC": "Dynamic range compression",
        "RSTR": "Audio restorer",
        "GEQ": "Graphic EQ",
        "HEQ": "Headphone EQ",
        "MDAX": "MDAX",
        "DACFIL": "DAC filter",
    },
    "SS": {
        "TTRLEV": "Tactile transducer level",
        "TTRLPF": "Tactile transducer low-pass filter",
        "TTR": "Tactile transducer",
        "HOSALS": "Auto lip sync",
        "INF": "Info screen value (signal details; the exact field is not decoded here)",
    },
    "SY": {
        "RST": "Reset",
        "REMOTE LOCK": "Remote control lock",
        "PANEL+V LOCK": "Panel and volume lock",
        "PANEL LOCK": "Panel lock",
    },
    "VS": {
        "MONI": "HDMI output",
        "AUDIO": "HDMI audio decode",
        "VPM": "Video processing mode",
    },
    "NS": {
        "9A": "Play",
        "9B": "Pause",
        "9C": "Stop",
        "E": "Display line",
    },
}


def _volume(parameter: str) -> str | None:
    """MV values: the receiver counts from -80 dB; a third digit is the half step (as in denonavr)."""
    digits = parameter.strip()
    if not digits.isdigit() or len(digits) < 2:
        return None
    value = int(digits[:2]) + (0.5 if len(digits) == 3 and digits[2] == "5" else 0)
    return f"{value - 80:+.1f} dB"


def describe_zone(zone: str) -> str:
    return ZONES.get(zone, zone)


def describe(zone: str, code: str, parameter: str) -> str:
    """One line explaining an event, e.g. 'audio setting › Dialog enhancer: MED'."""
    meaning = CODES.get(code)
    if meaning is None:
        return "code not decoded here"
    text = parameter.strip()
    if code == "MV":
        return f"{meaning}: {_volume(text) or text}"
    if code == "MS" and text[:5] in ("QUICK", "SMART"):
        return f"{meaning} › preset {text[5:].strip() or '?'} recalled"
    if code in ("MS", "SI", "MU", "PW", "ZM", "Z2", "Z3", "ECO", "DIM", "STBY", "SLP"):
        return f"{meaning}: {text}" if text else meaning
    subcodes = SUBCODES.get(code)
    if subcodes:
        for prefix in sorted(subcodes, key=len, reverse=True):
            if text.startswith(prefix):
                value = text[len(prefix) :].strip(" :")
                return f"{meaning} › {subcodes[prefix]}" + (f": {value}" if value else "")
        return f"{meaning} (parameter not decoded)"
    return f"{meaning}: {text}" if text else meaning
