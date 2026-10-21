"""CLI tests against an in-process fake device (socketpair, no TCP port needed)."""

import asyncio
import json
import socket
from urllib.parse import parse_qsl, urlsplit

import pytest
from heos_cli.main import app
from typer.testing import CliRunner

PLAYERS = [
    {"name": "Kitchen", "pid": 1, "model": "HEOS 1", "version": "3.50.0", "network": "wifi"},
    {
        "name": "Living Room",
        "pid": 2,
        "model": "HEOS 7",
        "version": "3.50.0",
        "network": "wired",
        "gid": 2,
    },
]


def _ok(command, message="", payload=None, options=None):
    out = {"heos": {"command": command, "result": "success", "message": message}}
    if payload is not None:
        out["payload"] = payload
    if options is not None:
        out["options"] = options
    return out


class Device(list):
    """Commands received by the fake as (command, params) pairs; ``state`` is data it serves."""

    def __init__(self):
        super().__init__()
        self.state = {"players": PLAYERS}

    def last(self, command):
        return next(params for cmd, params in reversed(self) if cmd == command)


@pytest.fixture
def device(monkeypatch):
    sent = Device()

    def reply(command, query):
        pid = dict(parse_qsl(query)).get("pid", "1")
        return {
            "player/get_players": _ok(command, payload=sent.state["players"]),
            "player/get_volume": _ok(command, f"pid={pid}&level=25"),
            "player/get_play_state": _ok(command, f"pid={pid}&state=play"),
            "player/get_mute": _ok(command, f"pid={pid}&state=off"),
            "player/get_play_mode": _ok(command, f"pid={pid}&repeat=off&shuffle=off"),
            "player/get_now_playing_media": _ok(
                command,
                f"pid={pid}",
                payload={"type": "song", "song": "S", "artist": "A", "album": "B", "sid": 1024},
            ),
            "group/get_groups": _ok(
                command,
                payload=[
                    {
                        "name": "G",
                        "gid": "2",
                        "players": [{"name": "Living Room", "pid": 2, "role": "leader"}],
                    }
                ],
            ),
            "group/get_volume": _ok(command, "gid=2&level=30"),
            "group/get_mute": _ok(command, "gid=2&state=off"),
            "browse/get_music_sources": _ok(
                command,
                payload=[
                    {
                        "name": "Local Music",
                        "sid": 1024,
                        "type": "heos_service",
                        "image_url": "",
                        "available": "true",
                    }
                ],
            ),
            "browse/browse": [
                _ok(command, "command under process&sid=13"),
                _ok(
                    command,
                    "sid=13&returned=1&count=1",
                    payload=[
                        {
                            "name": "Top Albums",
                            "type": "container",
                            "container": "yes",
                            "playable": "no",
                            "image_url": "",
                            "cid": "TopAlbums",
                            "mid": "x",
                        }
                    ],
                ),
            ],
        }.get(command, _ok(command, query))

    async def serve(reader, writer):
        while line := await reader.readline():
            parts = urlsplit(line.decode().strip())
            command = parts.netloc + parts.path
            sent.append((command, dict(parse_qsl(parts.query))))
            await asyncio.sleep(
                0.002
            )  # real networks have latency; pyheos drops replies that beat it
            replies = reply(command, parts.query)
            for r in [replies] if isinstance(replies, dict) else replies:
                writer.write(json.dumps(r).encode() + b"\r\n")
            await writer.drain()

    real_open = asyncio.open_connection
    tasks: set = set()  # asyncio holds only weak references to tasks

    async def open_connection(host=None, port=None, **kwargs):
        client_sock, server_sock = socket.socketpair()
        reader, writer = await real_open(sock=server_sock)
        task = asyncio.create_task(serve(reader, writer))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return await real_open(sock=client_sock)

    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    monkeypatch.delenv("HEOS_PLAYER", raising=False)
    return sent


def invoke(*args):
    return CliRunner().invoke(app, ["-H", "fake", *args])


def test_players_table(device):
    result = invoke("players")
    assert result.exit_code == 0, result.output
    assert "Kitchen" in result.output and "Living Room" in result.output


def test_players_json(device):
    result = invoke("--json", "players")
    assert [p["player_id"] for p in json.loads(result.output)] == [1, 2]


def test_volume_set_resolves_player_by_partial_name(device):
    result = invoke("-p", "living", "volume", "40")
    assert result.exit_code == 0, result.output
    assert device.last("player/set_volume") == {"pid": "2", "level": "40"}


def test_multiple_players_without_choice_is_an_error(device):
    result = invoke("volume")
    assert result.exit_code != 0
    assert "several players" in result.output


def test_single_player_is_used_implicitly(device):
    device.state["players"] = PLAYERS[:1]
    result = invoke("volume")
    assert result.exit_code == 0 and result.output.strip() == "25"


def test_status_json(device):
    result = invoke("--json", "-p", "1", "status")
    data = json.loads(result.output)
    assert (data["state"], data["volume"], data["mute"]) == ("play", 25, False)
    assert data["now_playing"]["song"] == "S"


def test_group_volume_and_range_validation(device):
    assert invoke("group", "volume", "G", "30").exit_code == 0
    assert device.last("group/set_volume") == {"gid": "2", "level": "30"}
    assert invoke("volume", "101").exit_code != 0


def test_queue_remove_and_transport(device):
    assert invoke("-p", "1", "queue", "remove", "4", "5").exit_code == 0
    assert device.last("player/remove_from_queue") == {"pid": "1", "qid": "4,5"}
    assert invoke("-p", "2", "pause").exit_code == 0
    assert device.last("player/set_play_state") == {"pid": "2", "state": "pause"}


def test_browse_waits_for_the_real_reply_after_command_under_process(device):
    result = invoke("browse", "13")
    assert result.exit_code == 0, result.output
    assert "Top Albums" in result.output  # not the empty interim reply


def test_raw_prints_full_response(device):
    result = invoke("raw", "player/get_volume", "pid=1")
    assert json.loads(result.output)["message"] == {"pid": "1", "level": "25"}
