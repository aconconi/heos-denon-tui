"""Drive the TUI with Textual's pilot against the fake HEOS device in conftest.py."""

from conftest import cell, settle
from heos_tui.app import HeosTui
from heos_tui.widgets import NowPlayingBar, QueueView
from textual.widgets import DataTable, TabbedContent


async def test_startup_shows_rooms_now_playing_and_queue(fake):
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        assert app.query_one("#players", DataTable).row_count == 2
        assert cell(app, "#players", 1, "name") == "Kitchen"
        assert app.query_one(QueueView).row_count == 2
        assert str(app.query_one(NowPlayingBar).render()).count("Teardrop") == 1
        assert fake.has("system/register_for_change_events", enable="on")
        assert "not signed in" in app.sub_title


async def test_transport_and_volume_keys(fake):
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await pilot.press("space", "plus", "minus", "m", "n", "p", "s", "r")
        await settle(pilot)
        assert fake.has("player/set_play_state", pid="1", state="pause")  # was playing
        assert fake.has("player/volume_up", pid="1", step="5")
        assert fake.has("player/volume_down", pid="1", step="5")
        assert fake.has("player/toggle_mute", pid="1")
        assert fake.has("player/play_next", pid="1")
        assert fake.has("player/play_previous", pid="1")
        assert fake.has("player/set_play_mode", pid="1", repeat="off", shuffle="on")
        assert fake.has("player/set_play_mode", pid="1", repeat="on_all", shuffle="off")


async def test_events_update_room_list(fake):
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await fake.push("event/player_volume_changed", "pid=1&level=40&mute=on")
        await fake.push("event/player_state_changed", "pid=1&state=pause")
        await settle(pilot)
        assert "40" in cell(app, "#players", 1, "vol")
        assert cell(app, "#players", 1, "state") == "⏸"


async def test_progress_event_with_decimals_updates_bar(fake):
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await fake.push(
            "event/player_now_playing_progress", "pid=1&cur_pos=61000.0&duration=240000"
        )
        await settle(pilot)
        assert "1:01" in str(app.query_one(NowPlayingBar).render())


async def test_enter_in_queue_plays_item(fake):
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        app.query_one(QueueView).focus()
        await pilot.press("down", "enter")
        await settle(pilot)
        assert fake.has("player/play_queue", pid="1", qid="2")


async def test_browse_sources_and_signed_out_service(fake):
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await pilot.press("3")
        await settle(pilot)
        assert app.query_one("#browse-table", DataTable).row_count == 2
        await pilot.press("down", "enter")  # Amazon Music, not available
        await settle(pilot)
        assert not fake.has("browse/browse", sid="13")
        await pilot.press("up", "enter")  # Local Music
        await settle(pilot)
        assert fake.has("browse/browse", sid="1024")
        assert (
            app.query_one("#browse-table", DataTable).row_count == 1
        )  # the real reply, not the interim one


async def test_account_sign_in(fake):
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await pilot.press("l")
        await pilot.pause(0.2)
        await pilot.press(*"me@example.com", "enter", *"secret", "enter")
        await settle(pilot)
        assert fake.has("system/sign_in", un="me@example.com", pw="secret")
        assert "me@example.com" in app.sub_title


async def test_starts_on_queue_tab_not_stolen_by_focus(fake):
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        assert app.query_one(TabbedContent).active == "queue"


async def test_rooms_tab_lists_rooms_and_switching_rooms_changes_player(fake):
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        assert app.current_pid == 1
        await pilot.press("right_square_bracket")  # next room, from any tab
        await settle(pilot)
        assert app.current_pid == 2
        assert "Room: Office" in str(app.query_one(NowPlayingBar).render())
        await pilot.press("space")  # transport now targets the other room
        await settle(pilot)
        assert fake.has("player/set_play_state", pid="2", state="pause")
        await pilot.press("left_square_bracket")
        await settle(pilot)
        assert app.current_pid == 1


async def test_enter_on_a_room_opens_its_queue(fake):
    app = HeosTui("fake")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await pilot.press("1")
        await settle(pilot)
        assert app.query_one(TabbedContent).active == "rooms"
        await pilot.press("down", "enter")
        await settle(pilot)
        assert app.current_pid == 2
        assert app.query_one(TabbedContent).active == "queue"
