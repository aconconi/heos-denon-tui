"""Play queue commands."""

from typing import Annotated

import typer

from ..common import State, resolve_player, run
from ..output import emit, queue_table


def register(app: typer.Typer) -> None:
    queue = typer.Typer(help="Inspect and edit the play queue.", no_args_is_help=True)
    app.add_typer(queue, name="queue")

    @queue.command("list")
    def queue_list(
        ctx: typer.Context,
        start: Annotated[
            int | None, typer.Option(min=0, help="First record index (0-based).")
        ] = None,
        end: Annotated[int | None, typer.Option(min=0, help="Last record index.")] = None,
    ) -> None:
        """List queue items (the device returns at most 100 per call)."""
        if (start is None) != (end is None):
            raise typer.BadParameter("--start and --end must be used together")

        async def go(heos, s: State) -> None:
            emit(s, await (await resolve_player(heos, s.player)).get_queue(start, end), queue_table)

        run(ctx, go)

    @queue.command("play")
    def queue_play(ctx: typer.Context, qid: int) -> None:
        """Play the queue item QID."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).play_queue(qid)

        run(ctx, go)

    @queue.command("remove")
    def queue_remove(ctx: typer.Context, qids: Annotated[list[int], typer.Argument()]) -> None:
        """Remove the given queue items."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).remove_from_queue(qids)

        run(ctx, go)

    @queue.command("clear")
    def queue_clear(ctx: typer.Context) -> None:
        """Empty the queue."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).clear_queue()

        run(ctx, go)

    @queue.command("save")
    def queue_save(ctx: typer.Context, name: str) -> None:
        """Save the queue as a HEOS playlist called NAME."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).save_queue(name)

        run(ctx, go)

    @queue.command("move")
    def queue_move(
        ctx: typer.Context,
        destination: Annotated[int, typer.Argument(help="Destination queue id.")],
        qids: Annotated[list[int], typer.Argument(help="Queue ids to move.")],
    ) -> None:
        """Move queue items to DESTINATION."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).move_queue_item(qids, destination)

        run(ctx, go)
