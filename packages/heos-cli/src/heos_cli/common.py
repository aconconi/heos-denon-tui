"""Shared CLI plumbing: global state, running async code, resolving players and groups."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import typer
from heos_discovery import discover
from pyheos import Heos, HeosError, HeosGroup, HeosOptions, HeosPlayer

from .output import err_console


@dataclass
class State:
    host: str | None = None
    timeout: float = 10.0
    json: bool = False
    player: str | None = None


def run(
    ctx: typer.Context,
    fn: Callable[[Heos, State], Awaitable[None]],
    *,
    events: bool = False,
) -> None:
    """Connect, await ``fn(heos, state)``, and turn library errors into exit code 1.

    One-shot commands don't need change events or heart beats, so both are off unless
    ``events`` is set.
    """
    state: State = ctx.obj
    try:
        asyncio.run(_run(state, fn, events))
    except (HeosError, ValueError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        pass


async def _run(state: State, fn: Callable[[Heos, State], Awaitable[None]], events: bool) -> None:
    host = state.host
    if host is None:
        err_console.print("No --host given, searching for a HEOS device...")
        found = await discover(timeout=5, stop_after_first=True)
        if not found:
            raise typer.BadParameter("no HEOS device found; pass --host or set HEOS_HOST")
        host = found[0].host
        err_console.print(f"Using {host}")
    heos = Heos(HeosOptions(host, timeout=state.timeout, events=events, heart_beat=events))
    await heos.connect()
    try:
        await fn(heos, state)
    finally:
        await heos.disconnect()


async def resolve_player(heos: Heos, ident: str | None) -> HeosPlayer:
    """Find a player by id or (partial, case-insensitive) name; the only player if none given."""
    players = list((await heos.get_players()).values())
    if ident is None:
        if len(players) == 1:
            return players[0]
        names = ", ".join(p.name for p in players)
        raise typer.BadParameter(f"several players found ({names}); choose one with --player")
    if ident.lstrip("-").isdigit():
        for p in players:
            if p.player_id == int(ident):
                return p
    exact = [p for p in players if p.name.lower() == ident.lower()]
    partial = [p for p in players if ident.lower() in p.name.lower()]
    matches = exact or partial
    if len(matches) != 1:
        known = ", ".join(f"{p.name} ({p.player_id})" for p in players)
        kind = "ambiguous" if matches else "unknown"
        raise typer.BadParameter(f"{kind} player {ident!r}; known: {known}")
    return matches[0]


async def player_id(heos: Heos, state: State, override: str | None = None) -> int:
    return (await resolve_player(heos, override or state.player)).player_id


async def resolve_group(heos: Heos, ident: str) -> HeosGroup:
    """Find a group by id or name, or the group a named player belongs to."""
    groups = list((await heos.get_groups()).values())
    players = (await heos.get_players()).values()
    if ident.lstrip("-").isdigit():
        for g in groups:
            if g.group_id == int(ident):
                return g
    for g in groups:
        member_names = {p.name.lower() for p in players if p.player_id in g.member_player_ids}
        if g.name.lower() == ident.lower() or ident.lower() in member_names:
            return g
    known = ", ".join(f"{g.name} ({g.group_id})" for g in groups) or "none"
    raise typer.BadParameter(f"unknown group {ident!r}; known: {known}")
