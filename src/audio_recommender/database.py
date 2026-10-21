"""Read-only access to the SQLite catalogue."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

SCALAR_FEATURES = (
    "tempo_mean",
    "tempo_std",
    "energy_rms_mean",
    "energy_rms_std",
    "energy_norm_peak_mean",
    "energy_norm_peak_std",
    "acousticness_zcr_mean",
    "acousticness_zcr_std",
    "brightness_mean",
    "brightness_std",
    "zcr_mean",
    "zcr_std",
    "rolloff_mean",
    "rolloff_std",
    "onset_mean",
    "onset_std",
    "rhythm_mean",
    "rhythm_std",
)

VECTOR_FEATURES = {
    "mfcc_mean": 13,
    "chroma_mean": 12,
    "tonnetz_mean": 6,
    "spectral_contrast_mean": 7,
}


class DatabaseError(ValueError):
    """Raised when a catalogue cannot be read or does not match the schema."""


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold().strip())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _connect(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path).expanduser()
    if not path.is_file():
        raise DatabaseError(f"No se encontró la base de datos: {path}")
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection
    except sqlite3.Error as error:
        raise DatabaseError(f"No se pudo abrir la base de datos: {error}") from error


def _validate_schema(connection: sqlite3.Connection) -> None:
    required = {
        "songs": {
            "id",
            "title",
            "artist_display",
            "genre",
            "year",
            "features_json",
            *SCALAR_FEATURES,
        },
        "song_tags": {"song_id", "tag_id", "weight"},
        "tags": {"id", "name"},
    }
    for table, expected_columns in required.items():
        try:
            columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
        except sqlite3.Error as error:
            raise DatabaseError(f"No se pudo inspeccionar la tabla {table}: {error}") from error
        missing = sorted(expected_columns - columns)
        if missing:
            raise DatabaseError(
                f"El esquema no es compatible: falta(n) en {table}: "
                f"{', '.join(missing)}. Consulta docs/database-schema.md."
            )


def _open_validated(database_path: str | Path) -> sqlite3.Connection:
    connection = _connect(database_path)
    try:
        _validate_schema(connection)
    except DatabaseError:
        connection.close()
        raise
    return connection


def load_catalog(database_path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load songs and tags from a schema-validated, read-only database."""
    connection = _open_validated(database_path)
    columns = ", ".join(f'"{name}"' for name in SCALAR_FEATURES)
    try:
        songs = pd.read_sql_query(
            f"""
            SELECT id, title, artist_display, genre, year, features_json, {columns}
            FROM songs
            """,
            connection,
        )
        tags = pd.read_sql_query(
            """
            SELECT song_tags.song_id, tags.name AS tag,
                   COALESCE(song_tags.weight, 1.0) AS weight
            FROM song_tags
            JOIN tags ON tags.id = song_tags.tag_id
            """,
            connection,
        )
    except (sqlite3.Error, pd.errors.DatabaseError) as error:
        raise DatabaseError(f"No se pudo leer el catálogo: {error}") from error
    finally:
        connection.close()
    return songs, tags


def check_catalog(database_path: str | Path) -> tuple[int, int]:
    connection = _open_validated(database_path)
    try:
        song_count = connection.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        tag_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM song_tags
            JOIN tags ON tags.id = song_tags.tag_id
            """
        ).fetchone()[0]
    except sqlite3.Error as error:
        raise DatabaseError(f"No se pudo contar el catálogo: {error}") from error
    finally:
        connection.close()
    return song_count, tag_count


def search_songs(
    database_path: str | Path,
    *,
    title: str | None = None,
    artist: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("El límite de resultados debe ser mayor que cero.")
    if (title is None) == (artist is None):
        raise ValueError("Indica exactamente un criterio: título o artista.")
    column = "title" if title is not None else "artist_display"
    query = normalize_text(title if title is not None else artist)
    if not query:
        return []

    connection = _open_validated(database_path)
    try:
        rows = connection.execute(
            "SELECT id, title, artist_display FROM songs"
        ).fetchall()
    except sqlite3.Error as error:
        raise DatabaseError(f"No se pudo buscar en el catálogo: {error}") from error
    finally:
        connection.close()

    matches = [
        dict(row)
        for row in rows
        if query in normalize_text(row[column])
    ]
    matches.sort(
        key=lambda row: (
            normalize_text(row["artist_display"]),
            normalize_text(row["title"]),
        )
    )
    return matches[:limit]


def get_song(database_path: str | Path, song_id: int) -> dict[str, Any] | None:
    connection = _open_validated(database_path)
    try:
        row = connection.execute(
            "SELECT id, title, artist_display FROM songs WHERE id = ?",
            (song_id,),
        ).fetchone()
    except sqlite3.Error as error:
        raise DatabaseError(f"No se pudo consultar la canción: {error}") from error
    finally:
        connection.close()
    return dict(row) if row is not None else None
