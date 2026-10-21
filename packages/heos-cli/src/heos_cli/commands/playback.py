"""Playback, volume, mute, play mode, and QuickSelect commands."""

from enum import StrEnum
from typing import Annotated

import typer
from pyheos import PlayState, RepeatType

from ..common import State, resolve_player, run
from ..output import console, emit, now_playing_line, players_table


class MuteAction(StrEnum):
    on = "on"
    off = "off"
    toggle = "toggle"


class Repeat(StrEnum):
    off = "off"
    all = "all"
    one = "one"


_REPEAT = {Repeat.off: RepeatType.OFF, Repeat.all: RepeatType.ON_ALL, Repeat.one: RepeatType.ON_ONE}

Level = Annotated[int | None, typer.Argument(min=0, max=100, help="Volume 0-100; omit to show.")]
Step = Annotated[int, typer.Argument(min=1, max=10, help="Step size 1-10.")]


def register(app: typer.Typer) -> None:
    @app.command()
    def players(ctx: typer.Context) -> None:
        """List players."""

        async def go(heos, s: State) -> None:
            emit(s, list((await heos.get_players()).values()), players_table)

        run(ctx, go)

    @app.command()
    def status(ctx: typer.Context) -> None:
        """Show play state, volume, mute and now-playing for the player."""

        async def go(heos, s: State) -> None:
            p = await resolve_player(heos, s.player)
            data = {
                "player_id": p.player_id,
                "state": p.state,
                "volume": p.volume,
                "mute": p.is_muted,
                "now_playing": p.now_playing_media,
            }

            def render(d: dict) -> None:
                muted = " (muted)" if d["mute"] else ""
                console.print(f"[bold]{d['state'].value}[/bold]  volume {d['volume']}{muted}")
                console.print(now_playing_line(d["now_playing"]))

            emit(s, data, render)

        run(ctx, go)

    def _transport(name: str, state: PlayState) -> None:
        def command(ctx: typer.Context) -> None:
            async def go(heos, s: State) -> None:
                await (await resolve_player(heos, s.player)).set_state(state)

            run(ctx, go)

        command.__doc__ = f"Set the player to '{state.value}'."
        app.command(name)(command)

    _transport("play", PlayState.PLAY)
    _transport("pause", PlayState.PAUSE)
    _transport("stop", PlayState.STOP)

    @app.command()
    def next(ctx: typer.Context) -> None:
        """Skip to the next track."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).play_next()

        run(ctx, go)

    @app.command()
    def prev(ctx: typer.Context) -> None:
        """Go to the previous track."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).play_previous()

        run(ctx, go)

    @app.command()
    def volume(ctx: typer.Context, level: Level = None) -> None:
        """Show the volume, or set it to LEVEL."""

        async def go(heos, s: State) -> None:
            p = await resolve_player(heos, s.player)
            if level is None:
                emit(
                    s,
                    {"player_id": p.player_id, "volume": p.volume},
                    lambda d: console.print(d["volume"]),
                )
            else:
                await p.set_volume(level)

        run(ctx, go)

    @app.command()
    def up(ctx: typer.Context, step: Step = 5) -> None:
        """Raise the volume by STEP (default 5)."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).volume_up(step)

        run(ctx, go)

    @app.command()
    def down(ctx: typer.Context, step: Step = 5) -> None:
        """Lower the volume by STEP (default 5)."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).volume_down(step)

        run(ctx, go)

    @app.command()
    def mute(
        ctx: typer.Context, action: Annotated[MuteAction | None, typer.Argument()] = None
    ) -> None:
        """Show the mute state, or set it with on / off / toggle."""

        async def go(heos, s: State) -> None:
            p = await resolve_player(heos, s.player)
            if action is None:
                emit(
                    s,
                    {"player_id": p.player_id, "mute": p.is_muted},
                    lambda d: console.print("on" if d["mute"] else "off"),
                )
            elif action is MuteAction.toggle:
                await p.toggle_mute()
            else:
                await p.set_mute(action is MuteAction.on)

        run(ctx, go)

    @app.command()
    def mode(
        ctx: typer.Context,
        repeat: Annotated[Repeat | None, typer.Option(help="Repeat mode.")] = None,
        shuffle: Annotated[bool | None, typer.Option("--shuffle/--no-shuffle")] = None,
    ) -> None:
        """Show the repeat/shuffle mode, or change it."""

        async def go(heos, s: State) -> None:
            p = await resolve_player(heos, s.player)
            if repeat is None and shuffle is None:
                data = {"repeat": p.repeat, "shuffle": p.shuffle}
                emit(
                    s,
                    data,
                    lambda d: console.print(
                        f"repeat={d['repeat'].value} shuffle={'on' if d['shuffle'] else 'off'}"
                    ),
                )
                return
            await p.set_play_mode(
                _REPEAT[repeat] if repeat else p.repeat,
                p.shuffle if shuffle is None else shuffle,
            )

        run(ctx, go)

    quickselect = typer.Typer(
        help="QuickSelect slots (LS AVR / HEOS Bar only).", no_args_is_help=True
    )
    app.add_typer(quickselect, name="quickselect")

    @quickselect.command("list")
    def qs_list(ctx: typer.Context) -> None:
        """List QuickSelect slots."""

        async def go(heos, s: State) -> None:
            slots = await (await resolve_player(heos, s.player)).get_quick_selects()
            emit(s, slots, lambda d: [console.print(f"{i}: {name}") for i, name in d.items()])

        run(ctx, go)

    @quickselect.command("play")
    def qs_play(ctx: typer.Context, slot: Annotated[int, typer.Argument(min=1, max=6)]) -> None:
        """Play the source stored in SLOT."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).play_quick_select(slot)

        run(ctx, go)

    @quickselect.command("set")
    def qs_set(ctx: typer.Context, slot: Annotated[int, typer.Argument(min=1, max=6)]) -> None:
        """Store the currently playing source in SLOT."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).set_quick_select(slot)

        run(ctx, go)
