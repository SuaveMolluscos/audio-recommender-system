"""Persistence and validation for a user's private ratings."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path


class ProfileError(ValueError):
    """Raised when a user profile is invalid or cannot be persisted."""


def validate_ratings(ratings: Iterable[Iterable[object]]) -> dict[int, int]:
    parsed: dict[int, int] = {}
    try:
        for entry in ratings:
            values = list(entry)
            if len(values) != 2:
                raise ProfileError("Cada calificación debe contener ID y nota.")
            song_id, rating = values
            if isinstance(song_id, bool) or isinstance(rating, bool):
                raise ProfileError("El ID y la calificación deben ser enteros.")
            song_id, rating = int(song_id), int(rating)
            if song_id < 1 or not 0 <= rating <= 10:
                raise ProfileError("El ID debe ser positivo y la nota estar entre 0 y 10.")
            if song_id in parsed:
                raise ProfileError(f"El ID {song_id} está duplicado en el perfil.")
            parsed[song_id] = rating
    except (TypeError, ValueError) as error:
        if isinstance(error, ProfileError):
            raise
        raise ProfileError("El perfil contiene una calificación inválida.") from error
    return parsed


def load_profile(path: str | Path) -> dict[int, int]:
    profile_path = Path(path)
    if not profile_path.exists():
        return {}
    try:
        with profile_path.open(encoding="utf-8") as profile_file:
            payload = json.load(profile_file)
    except (OSError, json.JSONDecodeError) as error:
        raise ProfileError(f"No se pudo leer el perfil {profile_path}: {error}") from error
    if not isinstance(payload, list):
        raise ProfileError(f"El perfil {profile_path} debe contener una lista JSON.")
    return validate_ratings(payload)


def save_profile(path: str | Path, ratings: dict[int, int]) -> None:
    profile_path = Path(path)
    validated = validate_ratings(ratings.items())
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=profile_path.parent,
            delete=False,
        ) as profile_file:
            temporary_name = profile_file.name
            json.dump(
                [[song_id, rating] for song_id, rating in sorted(validated.items())],
                profile_file,
                ensure_ascii=False,
                indent=2,
            )
            profile_file.write("\n")
        os.replace(temporary_name, profile_path)
    except OSError as error:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise ProfileError(f"No se pudo guardar el perfil {profile_path}: {error}") from error
