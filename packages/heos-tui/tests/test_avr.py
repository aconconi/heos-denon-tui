"""The Amp tab, against a fake denonavr receiver."""

from conftest import settle
from heos_tui.app import HeosTui
from heos_tui.avr import format_title
from heos_tui.controls import FIELD_X
from heos_tui.info_tiles import columns_for, info_values
from textual.widgets import RichLog, TabbedContent

AUDIO_XML = {"signal": "AAC", "fs": "48 kHz", "inputmode": "AUTO", "output": "Stereo", "sound": "x"}
VIDEO_XML = {
    "videooutput": "HDMI 1",
    "hdmisigin": "3840x2160p 60Hz",
    "hdmisigout": "1920x1080p 60Hz",
}


class FakeApi:
    """denonavr's HTTP client: answers the Info AppCommands in the given XML style."""

    def __init__(self, style="param"):
        self.style = style
        self.requests: list[str] = []

    async def async_post_appcommand(self, url, cmds):
        from xml.etree.ElementTree import fromstring

        name = cmds[0].name
        self.requests.append(name)
        data = AUDIO_XML if name == "GetAudioInfo" else VIDEO_XML
        if self.style == "param":
            body = "".join(f'<param name="{k}">{v}</param>' for k, v in data.items())
            return fromstring(f'<rx><cmd id="3"><name>{name}</name><list>{body}</list></cmd></rx>')
        body = "".join(f"<{k}>{v}</{k}>" for k, v in data.items())
        return fromstring(f'<rx><cmd id="3">{body}</cmd></rx>')


class FakeAudyssey:
    """The part of denonavr's audyssey object the panel uses (LFC lives there, not on DenonAVR)."""

    def __init__(self):
        self.lfc = True
        self.calls: list[str] = []

    async def async_lfc_on(self):
        self.calls.append("lfc_on")

    async def async_lfc_off(self):
        self.calls.append("lfc_off")


class FakeAvr:
    """Just enough of denonavr.DenonAVR for the panel; records the calls it receives."""

    instances: list["FakeAvr"] = []

    def __init__(self, host, **kwargs):
        self.host = host
        self.calls: list[tuple] = []
        self.update_calls = 0
        self.audyssey_update_calls = 0
        self.on_update = None  # lets a test make the receiver change its values over time
        self.callbacks = []
        self.name = "Living Room AVR"
        self.model_name = "AVR-X1700H"
        self.manufacturer = "Denon"
        self.power = "ON"
        self.input_func = "Game"
        self.input_func_list = ["Game", "Phono", "Tuner"]
        self.support_sound_mode = True
        self.sound_mode = "DOLBY SURROUND"
        self.sound_mode_raw = "DOLBY SURROUND"
        self.sound_mode_list = ["MOVIE", "MUSIC", "DOLBY SURROUND"]
        self.volume = -36.5
        self.muted = False
        self.multi_eq = "Reference"
        self.dynamic_eq = True
        self.audyssey = FakeAudyssey()
        from types import SimpleNamespace

        self._device = SimpleNamespace(
            api=FakeApi(), urls=SimpleNamespace(appcommand0300="/goform/AppCommand0300.xml")
        )
        self.reference_level_offset = "0dB"
        self.dynamic_volume = "Off"
        self.support_tone_control = True
        self.tone_control_status = True
        self.bass = 0
        self.treble = 0
        self.hdmi_output = "AUTO1"
        self.hdmi_audio_decode = "AMP"
        self.video_processing_mode = "Auto"
        self.telnet_connected = True
        FakeAvr.instances.append(self)

    async def async_setup(self):
        pass

    async def async_update(self):
        self.update_calls += 1
        if self.on_update:
            self.on_update(self)

    async def async_update_audyssey(self):
        self.audyssey_update_calls += 1

    async def async_telnet_connect(self):
        pass

    async def async_telnet_disconnect(self):
        pass

    def register_callback(self, event, callback):
        self.callbacks.append(callback)

    def unregister_callback(self, event, callback):
        self.callbacks.remove(callback)

    def send_telnet_commands(self, *commands):
        self.calls.append(("telnet", *commands))

    async def async_send_telnet_commands(self, *commands):
        self.calls.append(("telnet", *commands))

    def __getattr__(self, name):  # every async_* control method just records itself
        if name.startswith("async_"):

            async def record(*args):
                self.calls.append((name, *args))

            return record
        raise AttributeError(name)


def use_fake_avr(monkeypatch):
    FakeAvr.instances.clear()
    monkeypatch.setattr("heos_tui.app.DenonAVR", FakeAvr)


async def test_amp_tab_appears_when_heos_host_is_also_an_avr(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        assert app.avr_panel is not None
        assert FakeAvr.instances[0].host == "fake"  # probed the HEOS device's own address
        await pilot.press("4")
        await settle(pilot)
        assert app.query_one(TabbedContent).active == "amp"


async def test_explicit_avr_host_is_used(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake", avr_host="192.168.1.50")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        assert FakeAvr.instances[0].host == "192.168.1.50"


async def test_no_amp_tab_when_host_is_not_an_avr(fake):
    app = HeosTui("fake")  # default stub raises, like a plain HEOS speaker
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        assert app.avr_panel is None
        await pilot.press("4")  # explains instead of crashing
        await settle(pilot)
        assert app.query_one(TabbedContent).active == "queue"


async def test_failed_probe_with_explicit_host_does_not_crash(fake):
    app = HeosTui("fake", avr_host="10.0.0.9")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        assert app.avr_panel is None


async def test_volume_mute_and_power_keys_target_the_amp_on_its_tab(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        avr = FakeAvr.instances[0]
        await pilot.press("plus", "minus", "m", "w")  # on the Queue tab: HEOS room
        await settle(pilot)
        controls = [
            c for c in avr.calls if c[0] != "telnet"
        ]  # the panel queries dialog state on mount
        assert fake.has("player/volume_up", pid="1") and not controls
        await pilot.press("4")
        await settle(pilot)
        await pilot.press("plus", "minus", "m", "w")
        await settle(pilot)
        names = [c[0] for c in avr.calls]
        assert "async_volume_up" in names and "async_volume_down" in names
        assert ("async_mute", True) in avr.calls
        assert "async_power_off" in names


async def test_input_selection_and_dynamic_eq(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        avr = FakeAvr.instances[0]
        await pilot.press("4", "i")
        await pilot.pause(0.3)
        await pilot.press("down", "enter")  # Phono
        await settle(pilot)
        assert ("async_set_input_func", "Phono") in avr.calls
        await pilot.press("e")  # shortcut flips the Dynamic EQ switch (it was on)
        await settle(pilot)
        assert ("async_dynamic_eq_off",) in avr.calls


async def test_audyssey_setting_and_dialog_enhancer(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        avr = FakeAvr.instances[0]
        await pilot.press("4", "a")  # focuses the MultiEQ selector
        await pilot.press("enter")  # opens its list
        await pilot.pause(0.3)
        await pilot.press("down", "enter")  # second value: Flat
        await settle(pilot)
        assert ("async_set_multieq", "Flat") in avr.calls
        await pilot.press("h")
        await pilot.pause(0.3)
        await pilot.press("down", "enter")  # LOW
        await settle(pilot)
        assert ("telnet", "PSDEH LOW") in avr.calls


async def test_telnet_events_are_logged_and_dialog_state_tracked(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        avr = FakeAvr.instances[0]
        await pilot.press("4")  # RichLog only renders once its tab is visible
        await settle(pilot)
        avr.callbacks[0]("Main", "PS", "DEH HIGH")
        await settle(pilot)
        assert app.avr_panel.dialog == "HIGH"
        assert app.query_one("#amp-log", RichLog).lines


def test_formats_and_title_show_dashes_for_unknown_values():
    avr = FakeAvr("x")
    avr.hdmi_audio_decode = None
    assert info_values(avr, {})["hdmi-decode"] is None  # shown as "-" by the tile
    assert "Living Room AVR" in format_title(avr).plain


async def open_amp(pilot):
    await settle(pilot)
    await pilot.press("4")
    await settle(pilot)


async def test_arrow_keys_move_between_controls(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await open_amp(pilot)
        assert app.focused.id == "amp-power"
        await pilot.press("down")
        assert app.focused.id == "amp-mute"
        await pilot.press("up")
        assert app.focused.id == "amp-power"


async def test_switches_toggle_with_space_and_with_mouse(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await open_amp(pilot)
        avr = FakeAvr.instances[0]
        await pilot.press("space")  # power switch has focus: it was on
        await settle(pilot)
        assert ("async_power_off",) in avr.calls
        await pilot.click("#amp-mute")  # mouse
        await settle(pilot)
        assert ("async_mute", True) in avr.calls


async def test_selector_cycles_with_arrows_and_follows_the_device(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await open_amp(pilot)
        avr = FakeAvr.instances[0]
        app.query_one("#amp-input").focus()
        await pilot.press("right")  # Game -> Phono
        await settle(pilot)
        assert ("async_set_input_func", "Phono") in avr.calls
        await pilot.press("left", "left")  # Phono -> Game -> wraps to Tuner
        await settle(pilot)
        assert ("async_set_input_func", "Tuner") in avr.calls


async def test_volume_slider_keyboard_and_mouse(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await open_amp(pilot)
        avr = FakeAvr.instances[0]
        app.query_one("#amp-volume").focus()
        await pilot.press("right")  # -36.5 -> -36.0
        await settle(pilot)
        assert ("async_set_volume", -36.0) in avr.calls
        slider = app.query_one("#amp-volume")
        await pilot.click(
            "#amp-volume", offset=(FIELD_X + slider.bar_width - 1, 0)
        )  # right end of the bar
        await settle(pilot)
        loudest = max(c[1] for c in avr.calls if c[0] == "async_set_volume")
        assert loudest > 0


async def test_tone_sliders_are_disabled_while_dynamic_eq_is_on(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await open_amp(pilot)
        avr = FakeAvr.instances[0]
        assert app.query_one("#amp-bass").disabled  # dynamic EQ is on in the fake
        avr.dynamic_eq = False
        app.avr_panel.sync()
        assert not app.query_one("#amp-bass").disabled


async def test_dialog_enhancer_disabled_without_telnet(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await open_amp(pilot)
        FakeAvr.instances[0].telnet_connected = False
        app.avr_panel.sync()
        assert app.query_one("#amp-dialog").disabled


async def test_dashboard_uses_two_columns_when_wide_and_one_when_narrow(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    for width, narrow in ((160, False), (80, True)):
        app = HeosTui("fake")
        async with app.run_test(size=(width, 40)) as pilot:
            await open_amp(pilot)
            assert app.query_one("#amp-columns").has_class("narrow") is narrow


def test_controls_share_one_grid_with_left_aligned_values():
    from heos_tui.controls import FIELD_WIDTH, AmpSlider, OptionCycler, ToggleControl

    toggle, cycler = ToggleControl("Power"), OptionCycler("Input")
    slider = AmpSlider("Volume", 0, 1, 1, str)
    toggle.value, cycler.value = True, "Game"
    rows = {
        "toggle": toggle.render().plain,
        "cycler": cycler.render().plain,
        "slider": slider.render().plain,
    }
    # every value starts at the first cell of the field
    assert rows["toggle"][FIELD_X:].startswith("● ON")
    assert rows["cycler"][FIELD_X:].startswith("Game")
    assert rows["slider"][FIELD_X:].startswith("─")
    assert (
        rows["cycler"][FIELD_X + FIELD_WIDTH - 3 : FIELD_X + FIELD_WIDTH] == "◀ ▶"
    )  # arrows at the right edge
    assert rows["slider"][FIELD_X : FIELD_X + FIELD_WIDTH] == "─" * FIELD_WIDTH  # bar = field width


async def test_quick_select_is_a_vertical_list_beside_receiver(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(160, 50)) as pilot:
        await open_amp(pilot)
        receiver = app.query_one("#amp-power").region
        quick = [app.query_one(f"#amp-quick-{n}").region for n in (1, 2, 3, 4)]
        assert all(r.x > receiver.x for r in quick)  # second column, right of Receiver
        assert len({r.x for r in quick}) == 1  # one column ...
        assert [r.y for r in quick] == sorted(r.y for r in quick) and len(
            {r.y for r in quick}
        ) == 4  # ... one per line
        # the Receiver and Quick Select headings share a row
        assert (
            app.query_one("#amp-quick-title").region.y
            == app.query_one("#amp-receiver-title").region.y
        )


async def test_second_row_is_audyssey_left_and_tone_and_dialog_right(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(160, 50)) as pilot:
        await open_amp(pilot)
        audyssey = app.query_one("#amp-audyssey-title").region
        tone = app.query_one("#amp-tone-title").region
        assert (
            audyssey.y == tone.y and tone.x > audyssey.x
        )  # same row, Tone and dialog on the right
        last_quick = app.query_one("#amp-quick-4").region
        last_receiver = app.query_one("#amp-volume").region
        assert audyssey.y > max(last_quick.y, last_receiver.y)  # below the first row of sections


async def test_quick_select_presets_by_keyboard_and_mouse(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(160, 50)) as pilot:
        await open_amp(pilot)
        avr = FakeAvr.instances[0]
        assert ("telnet", "PSDEH ?") in avr.calls
        await pilot.press(
            "u", "down", "down", "enter"
        )  # focus the first preset, go to the third, recall
        await settle(pilot)
        assert ("async_get_command", "/goform/formiPhoneAppDirect.xml?MSQUICK3") in avr.calls
        await pilot.click("#amp-quick-2")  # mouse
        await settle(pilot)
        assert ("async_get_command", "/goform/formiPhoneAppDirect.xml?MSQUICK2") in avr.calls
        # A preset is an action, not a state: nothing is ever marked "active", even if telnet mentions one
        avr.callbacks[0]("Main", "MS", "QUICK4")
        await settle(pilot)
        assert all(
            "active" not in app.query_one(f"#amp-quick-{n}").render().plain for n in (1, 2, 3, 4)
        )


async def test_quick_select_names_come_from_the_heos_player_at_the_amp_address(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake", avr_host="192.168.1.50")  # the Kitchen player has this address
    async with app.run_test(size=(160, 50)) as pilot:
        await open_amp(pilot)
        assert fake.has("player/get_quickselects", pid="1")
        assert app.query_one("#amp-quick-1").render().plain.startswith("1  Apple TV")
        assert app.query_one("#amp-quick-4").render().plain.startswith("4  Game console")


async def test_quick_select_keeps_default_names_when_no_player_matches(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake", avr_host="10.9.9.9")  # two HEOS players, none at this address
    async with app.run_test(size=(160, 50)) as pilot:
        await open_amp(pilot)
        assert not fake.has("player/get_quickselects")
        assert app.query_one("#amp-quick-1").render().plain.startswith("1  Quick Select 1")


async def test_everything_is_one_column_in_a_narrow_terminal(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(80, 70)) as pilot:
        await open_amp(pilot)
        xs = {
            app.query_one(i).region.x
            for i in ("#amp-power", "#amp-quick-1", "#amp-lfc", "#amp-bass")
        }
        assert len(xs) == 1  # a single column
        ys = [
            app.query_one(i).region.y
            for i in ("#amp-power", "#amp-quick-1", "#amp-lfc", "#amp-bass")
        ]
        assert ys == sorted(
            ys
        )  # in reading order: Receiver, Quick Select, Audyssey, Tone and dialog


async def test_marantz_uses_smart_select(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(140, 40)) as pilot:
        await open_amp(pilot)
        avr = FakeAvr.instances[0]
        avr.manufacturer = "Marantz"
        await pilot.press("u", "enter")
        await settle(pilot)
        assert ("async_get_command", "/goform/formiPhoneAppDirect.xml?MSSMART1") in avr.calls


async def test_audyssey_section_has_the_requested_controls_in_order(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(160, 40)) as pilot:
        await open_amp(pilot)
        ids = ["amp-multieq", "amp-dyneq", "amp-reflevel", "amp-dynvol", "amp-lfc"]
        labels = [app.query_one(f"#{i}").label for i in ids]
        assert labels == [
            "MultiEQ XT32",
            "Dynamic EQ",
            "Reference Level Offset",
            "Dynamic Volume",
            "Audyssey LFC",
        ]
        order = [w.id for w in app.query("ControlRow") if w.id in ids]
        assert order == ids  # on screen in the requested order


async def test_audyssey_lfc_toggle_and_unavailable_without_telnet_state(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(160, 40)) as pilot:
        await open_amp(pilot)
        avr = FakeAvr.instances[0]
        app.query_one("#amp-lfc").focus()
        await pilot.press("space")  # LFC is on in the fake
        await settle(pilot)
        assert avr.audyssey.calls == ["lfc_off"]
        avr.audyssey.lfc = None  # the receiver never reported it
        app.avr_panel.sync()
        assert app.query_one("#amp-lfc").disabled


async def test_avr_info_shows_audio_format_sample_rate_and_video_resolution(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(160, 40)) as pilot:
        await open_amp(pilot)
        avr = FakeAvr.instances[0]
        assert avr._device.api.requests[:2] == ["GetAudioInfo", "GetVideoInfo"]
        text = info_text(app)
        assert "Audio format AAC" in text
        assert "Sample rate 48 kHz" in text
        assert "Video input 3840x2160p 60Hz" in text
        assert "Video output 1920x1080p 60Hz" in text
        # what the receiver sent is also logged, for checking the mapping against a real amp
        assert any("INFO" in str(line) for line in app.query_one("#amp-log", RichLog).lines)


async def test_avr_info_accepts_tag_style_responses(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    monkeypatch.setattr(
        FakeApi,
        "__init__",
        lambda self: setattr(self, "style", "tag") or setattr(self, "requests", []),
    )
    app = HeosTui("fake")
    async with app.run_test(size=(160, 40)) as pilot:
        await open_amp(pilot)
        text = info_text(app)
        assert "Audio format AAC" in text and "Video input 3840x2160p 60Hz" in text


async def test_avr_info_survives_a_receiver_that_does_not_answer(fake, monkeypatch):
    from denonavr.exceptions import AvrInvalidResponseError

    use_fake_avr(monkeypatch)

    async def refuse(self, url, cmds):
        raise AvrInvalidResponseError("nope", url)

    monkeypatch.setattr(FakeApi, "async_post_appcommand", refuse)
    app = HeosTui("fake")
    async with app.run_test(size=(160, 40)) as pilot:
        await open_amp(pilot)
        text = info_text(app)
        assert "Audio format -" in text  # dashes, no crash


async def test_signal_events_trigger_a_refresh_of_the_info(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(160, 40)) as pilot:
        await open_amp(pilot)
        avr = FakeAvr.instances[0]
        before = len(avr._device.api.requests)
        avr.callbacks[0]("Main", "SI", "GAME")  # input changed
        await settle(pilot)
        assert len(avr._device.api.requests) > before


def info_text(app):
    """All AVR Info tiles as one whitespace-normalised string: 'Label value Label value ...'."""
    from heos_tui.info_tiles import InfoTile

    return " ".join(" ".join(str(t.render()).split()) for t in app.query(InfoTile))


def test_columns_for_width_gives_three_tiles_in_80_columns():
    assert columns_for(74) == 3  # an 80-column terminal after padding
    assert columns_for(160) == 4  # capped
    assert columns_for(30) == 1


async def test_avr_info_tiles_reflow_with_the_terminal_width(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    for width, columns in ((80, 3), (160, 4), (50, 2)):
        app = HeosTui("fake")
        async with app.run_test(size=(width, 40)) as pilot:
            await open_amp(pilot)
            grid = app.query_one("#amp-info")
            assert grid.styles.grid_size_columns == columns


async def test_info_tiles_sit_below_the_controls_and_not_in_a_column(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(80, 40)) as pilot:
        await open_amp(pilot)
        columns = app.query_one("#amp-columns")
        assert app.query_one("#amp-info") not in columns.query(
            "*"
        )  # full width, outside the columns
        assert app.query_one("#amp-info").region.y > app.query_one("#amp-lfc").region.y


async def test_quick_select_names_use_the_same_colour_as_avr_info_values(fake, monkeypatch):
    from heos_tui.controls import VALUE_STYLE
    from heos_tui.info_tiles import InfoTile

    use_fake_avr(monkeypatch)
    app = HeosTui("fake", avr_host="192.168.1.50")
    async with app.run_test(size=(160, 50)) as pilot:
        await open_amp(pilot)
        name = app.query_one("#amp-quick-1").render()
        assert name.plain.startswith("1  Apple TV")
        styled = [
            str(name.plain[s.start : s.end]) for s in name.spans if str(s.style) == VALUE_STYLE
        ]
        assert "Apple TV" in styled  # the name is coloured ...
        assert "1" not in styled  # ... the number is not
        tile = app.query_one(InfoTile)
        tile.set_value("AAC")
        assert any(
            str(s.style) == VALUE_STYLE for s in tile.render().spans
        )  # same style on the info value


async def test_telnet_log_explains_each_event(fake, monkeypatch):
    use_fake_avr(monkeypatch)
    app = HeosTui("fake")
    async with app.run_test(size=(160, 50)) as pilot:
        await open_amp(pilot)
        avr = FakeAvr.instances[0]
        avr.callbacks[0]("Main", "PS", "DEH HIGH")
        avr.callbacks[0]("All", "SY", "PANEL LOCK OFF")
        avr.callbacks[0]("Main", "SS", "INFSIGRESS O---")
        await settle(pilot)
        lines = [strip.text for strip in app.query_one("#amp-log", RichLog).lines]
        joined = "\n".join(lines)
        assert "Dialog enhancer: HIGH" in joined
        assert "Panel lock: OFF" in joined
        assert "INFSIGRESS O---" in joined and "not decoded" in joined


async def test_recalling_a_preset_rereads_every_value_until_the_receiver_settles(fake, monkeypatch):
    from heos_tui.controls import AmpSlider

    use_fake_avr(monkeypatch)
    monkeypatch.setattr("heos_tui.avr.PRESET_RELOAD_DELAYS", (0.0, 0.05, 0.1))
    app = HeosTui("fake")
    async with app.run_test(size=(160, 50)) as pilot:
        await open_amp(pilot)
        avr = FakeAvr.instances[0]
        baseline = {
            "updates": avr.update_calls,
            "audyssey": avr.audyssey_update_calls,
            "info": len(avr._device.api.requests),
            "dialog": avr.calls.count(("telnet", "PSDEH ?")),
        }

        def settle_in_steps(receiver):
            # the receiver applies the preset gradually: input first, then volume and the Audyssey mode
            seen = receiver.update_calls - baseline["updates"]
            if seen >= 1:
                receiver.input_func = "Phono"
            if seen >= 3:
                receiver.volume = -20.0
                receiver.multi_eq = "Flat"

        avr.on_update = settle_in_steps
        await pilot.press("u", "enter")  # recall Quick Select 1
        await settle(pilot)
        await pilot.pause(0.4)
        # everything was read again, more than once ...
        assert avr.update_calls - baseline["updates"] >= 3
        assert avr.audyssey_update_calls - baseline["audyssey"] >= 3
        assert (
            len(avr._device.api.requests) - baseline["info"] >= 6
        )  # audio + video info, three times
        assert (
            avr.calls.count(("telnet", "PSDEH ?")) - baseline["dialog"] >= 3
        )  # dialog enhancer too
        # ... and the screen shows the values that only arrived on the later reads
        assert app.query_one("#amp-input").value == "Phono"
        assert app.query_one("#amp-volume", AmpSlider).value == -20.0
        assert app.query_one("#amp-multieq").value == "Flat"
