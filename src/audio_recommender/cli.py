"""Command-line interface for the local recommender."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from audio_recommender import __version__
from audio_recommender.database import check_catalog, get_song, search_songs
from audio_recommender.engine import recommend
from audio_recommender.profile import load_profile, save_profile

DEFAULT_PROFILE = Path("data/user_profile.json")
ACCENT = "bright_cyan"
MUTED = "grey70"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audio-recommender",
        description="Recomendador musical híbrido local.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--database",
        required=True,
        type=Path,
        help="Ruta a una base SQLite compatible (se abre en solo lectura).",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE,
        help=f"Archivo privado de calificaciones (por defecto: {DEFAULT_PROFILE}).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Validar esquema y contar filas.")

    search = commands.add_parser("search", help="Buscar por título o artista.")
    search_by = search.add_mutually_exclusive_group(required=True)
    search_by.add_argument("--title")
    search_by.add_argument("--artist")
    search.add_argument("--limit", type=int, default=20)

    rate = commands.add_parser("rate", help="Agregar o actualizar una calificación.")
    rate.add_argument("song_id", type=int)
    rate.add_argument("rating", type=int, choices=range(11), metavar="0..10")

    commands.add_parser("ratings", help="Mostrar las canciones calificadas.")

    recommendation = commands.add_parser("recommend", help="Generar recomendaciones.")
    recommendation.add_argument("--top", type=int, default=30)
    return parser


def _print_songs(songs: list[dict[str, object]]) -> None:
    if not songs:
        print("Sin resultados.")
        return
    for song in songs:
        print(
            f"{song['id']:>7}  {song['title']} — {song['artist_display']}"
        )


def _render_brand(console: Console) -> None:
    brand = Text()
    brand.append("[*]  ", style="bold bright_cyan")
    brand.append("SONORA", style="bold white")
    brand.append("  /  MUSIC DISCOVERY", style="bold bright_magenta")
    brand.append(f"\nTu próxima canción favorita empieza aquí  ·  v{__version__}", style=MUTED)
    console.print(
        Panel(
            Align.center(brand),
            border_style=ACCENT,
            box=box.DOUBLE,
            padding=(1, 2),
        )
    )


def _render_dashboard(
    console: Console, song_count: int, tag_count: int, rating_count: int
) -> None:
    stats = Table.grid(expand=True, padding=(0, 2))
    stats.add_column(justify="center")
    stats.add_column(justify="center")
    stats.add_column(justify="center")
    stats.add_row(
        f"[bold white]{song_count:,}[/bold white]\n[grey70]canciones[/grey70]",
        f"[bold white]{tag_count:,}[/bold white]\n[grey70]etiquetas[/grey70]",
        f"[bold bright_cyan]{rating_count:,}[/bold bright_cyan]\n[grey70]tus valoraciones[/grey70]",
    )
    console.print(
        Panel(
            stats,
            title="[bold bright_cyan]BIBLIOTECA CONECTADA[/bold bright_cyan]",
            subtitle="[grey70]SQLite · solo lectura[/grey70]",
            border_style="grey37",
            box=box.ROUNDED,
        )
    )


def _render_menu(console: Console) -> None:
    options = Table.grid(expand=True, padding=(0, 1))
    options.add_column(ratio=1)
    options.add_column(ratio=1)
    options.add_row(
        "[bold bright_cyan]  1[/bold bright_cyan]  Buscar por título",
        "[bold bright_cyan]  2[/bold bright_cyan]  Buscar por artista",
    )
    options.add_row(
        "[bold bright_magenta]  3[/bold bright_magenta]  Calificar una canción",
        "[bold bright_magenta]  4[/bold bright_magenta]  Mi colección",
    )
    options.add_row(
        "[bold green]  5[/bold green]  Crear recomendaciones",
        "[bold grey70]  0[/bold grey70]  Salir",
    )
    console.print(
        Panel(
            options,
            title="[bold white]¿QUÉ TE APETECE HACER?[/bold white]",
            border_style=ACCENT,
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def _ask(console: Console, prompt: str) -> str:
    console.print(f"\n[bold {ACCENT}]{prompt}[/bold {ACCENT}]", end=" ")
    return input().strip()


def _wait_to_continue(console: Console) -> None:
    console.print("\n[grey70]Presiona Enter para volver al menú...[/grey70]")
    input()


def _render_song_table(
    console: Console,
    songs: list[dict[str, object]],
    *,
    title: str,
    rating_by_id: dict[int, int] | None = None,
) -> None:
    if not songs:
        console.print(
            Panel(
                "[yellow]No encontramos canciones con ese criterio.[/yellow]",
                title=f"[bold]{title}[/bold]",
                border_style="yellow",
                box=box.ROUNDED,
            )
        )
        return
    table = Table(
        box=box.ROUNDED,
        border_style="grey37",
        header_style="bold bright_cyan",
        expand=True,
        title=f"[bold white]{title}[/bold white]",
        row_styles=["none", "grey11"],
    )
    table.add_column("ID", justify="right", style="grey70", width=8)
    table.add_column("TÍTULO", style="bold white", min_width=18)
    table.add_column("ARTISTA", style="bright_magenta")
    if rating_by_id is not None:
        table.add_column("TU NOTA", justify="center", style="bright_cyan", width=10)
    for song in songs:
        values = [
            Text(str(song["id"]), style="grey70"),
            Text(str(song["title"] or "Sin título"), style="bold white"),
            Text(
                str(song["artist_display"] or "Artista desconocido"),
                style="bright_magenta",
            ),
        ]
        if rating_by_id is not None:
            rating = rating_by_id.get(int(song["id"]))
            values.append(
                Text(
                    f"{rating}/10" if rating is not None else "—",
                    style="bright_cyan",
                )
            )
        table.add_row(*values)
    console.print(table)


def _render_recommendations(console: Console, results) -> None:
    if results.empty:
        console.print(
            Panel(
                "[yellow]Todavía no hay suficientes señales para recomendar.\n"
                "Califica al menos 3 canciones y vuelve a intentarlo.[/yellow]",
                title="[bold yellow]AÚN ESTAMOS APRENDIENDO TU GUSTO[/bold yellow]",
                border_style="yellow",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        return
    table = Table(
        box=box.ROUNDED,
        border_style="bright_magenta",
        header_style="bold bright_cyan",
        expand=True,
        title="[bold white]TU PRÓXIMO DESCUBRIMIENTO[/bold white]",
        row_styles=["none", "grey11"],
    )
    table.add_column("#", justify="right", style="grey70", width=4)
    table.add_column("CANCIÓN", style="bold white", min_width=18)
    table.add_column("ARTISTA", style="bright_magenta")
    table.add_column("PREDICCIÓN", justify="center", style="green", width=13)
    table.add_column("CONFIANZA", justify="center", style="bright_cyan", width=12)
    table.add_column("¿POR QUÉ?", style="grey70", min_width=24)
    for index, (_, row) in enumerate(results.iterrows(), start=1):
        table.add_row(
            Text(f"{index:02}", style="grey70"),
            Text(str(row["title"] or "Sin título"), style="bold white"),
            Text(
                str(row["artist_display"] or "Artista desconocido"),
                style="bright_magenta",
            ),
            Text(f"{row['pred_rating']:.1f}/10", style="green"),
            Text(f"{row['confidence']:.0%}", style="bright_cyan"),
            Text(str(row["reason"]), style="grey70"),
        )
    console.print(table)
    console.print(
        "[grey70]Las predicciones orientan el ranking; no son garantías "
        "ni probabilidades calibradas.[/grey70]"
    )


def interactive_main(argv: list[str] | None = None) -> int:
    """Run the interactive terminal interface."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="audio-recommender-ui",
        description="Interfaz interactiva de terminal para el recomendador.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="Ruta a la base SQLite compatible. Si se omite, se solicitará.",
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    args = parser.parse_args(argv)
    console = Console(legacy_windows=False)

    try:
        database_path = args.database
        if database_path is None:
            database_path = Path(
                _ask(console, "[DB] Ruta al archivo SQLite:")
            ).expanduser()
        if not str(database_path).strip():
            console.print("[bold red]Debes indicar la ruta a la base de datos.[/bold red]")
            return 2
        song_count, tag_count = check_catalog(database_path)
        ratings = load_profile(args.profile)
    except (EOFError, KeyboardInterrupt):
        console.print("\n[grey70]Saliendo.[/grey70]")
        return 0
    except (OSError, ValueError) as error:
        console.print(f"[bold red]Error:[/bold red] {error}", stderr=True)
        return 2

    try:
        while True:
            console.clear()
            _render_brand(console)
            _render_dashboard(console, song_count, tag_count, len(ratings))
            _render_menu(console)
            choice = _ask(console, "Elige una opción [0-5]:")
            if choice == "0":
                console.print(
                    Panel(
                        Align.center(
                            "[bold bright_cyan]¡Gracias por escuchar![/bold bright_cyan]"
                        ),
                        border_style=ACCENT,
                        box=box.ROUNDED,
                    )
                )
                return 0
            if choice in ("1", "2"):
                prompt = "Título a buscar:" if choice == "1" else "Artista a buscar:"
                query = _ask(console, prompt)
                matches = search_songs(
                    database_path,
                    title=query if choice == "1" else None,
                    artist=query if choice == "2" else None,
                    limit=20,
                )
                _render_song_table(
                    console,
                    matches,
                    title="RESULTADOS DE BÚSQUEDA",
                )
                _wait_to_continue(console)
            elif choice == "3":
                try:
                    song_id = int(_ask(console, "ID de la canción:"))
                    rating = int(_ask(console, "Tu calificación (0-10):"))
                except ValueError:
                    console.print("[yellow]Escribe el ID y la nota como números enteros.[/yellow]")
                    continue
                if song_id < 1 or not 0 <= rating <= 10:
                    console.print(
                        "[yellow]El ID debe ser positivo y la nota estar entre 0 y 10.[/yellow]"
                    )
                    continue
                song = get_song(database_path, song_id)
                if song is None:
                    console.print(f"[yellow]No existe una canción con ID {song_id}.[/yellow]")
                    continue
                ratings[song_id] = rating
                save_profile(args.profile, ratings)
                rating_message = Text(str(song["title"]), style="bold white")
                rating_message.append(" — ")
                rating_message.append(f"{rating}/10", style="bright_cyan")
                console.print(
                    Panel(
                        rating_message,
                        title="[bold green]VALORACIÓN GUARDADA[/bold green]",
                        border_style="green",
                        box=box.ROUNDED,
                    )
                )
                _wait_to_continue(console)
            elif choice == "4":
                if not ratings:
                    console.print("[yellow]Aún no hay canciones calificadas.[/yellow]")
                    _wait_to_continue(console)
                    continue
                rated_songs = []
                for song_id, rating in sorted(ratings.items()):
                    song = get_song(database_path, song_id)
                    rated_songs.append(
                        song
                        or {
                            "id": song_id,
                            "title": "(canción no disponible)",
                            "artist_display": "",
                        }
                    )
                _render_song_table(
                    console,
                    rated_songs,
                    title="TU COLECCIÓN",
                    rating_by_id=ratings,
                )
                _wait_to_continue(console)
            elif choice == "5":
                with console.status(
                    "[bold bright_cyan]Analizando tu perfil musical...[/bold bright_cyan]",
                    spinner="dots",
                ):
                    results = recommend(database_path, ratings.items())
                _render_recommendations(console, results)
                _wait_to_continue(console)
            else:
                console.print("[yellow]Opción no válida. Elige un número del menú.[/yellow]")
                _wait_to_continue(console)
    except (EOFError, KeyboardInterrupt):
        console.print("\n[grey70]Saliendo.[/grey70]")
        return 0
    except (OSError, ValueError) as error:
        console.print(f"[bold red]Error:[/bold red] {error}", stderr=True)
        return 2


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            song_count, tag_count = check_catalog(args.database)
            print(f"Catálogo válido: {song_count} canciones, {tag_count} etiquetas.")
        elif args.command == "search":
            songs = search_songs(
                args.database,
                title=args.title,
                artist=args.artist,
                limit=args.limit,
            )
            _print_songs(songs)
        elif args.command == "rate":
            song = get_song(args.database, args.song_id)
            if song is None:
                print(f"No existe una canción con ID {args.song_id}.", file=sys.stderr)
                return 1
            profile = load_profile(args.profile)
            profile[args.song_id] = args.rating
            save_profile(args.profile, profile)
            print(f"Calificación guardada: {song['title']} — {args.rating}/10.")
        elif args.command == "ratings":
            profile = load_profile(args.profile)
            if not profile:
                print("Aún no hay canciones calificadas.")
            else:
                for song_id, rating in sorted(profile.items()):
                    song = get_song(args.database, song_id)
                    if song is None:
                        print(f"{song_id:>7}  (canción no disponible) — {rating}/10")
                    else:
                        print(
                            f"{song_id:>7}  {song['title']} — "
                            f"{song['artist_display']}  [{rating}/10]"
                        )
        elif args.command == "recommend":
            if args.top < 1:
                parser.error("--top debe ser mayor que cero.")
            profile = load_profile(args.profile)
            results = recommend(args.database, profile.items(), args.top)
            if results.empty:
                print(
                    "No se encontraron recomendaciones con evidencia suficiente. "
                    "Se requieren al menos 3 canciones calificadas."
                )
            else:
                for index, (_, row) in enumerate(results.iterrows(), start=1):
                    print(
                        f"{index:>3}. [{row['pred_rating']:.1f}/10, "
                        f"conf. {row['confidence']:.0%}] "
                        f"{row['title']} — {row['artist_display']}"
                    )
                    print(f"     {row['reason']}")
        return 0
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
