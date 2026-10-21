"""``heos`` command-line client."""

from typing import Annotated

import typer

from .commands import browse, groups, playback, queue, system
from .common import State

app = typer.Typer(
    help="Control Denon HEOS devices. Use -H/--host (or HEOS_HOST) and -p/--player (or HEOS_PLAYER).",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def global_options(
    ctx: typer.Context,
    host: Annotated[
        str | None,
        typer.Option(
            "--host", "-H", envvar="HEOS_HOST", help="Device IP/hostname; discovered if omitted."
        ),
    ] = None,
    player: Annotated[
        str | None, typer.Option("--player", "-p", envvar="HEOS_PLAYER", help="Player name or pid.")
    ] = None,
    timeout: Annotated[float, typer.Option(help="Seconds to wait for each command.")] = 10.0,
    json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    ctx.obj = State(host=host, timeout=timeout, json=json, player=player)


for module in (playback, groups, queue, browse, system):
    module.register(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
