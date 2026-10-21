"""Browse, search and play-media commands."""

from enum import StrEnum
from typing import Annotated

import typer
from pyheos import AddCriteriaType
from pyheos.const import MUSIC_SOURCE_PLAYLISTS

from ..common import State, resolve_player, run
from ..output import console, criteria_table, emit, media_table, sources_table


class AddMode(StrEnum):
    play_now = "play-now"
    play_next = "play-next"
    add_to_end = "add-to-end"
    replace_and_play = "replace-and-play"


_ADD = {
    AddMode.play_now: AddCriteriaType.PLAY_NOW,
    AddMode.play_next: AddCriteriaType.PLAY_NEXT,
    AddMode.add_to_end: AddCriteriaType.ADD_TO_END,
    AddMode.replace_and_play: AddCriteriaType.REPLACE_AND_PLAY,
}

Start = Annotated[int | None, typer.Option(min=0, help="First record index (0-based).")]
End = Annotated[int | None, typer.Option(min=0, help="Last record index.")]


def _check_range(start: int | None, end: int | None) -> None:
    if (start is None) != (end is None):
        raise typer.BadParameter("--start and --end must be used together")


def _render_result(result) -> None:
    media_table(result.items)
    total = result.count or "unknown"
    console.print(f"[dim]{result.returned} returned, {total} total[/dim]")
    for o in getattr(result, "options", []):
        console.print(f"[dim]option {o.id} ({o.context}): {o.name}[/dim]")


def register(app: typer.Typer) -> None:
    @app.command()
    def sources(ctx: typer.Context) -> None:
        """List music sources (streaming services, local servers, inputs, favorites...)."""

        async def go(heos, s: State) -> None:
            emit(s, list((await heos.get_music_sources()).values()), sources_table)

        run(ctx, go)

    @app.command()
    def browse(
        ctx: typer.Context,
        sid: Annotated[int, typer.Argument(help="Source id.")],
        cid: Annotated[
            str | None, typer.Argument(help="Container id from a previous browse.")
        ] = None,
        start: Start = None,
        end: End = None,
    ) -> None:
        """Browse a source, or a container inside it. CID/MID values are shown in the table."""
        _check_range(start, end)

        async def go(heos, s: State) -> None:
            emit(s, await heos.browse(sid, cid, start, end), _render_result)

        run(ctx, go)

    @app.command()
    def favorites(ctx: typer.Context) -> None:
        """List HEOS Favorites; the # column is the number for play-preset."""

        async def go(heos, s: State) -> None:
            favs = await heos.get_favorites()
            emit(s, favs, lambda d: media_table(d.values(), start=1))

        run(ctx, go)

    @app.command()
    def inputs(ctx: typer.Context) -> None:
        """List the playable inputs (aux, HDMI, ...) of all devices."""

        async def go(heos, s: State) -> None:
            emit(s, list(await heos.get_input_sources()), media_table)

        run(ctx, go)

    @app.command("search-criteria")
    def search_criteria(ctx: typer.Context, sid: int) -> None:
        """List the ways a source can be searched."""

        async def go(heos, s: State) -> None:
            emit(s, await heos.get_search_criteria(sid), criteria_table)

        run(ctx, go)

    @app.command()
    def search(
        ctx: typer.Context,
        sid: int,
        text: str,
        criteria: Annotated[
            str | None, typer.Option(help="Criteria id or name (default: first offered).")
        ] = None,
        start: Start = None,
        end: End = None,
    ) -> None:
        """Search a source."""
        _check_range(start, end)

        async def go(heos, s: State) -> None:
            options = await heos.get_search_criteria(sid)
            if criteria is None:
                if not options:
                    raise typer.BadParameter("this source offers no search criteria")
                criteria_id = options[0].criteria_id
            elif criteria.isdigit():
                criteria_id = int(criteria)
            else:
                match = [o for o in options if o.name.lower() == criteria.lower()]
                if not match:
                    raise typer.BadParameter(
                        f"unknown criteria {criteria!r}; run: heos-cli search-criteria {sid}"
                    )
                criteria_id = match[0].criteria_id
            emit(s, await heos.search(sid, text, criteria_id, start, end), _render_result)

        run(ctx, go)

    @app.command("play-station")
    def play_station(
        ctx: typer.Context,
        sid: int,
        mid: Annotated[str, typer.Argument(help="Media id of a 'station' item.")],
        cid: Annotated[str | None, typer.Option()] = None,
    ) -> None:
        """Play a station found by browse or search."""

        async def go(heos, s: State) -> None:
            await heos.play_station((await resolve_player(heos, s.player)).player_id, sid, cid, mid)

        run(ctx, go)

    @app.command("play-preset")
    def play_preset(ctx: typer.Context, number: Annotated[int, typer.Argument(min=1)]) -> None:
        """Play HEOS Favorites entry NUMBER (1-based)."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).play_preset_station(number)

        run(ctx, go)

    @app.command("play-input")
    def play_input(
        ctx: typer.Context,
        input_name: Annotated[str, typer.Argument(help="e.g. inputs/aux_in_1, inputs/hdmi_in_1")],
        source: Annotated[
            str | None, typer.Option("--from", help="Play the input of this other player.")
        ] = None,
    ) -> None:
        """Play an input on the player."""

        async def go(heos, s: State) -> None:
            p = await resolve_player(heos, s.player)
            source_id = (await resolve_player(heos, source)).player_id if source else None
            await p.play_input_source(input_name, source_id)

        run(ctx, go)

    @app.command("play-url")
    def play_url(ctx: typer.Context, url: str) -> None:
        """Play a stream URL."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).play_url(url)

        run(ctx, go)

    @app.command()
    def add(
        ctx: typer.Context,
        sid: int,
        cid: Annotated[str, typer.Argument(help="Container id (a playable container).")],
        mid: Annotated[
            str | None, typer.Option(help="Add only this track instead of the container.")
        ] = None,
        mode: Annotated[AddMode, typer.Option(help="Where to put it.")] = AddMode.add_to_end,
    ) -> None:
        """Add a container or track to the queue."""

        async def go(heos, s: State) -> None:
            await (await resolve_player(heos, s.player)).add_to_queue(sid, cid, mid, _ADD[mode])

        run(ctx, go)

    @app.command("rename-playlist")
    def rename_playlist(ctx: typer.Context, cid: str, name: str) -> None:
        """Rename a HEOS playlist (CID from: heos-cli browse 1025)."""

        async def go(heos, s: State) -> None:
            await heos.rename_playlist(MUSIC_SOURCE_PLAYLISTS, cid, name)

        run(ctx, go)

    @app.command("delete-playlist")
    def delete_playlist(
        ctx: typer.Context, cid: str, yes: Annotated[bool, typer.Option("--yes", "-y")] = False
    ) -> None:
        """Delete a HEOS playlist (CID from: heos-cli browse 1025)."""
        if not yes:
            typer.confirm(f"Delete playlist {cid}?", abort=True)

        async def go(heos, s: State) -> None:
            await heos.delete_playlist(MUSIC_SOURCE_PLAYLISTS, cid)

        run(ctx, go)
