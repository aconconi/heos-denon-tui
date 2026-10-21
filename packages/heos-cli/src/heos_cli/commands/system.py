"""Discovery, account, events, firmware and raw-command commands."""

import asyncio
import json
from typing import Annotated

import typer
from heos_discovery import discover
from pyheos import Heos, SignalType
from pyheos.message import HeosCommand

from ..common import State, resolve_player, run
from ..output import console, emit, err_console, to_jsonable


def register(app: typer.Typer) -> None:
    @app.command("discover")
    def discover_cmd(
        ctx: typer.Context,
        timeout: Annotated[float, typer.Option(help="Seconds to wait for replies.")] = 3.0,
    ) -> None:
        """Find HEOS devices on the network (SSDP)."""
        state: State = ctx.obj
        try:
            devices = asyncio.run(discover(timeout))
        except OSError as exc:
            err_console.print(f"[red]error:[/red] discovery failed: {exc}")
            raise typer.Exit(1) from None
        emit(
            state,
            devices,
            lambda ds: (
                [console.print(f"{d.host}  {d.server}") for d in ds] or console.print("none found")
            ),
        )

    @app.command()
    def watch(ctx: typer.Context) -> None:
        """Print change events until interrupted (Ctrl-C)."""

        async def go(heos: Heos, s: State) -> None:
            lines: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

            async def on_player(player_id: int, event: str) -> None:
                lines.put_nowait((event, {"player_id": player_id}))

            async def on_controller(event: str, data: object) -> None:
                lines.put_nowait((event, {}))

            heos.dispatcher.connect(SignalType.PLAYER_EVENT, on_player)
            heos.add_on_controller_event(on_controller)
            await heos.get_players()  # events are only reported for loaded players
            err_console.print("Listening for events, Ctrl-C to stop.")
            players = heos.players
            while True:
                event, info = await lines.get()
                pid = info.get("player_id") if isinstance(info, dict) else None
                player = players.get(pid) if pid is not None else None
                if s.json:
                    print(json.dumps({"event": event, **to_jsonable(info)}), flush=True)
                elif player:
                    console.print(
                        f"{event}  {player.name}  state={player.state}  vol={player.volume}"
                    )
                else:
                    console.print(event)

        run(ctx, go, events=True)

    @app.command()
    def account(ctx: typer.Context) -> None:
        """Show the signed-in HEOS account."""

        async def go(heos: Heos, s: State) -> None:
            user = heos.signed_in_username
            emit(s, {"signed_in": user is not None, "username": user},
                 lambda d: console.print(f"signed in as {user}" if user else "signed out"))  # fmt: skip

        run(ctx, go)

    @app.command()
    def signin(
        ctx: typer.Context,
        username: str,
        password: Annotated[
            str, typer.Option(prompt=True, hide_input=True, envvar="HEOS_PASSWORD")
        ],
    ) -> None:
        """Sign in to a HEOS account (the password is prompted, not taken as an argument)."""

        async def go(heos: Heos, s: State) -> None:
            console.print(f"signed in as {await heos.sign_in(username, password)}")

        run(ctx, go)

    @app.command()
    def signout(ctx: typer.Context) -> None:
        """Sign out of the HEOS account."""

        async def go(heos: Heos, s: State) -> None:
            await heos.sign_out()

        run(ctx, go)

    @app.command("check-update")
    def check_update(ctx: typer.Context) -> None:
        """Check whether a firmware update is available for the player."""

        async def go(heos: Heos, s: State) -> None:
            available = await (await resolve_player(heos, s.player)).check_update()
            emit(s, {"update_available": available},
                 lambda d: console.print("update available" if available else "up to date"))  # fmt: skip

        run(ctx, go)

    @app.command()
    def reboot(
        ctx: typer.Context, yes: Annotated[bool, typer.Option("--yes", "-y")] = False
    ) -> None:
        """Reboot the speaker the CLI connects to."""
        if not yes:
            typer.confirm("Reboot the HEOS device?", abort=True)

        async def go(heos: Heos, s: State) -> None:
            await heos.reboot()

        run(ctx, go)

    @app.command()
    def raw(
        ctx: typer.Context,
        command: Annotated[str, typer.Argument(help="e.g. player/get_volume")],
        params: Annotated[
            list[str] | None, typer.Argument(help="key=value pairs, e.g. pid=1")
        ] = None,
    ) -> None:
        """Send any HEOS command and print the full response (for debugging).

        Uses pyheos' internal connection, so it may need updating after a pyheos upgrade.
        """
        pairs = {}
        for p in params or []:
            key, sep, value = p.partition("=")
            if not sep:
                raise typer.BadParameter(f"expected key=value, got {p!r}")
            pairs[key] = value

        async def go(heos: Heos, s: State) -> None:
            message = await heos._connection.command(
                HeosCommand(command.removeprefix("heos://"), pairs)
            )
            print(json.dumps({
                "command": message.command, "result": message.result, "message": message.message,
                "payload": message.payload, "options": message.options,
            }, indent=2))  # fmt: skip

        run(ctx, go)
