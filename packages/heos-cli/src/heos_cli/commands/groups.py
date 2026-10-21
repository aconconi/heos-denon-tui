"""Group commands."""

from enum import StrEnum
from typing import Annotated

import typer

from ..common import State, resolve_group, resolve_player, run
from ..output import console, emit, groups_table
from .playback import Level, MuteAction, Step


class Direction(StrEnum):
    up = "up"
    down = "down"


def register(app: typer.Typer) -> None:
    group = typer.Typer(help="Manage speaker groups.", no_args_is_help=True)
    app.add_typer(group, name="group")

    @app.command()
    def groups(ctx: typer.Context) -> None:
        """List groups."""

        async def go(heos, s: State) -> None:
            names = {p.player_id: p.name for p in (await heos.get_players()).values()}
            emit(s, list((await heos.get_groups()).values()), lambda gs: groups_table(gs, names))

        run(ctx, go)

    @group.command("list")
    def group_list(ctx: typer.Context) -> None:
        """List groups."""
        groups(ctx)

    @group.command("create")
    def group_create(
        ctx: typer.Context,
        players: Annotated[
            list[str], typer.Argument(help="Player names/ids; the first is the leader.")
        ],
    ) -> None:
        """Create a group, or replace the members of the leader's existing group."""

        async def go(heos, s: State) -> None:
            ids = [(await resolve_player(heos, p)).player_id for p in players]
            await heos.create_group(ids[0], ids[1:])

        run(ctx, go)

    @group.command("ungroup")
    def group_ungroup(
        ctx: typer.Context, leader: Annotated[str, typer.Argument(help="Leader player.")]
    ) -> None:
        """Dissolve the group led by LEADER."""

        async def go(heos, s: State) -> None:
            await heos.remove_group((await resolve_player(heos, leader)).player_id)

        run(ctx, go)

    @group.command("volume")
    def group_volume(ctx: typer.Context, name: str, level: Level = None) -> None:
        """Show a group's volume, or set it to LEVEL."""

        async def go(heos, s: State) -> None:
            g = await resolve_group(heos, name)
            if level is None:
                emit(
                    s,
                    {"group_id": g.group_id, "volume": g.volume},
                    lambda d: console.print(d["volume"]),
                )
            else:
                await heos.set_group_volume(g.group_id, level)

        run(ctx, go)

    @group.command("step")
    def group_step(ctx: typer.Context, name: str, direction: Direction, step: Step = 5) -> None:
        """Raise or lower a group's volume by STEP."""

        async def go(heos, s: State) -> None:
            g = await resolve_group(heos, name)
            await (heos.group_volume_up if direction is Direction.up else heos.group_volume_down)(
                g.group_id, step
            )

        run(ctx, go)

    @group.command("mute")
    def group_mute(
        ctx: typer.Context, name: str, action: Annotated[MuteAction | None, typer.Argument()] = None
    ) -> None:
        """Show a group's mute state, or set it with on / off / toggle."""

        async def go(heos, s: State) -> None:
            g = await resolve_group(heos, name)
            if action is None:
                emit(
                    s,
                    {"group_id": g.group_id, "mute": g.is_muted},
                    lambda d: console.print("on" if d["mute"] else "off"),
                )
            elif action is MuteAction.toggle:
                await heos.group_toggle_mute(g.group_id)
            else:
                await heos.group_set_mute(g.group_id, action is MuteAction.on)

        run(ctx, go)
