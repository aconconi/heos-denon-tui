from heos_tui.telnet_codes import describe, describe_zone


def test_sub_codes_are_decoded_with_their_value():
    assert describe("Main", "PS", "DEH MED") == "audio setting › Dialog enhancer: MED"
    assert describe("Main", "PS", "LFC ON") == "audio setting › Audyssey LFC: ON"
    assert describe("Main", "PS", "MULTEQ:AUDYSSEY") == "audio setting › MultiEQ: AUDYSSEY"
    assert (
        describe("All", "SY", "PANEL LOCK ON")
        == "system (remote/panel lock, reset) › Panel lock: ON"
    )
    assert (
        describe("Main", "SS", "TTRLEV 50")
        == "setup and info values › Tactile transducer level: 50"
    )


def test_longest_prefix_wins():
    assert "Audyssey LFC containment amount" in describe("Main", "PS", "CNTAMT 3")
    assert "Panel and volume lock" in describe("All", "SY", "PANEL+V LOCK ON")


def test_ss_info_values_are_marked_as_not_decoded():
    text = describe("Main", "SS", "INFSIGRESS O---")
    assert "Info screen value" in text and "not decoded" in text


def test_volume_is_converted_to_db_like_denonavr_does():
    assert describe("Main", "MV", "40") == "master volume: -40.0 dB"
    assert describe("Main", "MV", "405") == "master volume: -39.5 dB"
    assert describe("Main", "MV", "MAX 98") == "master volume: MAX 98"  # not a number: shown as is


def test_quick_select_recall_and_simple_values():
    assert describe("Main", "MS", "QUICK3") == "sound mode › preset 3 recalled"
    assert describe("Main", "MS", "DOLBY SURROUND") == "sound mode: DOLBY SURROUND"
    assert describe("All", "PW", "ON") == "power: ON"
    assert describe("Main", "SI", "GAME") == "input source: GAME"


def test_unknown_codes_and_parameters_are_admitted_not_guessed():
    assert describe("Main", "XX", "1") == "code not decoded here"
    assert describe("Main", "PS", "NOPE 1") == "audio setting (parameter not decoded)"


def test_zones_have_plain_names():
    assert describe_zone("All").startswith("whole receiver")
    assert describe_zone("Main") == "main zone"
    assert describe_zone("Zone9") == "Zone9"
