"""Hybrid content-based recommendation engine."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from audio_recommender.database import (
    SCALAR_FEATURES,
    VECTOR_FEATURES,
    load_catalog,
)
from audio_recommender.profile import validate_ratings

TOP_K_SIMILAR = 8
TOP_N = 30
MIN_TRUSTED_SIMILARITY = 0.58
MIN_PREDICTION = 7.0
MIN_CONFIDENCE = 0.52
MAX_PER_ARTIST = 3


def expand_vector_features(songs: pd.DataFrame) -> pd.DataFrame:
    expanded = songs.copy()
    for feature_name, dimensions in VECTOR_FEATURES.items():
        values = np.full((len(expanded), dimensions), np.nan)
        for position, raw in enumerate(expanded["features_json"]):
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            statistics = payload.get("statistics")
            feature = statistics.get(feature_name) if isinstance(statistics, dict) else None
            vector = feature.get("mean") if isinstance(feature, dict) else None
            if not isinstance(vector, (list, tuple)) or len(vector) != dimensions:
                continue
            try:
                values[position] = np.asarray(vector, dtype=float)
            except (TypeError, ValueError):
                continue
        for index in range(dimensions):
            expanded[f"{feature_name}_{index}"] = values[:, index]
    return expanded.drop(columns=["features_json"])


def feature_columns() -> list[str]:
    return list(SCALAR_FEATURES) + [
        f"{name}_{index}"
        for name, dimensions in VECTOR_FEATURES.items()
        for index in range(dimensions)
    ]


def normalize_features(songs: pd.DataFrame) -> pd.DataFrame:
    normalized = songs.copy()
    blocks = [list(SCALAR_FEATURES)] + [
        [f"{name}_{index}" for index in range(dimensions)]
        for name, dimensions in VECTOR_FEATURES.items()
    ]
    for columns in blocks:
        for column in columns:
            values = pd.to_numeric(normalized[column], errors="coerce")
            values = values.replace([np.inf, -np.inf], np.nan)
            mean = values.mean()
            deviation = values.std()
            if pd.isna(mean) or pd.isna(deviation) or deviation < 1e-12:
                normalized[column] = 0.0
            else:
                normalized[column] = (values.fillna(mean) - mean) / deviation
        normalized.loc[:, columns] *= 1.0 / np.sqrt(len(columns))
    return normalized


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    if len(left) == 0 or len(right) == 0:
        return np.zeros((len(left), len(right)), dtype=float)
    left = np.nan_to_num(left, nan=0.0, posinf=0.0, neginf=0.0)
    right = np.nan_to_num(right, nan=0.0, posinf=0.0, neginf=0.0)
    left_norm = np.linalg.norm(left, axis=1, keepdims=True)
    right_norm = np.linalg.norm(right, axis=1, keepdims=True)
    left_norm[left_norm == 0] = 1.0
    right_norm[right_norm == 0] = 1.0
    return (left @ right.T) / (left_norm @ right_norm.T)


def predict_ratings(
    similarities: np.ndarray,
    ratings: np.ndarray,
    k: int = TOP_K_SIMILAR,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if k < 1:
        raise ValueError("k debe ser mayor que cero.")
    if similarities.shape[1] == 0:
        empty = np.zeros(similarities.shape[0])
        return np.full(similarities.shape[0], 5.0), empty, empty
    if len(ratings) != similarities.shape[1]:
        raise ValueError("Debe haber una calificación por cada canción del historial.")
    ratings = np.asarray(ratings, dtype=float)
    neighbors = min(k, similarities.shape[1])
    order = np.argsort(similarities, axis=1)[:, -neighbors:]
    selected = np.take_along_axis(similarities, order, axis=1)
    neighbor_ratings = ratings[order]
    weights = np.power(np.clip((selected + 1.0) / 2.0, 0.0, 1.0), 4.0)
    denominator = weights.sum(axis=1)
    prediction = np.divide(
        (weights * neighbor_ratings).sum(axis=1),
        denominator,
        out=np.full(len(similarities), 5.0),
        where=denominator > 1e-12,
    )
    best_similarity = selected[:, -1]
    best_scaled = np.clip((best_similarity + 1.0) / 2.0, 0.0, 1.0)
    if neighbors > 1:
        agreement = np.clip(1.0 - np.std(neighbor_ratings, axis=1) / 5.0, 0.0, 1.0)
    else:
        agreement = np.ones(len(similarities))
    confidence = 0.65 * best_scaled + 0.35 * agreement
    return prediction, confidence, best_similarity


def _rating_signal(rating: float) -> float:
    return (rating - 5.0) / 5.0


def _tag_profile(tags: pd.DataFrame, ratings: dict[int, int]) -> dict[str, float]:
    if tags.empty:
        return {}
    selected = tags[tags["song_id"].isin(ratings)].copy()
    if selected.empty:
        return {}
    selected["weight"] = pd.to_numeric(selected["weight"], errors="coerce").fillna(1.0)
    selected["contribution"] = selected.apply(
        lambda row: _rating_signal(ratings[int(row["song_id"])]) * row["weight"],
        axis=1,
    )
    totals = selected.groupby("tag")["contribution"].sum()
    weights = selected.groupby("tag")["weight"].sum().replace(0, 1.0)
    return {
        str(tag): float(np.clip(value, -1.0, 1.0))
        for tag, value in (totals / weights).items()
    }


def _tag_scores(
    tags: pd.DataFrame, candidate_ids: list[int], profile: dict[str, float]
) -> np.ndarray:
    scores: dict[int, float] = {}
    profile_norm = np.sqrt(sum(value * value for value in profile.values()))
    if tags.empty or profile_norm < 1e-12:
        return np.zeros(len(candidate_ids))
    selected = tags[tags["song_id"].isin(candidate_ids)]
    for song_id, group in selected.groupby("song_id"):
        dot = 0.0
        norm = 0.0
        for _, row in group.iterrows():
            weight = float(row["weight"]) if pd.notna(row["weight"]) else 1.0
            dot += profile.get(str(row["tag"]), 0.0) * weight
            norm += weight * weight
        denominator = profile_norm * np.sqrt(norm)
        scores[int(song_id)] = dot / denominator if denominator > 1e-12 else 0.0
    return np.asarray([scores.get(int(song_id), 0.0) for song_id in candidate_ids])


def _metadata_profiles(
    songs: pd.DataFrame, ratings: dict[int, int]
) -> tuple[dict[str, float], dict[str, float]]:
    selected = songs[songs["id"].isin(ratings)].copy()
    if selected.empty:
        return {}, {}
    selected["signal"] = selected["id"].map(
        lambda song_id: _rating_signal(ratings[int(song_id)])
    )

    def build(column: str) -> dict[str, float]:
        result = {}
        for value, group in selected.groupby(column, dropna=True):
            if pd.isna(value) or not str(value).strip():
                continue
            confidence = min(1.0, np.sqrt(len(group) / 5.0))
            result[str(value)] = float(
                np.clip(group["signal"].mean() * confidence, -1.0, 1.0)
            )
        return result

    return build("artist_display"), build("genre")


def _metadata_scores(
    candidates: pd.DataFrame,
    artists: dict[str, float],
    genres: dict[str, float],
) -> tuple[np.ndarray, np.ndarray]:
    artist_scores = [
        artists.get(str(value), 0.0) if pd.notna(value) else 0.0
        for value in candidates["artist_display"]
    ]
    genre_scores = [
        genres.get(str(value), 0.0) if pd.notna(value) else 0.0
        for value in candidates["genre"]
    ]
    return np.asarray(artist_scores), np.asarray(genre_scores)


def _negative_penalty(similarities: np.ndarray, ratings: np.ndarray) -> np.ndarray:
    if similarities.shape[1] == 0:
        return np.zeros(similarities.shape[0])
    rejection = np.clip((5.0 - ratings) / 5.0, 0.0, 1.0)
    weighted = np.clip((similarities + 1.0) / 2.0, 0.0, 1.0) * rejection[None, :]
    count = min(3, weighted.shape[1])
    return np.sort(weighted, axis=1)[:, -count:].mean(axis=1)


def _reason(row: pd.Series) -> str:
    reasons = []
    if row["audio_score"] >= 0.78:
        reasons.append("audio muy similar a tus favoritas")
    elif row["audio_score"] >= 0.65:
        reasons.append("perfil sonoro compatible")
    if row["tag_score"] >= 0.65:
        reasons.append("tags muy compatibles")
    if row["genre_score"] > 0.20:
        reasons.append("género afín")
    if row["artist_score"] > 0.35:
        reasons.append("artista con afinidad histórica")
    return ", ".join(reasons) or "coincidencia combinada con tu historial"


def _diversify(candidates: pd.DataFrame, limit: int) -> pd.DataFrame:
    selected = []
    artist_counts: dict[str, int] = {}
    for _, row in candidates.iterrows():
        artist = str(row["artist_display"])
        if artist_counts.get(artist, 0) >= MAX_PER_ARTIST:
            continue
        selected.append(row)
        artist_counts[artist] = artist_counts.get(artist, 0) + 1
        if len(selected) >= limit:
            break
    return pd.DataFrame(selected, columns=candidates.columns)


def recommend(
    database_path: str | Path,
    user_ratings: Iterable[Iterable[object]],
    top_n: int = TOP_N,
) -> pd.DataFrame:
    """Return ranked recommendations; an empty result is an intentional abstention."""
    if top_n < 1:
        raise ValueError("top_n debe ser mayor que cero.")
    ratings = validate_ratings(user_ratings)
    songs, tags = load_catalog(database_path)
    if songs.empty:
        return pd.DataFrame()
    valid_ids = set(songs["id"].astype(int))
    ratings = {song_id: rating for song_id, rating in ratings.items() if song_id in valid_ids}
    if len(ratings) < 3:
        return pd.DataFrame()

    expanded = expand_vector_features(songs)
    normalized = normalize_features(expanded)
    candidates = normalized[~normalized["id"].isin(ratings)].copy()
    if candidates.empty:
        return pd.DataFrame()
    history = normalized[normalized["id"].isin(ratings)].copy()
    history = history.set_index("id").loc[list(ratings)].reset_index()
    columns = feature_columns()
    similarities = cosine_similarity(
        candidates[columns].to_numpy(dtype=float),
        history[columns].to_numpy(dtype=float),
    )
    history_ratings = np.asarray([ratings[int(song_id)] for song_id in history["id"]])
    prediction, confidence, best_similarity = predict_ratings(
        similarities, history_ratings
    )

    raw_tag_scores = _tag_scores(tags, candidates["id"].astype(int).tolist(), _tag_profile(tags, ratings))
    artists, genres = _metadata_profiles(songs, ratings)
    artist_raw, genre_raw = _metadata_scores(candidates, artists, genres)
    negative_mask = history_ratings <= 5
    negative_penalty = _negative_penalty(
        similarities[:, negative_mask],
        history_ratings[negative_mask],
    )
    audio_score = np.clip(prediction / 10.0, 0.0, 1.0)
    result = candidates[["id", "title", "artist_display", "genre"]].copy()
    result["pred_rating"] = prediction
    result["confidence"] = confidence
    result["best_similarity"] = best_similarity
    result["audio_score"] = audio_score
    result["tag_score"] = (raw_tag_scores + 1.0) / 2.0
    result["genre_score"] = (genre_raw + 1.0) / 2.0
    result["artist_score"] = (artist_raw + 1.0) / 2.0
    result["negative_penalty"] = negative_penalty
    result["score"] = (
        0.58 * audio_score
        + 0.20 * result["tag_score"]
        + 0.08 * result["genre_score"]
        + 0.04 * result["artist_score"]
        + 0.10 * confidence
        - 0.18 * negative_penalty
    )
    result = result[
        (result["pred_rating"] >= MIN_PREDICTION)
        & (result["confidence"] >= MIN_CONFIDENCE)
        & (result["best_similarity"] >= MIN_TRUSTED_SIMILARITY)
    ]
    if result.empty:
        return result.reset_index(drop=True)
    result = result.sort_values(
        ["score", "pred_rating", "confidence"], ascending=False
    )
    result = _diversify(result, top_n).copy()
    if result.empty:
        return result.reset_index(drop=True)
    result["reason"] = result.apply(_reason, axis=1)
    return result.reset_index(drop=True)
