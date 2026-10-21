"""Shared fake HEOS device for the TUI tests (in-process, socketpair, no TCP port needed)."""

import asyncio
import json
import socket
from urllib.parse import parse_qsl, urlsplit

import pytest
from textual.widgets import DataTable


def ok(command, message="", payload=None, options=None):
    out = {"heos": {"command": command, "result": "success", "message": message}}
    if payload is not None:
        out["payload"] = payload
    if options is not None:
        out["options"] = options
    return out


class Fake:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []
        self.writers = []
        self.tasks: set = set()  # asyncio holds only weak references to tasks

    def has(self, command, **params):
        return any(
            c == command and all(p.get(k) == v for k, v in params.items()) for c, p in self.sent
        )

    def reply(self, c, q):
        pid = dict(parse_qsl(q)).get("pid", "1")
        table = {
            "system/check_account": ok(c, "signed_out"),
            "player/get_players": ok(
                c,
                payload=[
                    {
                        "name": "Kitchen",
                        "ip": "192.168.1.50",
                        "pid": 1,
                        "model": "HEOS 1",
                        "version": "3.50.0",
                        "network": "wifi",
                    },
                    {
                        "name": "Office",
                        "pid": 2,
                        "model": "HEOS 3",
                        "version": "3.50.0",
                        "network": "wired",
                    },
                ],
            ),
            "player/get_play_state": ok(c, f"pid={pid}&state=play"),
            "player/get_volume": ok(c, f"pid={pid}&level=25"),
            "player/get_mute": ok(c, f"pid={pid}&state=off"),
            "player/get_play_mode": ok(c, f"pid={pid}&repeat=off&shuffle=off"),
            "player/get_now_playing_media": ok(
                c,
                f"pid={pid}",
                payload={
                    "type": "song",
                    "song": "Teardrop",
                    "artist": "Massive Attack",
                    "album": "Mezzanine",
                    "qid": 2,
                    "sid": 1024,
                },
                options=[{"play": [{"id": 19, "name": "Add to HEOS Favorites"}]}],
            ),
            "player/get_queue": ok(
                c,
                payload=[
                    {
                        "song": "Angel",
                        "artist": "Massive Attack",
                        "album": "Mezzanine",
                        "qid": 1,
                        "image_url": "",
                        "mid": "m1",
                        "album_id": "a",
                    },
                    {
                        "song": "Teardrop",
                        "artist": "Massive Attack",
                        "album": "Mezzanine",
                        "qid": 2,
                        "image_url": "",
                        "mid": "m2",
                        "album_id": "a",
                    },
                ],
            ),
            "browse/get_music_sources": ok(
                c,
                payload=[
                    {
                        "name": "Local Music",
                        "sid": 1024,
                        "type": "heos_service",
                        "image_url": "",
                        "available": "true",
                    },
                    {
                        "name": "Amazon Music",
                        "sid": 13,
                        "type": "music_service",
                        "image_url": "",
                        "available": "false",
                    },
                ],
            ),
            "browse/browse": [
                ok(c, "command under process&sid=1024"),  # as sent by a real device
                ok(
                    c,
                    "sid=1024&returned=1&count=1",
                    payload=[
                        {
                            "name": "Artists",
                            "type": "container",
                            "container": "yes",
                            "playable": "no",
                            "image_url": "",
                            "cid": "Artists",
                            "mid": "x",
                        }
                    ],
                ),
            ],
            "player/get_quickselects": ok(
                c,
                f"pid={pid}",
                payload=[
                    {"id": 1, "name": "Apple TV"},
                    {"id": 2, "name": "Radio"},
                    {"id": 3, "name": "Vinyl"},
                    {"id": 4, "name": "Game console"},
                ],
            ),
            "system/sign_in": ok(c, "signed_in&un=me@example.com"),
        }
        return table.get(c, ok(c, q))

    async def serve(self, reader, writer):
        self.writers.append(writer)
        while line := await reader.readline():
            parts = urlsplit(line.decode().strip())
            command = parts.netloc + parts.path
            self.sent.append((command, dict(parse_qsl(parts.query))))
            await asyncio.sleep(0.002)  # real networks have latency
            replies = self.reply(command, parts.query)
            for r in [replies] if isinstance(replies, dict) else replies:
                writer.write(json.dumps(r).encode() + b"\r\n")
            await writer.drain()

    async def push(self, command, message):
        for w in self.writers:
            w.write(
                json.dumps({"heos": {"command": command, "message": message}}).encode() + b"\r\n"
            )
            await w.drain()


@pytest.fixture
def fake(monkeypatch):
    device = Fake()
    real_open = asyncio.open_connection

    async def open_connection(host=None, port=None, **kwargs):
        client_sock, server_sock = socket.socketpair()
        reader, writer = await real_open(sock=server_sock)
        task = asyncio.create_task(device.serve(reader, writer))
        device.tasks.add(task)
        task.add_done_callback(device.tasks.discard)
        return await real_open(sock=client_sock)

    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    return device


async def settle(pilot):
    await pilot.pause(0.3)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause(0.1)


def cell(app, table_id, row, column):
    return str(app.query_one(table_id, DataTable).get_cell(str(row), column))


class NoAvr:
    """Default stand-in for DenonAVR: the host is not a Denon AVR (no real network in tests)."""

    def __init__(self, *args, **kwargs):
        pass

    async def async_setup(self):
        from denonavr.exceptions import AvrNetworkError

        raise AvrNetworkError("not an AVR", "setup")


@pytest.fixture(autouse=True)
def no_avr(monkeypatch):
    monkeypatch.setattr("heos_tui.app.DenonAVR", NoAvr)


@pytest.fixture(autouse=True)
def quick_preset_reload(monkeypatch):
    """The real delays wait seconds for the receiver to settle; tests don't need to."""
    monkeypatch.setattr("heos_tui.avr.PRESET_RELOAD_DELAYS", (0.0, 0.05, 0.1))
