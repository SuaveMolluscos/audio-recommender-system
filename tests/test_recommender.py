import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from rich.console import Console

from audio_recommender.cli import _render_song_table, interactive_main, main
from audio_recommender.database import (
    DatabaseError,
    _connect,
    check_catalog,
    normalize_text,
    search_songs,
)
from audio_recommender.engine import (
    _diversify,
    _negative_penalty,
    expand_vector_features,
    normalize_features,
    predict_ratings,
    recommend,
)
from audio_recommender.profile import ProfileError, load_profile, save_profile

SCALARS = (
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


def create_catalog(path: str) -> None:
    connection = sqlite3.connect(path)
    scalar_sql = ", ".join(f"{name} REAL" for name in SCALARS)
    connection.executescript(
        f"""
        CREATE TABLE songs (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            artist_display TEXT,
            genre TEXT,
            year INTEGER,
            features_json TEXT,
            {scalar_sql}
        );
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE song_tags (
            song_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            weight REAL
        );
        INSERT INTO tags (id, name) VALUES (1, 'energetic');
        """
    )
    for song_id in range(1, 7):
        values = [float(song_id * (index + 1)) for index in range(len(SCALARS))]
        vector = {
            "statistics": {
                "mfcc_mean": [float(song_id)] * 13,
                "chroma_mean": [float(song_id)] * 12,
                "tonnetz_mean": [float(song_id)] * 6,
                "spectral_contrast_mean": [float(song_id)] * 7,
            }
        }
        connection.execute(
            f"""
            INSERT INTO songs
            (id, title, artist_display, genre, year, features_json,
             {", ".join(SCALARS)})
            VALUES ({", ".join("?" for _ in range(6 + len(SCALARS)))})
            """,
            (
                song_id,
                f"Track {song_id}",
                "Synthetic artist" if song_id < 6 else "Another artist",
                "synthetic",
                2000 + song_id,
                json.dumps(vector),
                *values,
            ),
        )
        connection.execute(
            "INSERT INTO song_tags (song_id, tag_id, weight) VALUES (?, 1, 1.0)",
            (song_id,),
        )
    connection.commit()
    connection.close()


class RecommenderTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "synthetic.sqlite"
        create_catalog(str(self.database_path))

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_search_is_case_and_accent_insensitive(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "UPDATE songs SET title = 'Beyoncé' WHERE id = 1"
        )
        connection.commit()
        connection.close()

        results = search_songs(self.database_path, title="beyonce")

        self.assertEqual([result["id"] for result in results], [1])
        self.assertEqual(normalize_text("Beyoncé"), "beyonce")

    def test_database_is_read_only_and_schema_is_checked(self):
        counts = check_catalog(self.database_path)
        self.assertEqual(counts, (6, 6))
        with self.assertRaises(DatabaseError):
            check_catalog(self.database_path.parent / "missing.sqlite")
        connection = _connect(self.database_path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM songs")
        finally:
            connection.close()

    def test_incompatible_schema_reports_missing_columns(self):
        empty_database = Path(self.temporary_directory.name) / "empty.sqlite"
        sqlite3.connect(empty_database).close()

        with self.assertRaisesRegex(DatabaseError, "songs"):
            check_catalog(empty_database)

    def test_feature_expansion_and_normalization_are_finite(self):
        songs = pd.DataFrame(
            {
                "features_json": [
                    json.dumps(
                        {
                            "statistics": {
                                "mfcc_mean": [1.0] * 13,
                                "chroma_mean": [2.0] * 12,
                                "tonnetz_mean": [3.0] * 6,
                                "spectral_contrast_mean": [4.0] * 7,
                            }
                        }
                    ),
                    "{malformed",
                ],
                **{column: [1.0, np.nan] for column in SCALARS},
            }
        )

        normalized = normalize_features(expand_vector_features(songs))

        numeric = normalized.select_dtypes(include=[np.number]).to_numpy()
        self.assertTrue(np.isfinite(numeric).all())
        self.assertEqual(normalized.loc[0, "mfcc_mean_0"], 0.0)

    def test_knn_predictions_and_empty_history(self):
        predicted, confidence, similarity = predict_ratings(
            np.array([[0.9, 0.1], [0.2, 0.8]]),
            np.array([10, 2]),
            k=1,
        )
        self.assertEqual(predicted.tolist(), [10.0, 2.0])
        self.assertTrue(np.all((confidence >= 0.0) & (confidence <= 1.0)))
        self.assertEqual(similarity.tolist(), [0.9, 0.8])
        empty_prediction, empty_confidence, _ = predict_ratings(
            np.empty((2, 0)), np.array([])
        )
        self.assertEqual(empty_prediction.tolist(), [5.0, 5.0])
        self.assertEqual(empty_confidence.tolist(), [0.0, 0.0])
        with self.assertRaisesRegex(ValueError, "k debe ser mayor"):
            predict_ratings(np.array([[0.5]]), np.array([8]), k=0)
        with self.assertRaisesRegex(ValueError, "una calificación"):
            predict_ratings(np.array([[0.5, 0.2]]), np.array([8]), k=1)

    def test_rejected_tracks_are_penalized_more_than_neutral_tracks(self):
        rejected_penalty = _negative_penalty(np.array([[0.9]]), np.array([0]))[0]
        neutral_penalty = _negative_penalty(np.array([[0.9]]), np.array([5]))[0]

        self.assertGreater(rejected_penalty, neutral_penalty)

    def test_artist_diversification_keeps_up_to_three_per_artist(self):
        candidates = pd.DataFrame(
            {
                "id": [1, 2, 3, 4, 5],
                "artist_display": ["A", "A", "A", "A", "B"],
                "score": [0.9, 0.8, 0.7, 0.6, 0.5],
            }
        )

        results = _diversify(candidates, limit=5)

        self.assertEqual(results["id"].tolist(), [1, 2, 3, 5])

    def test_recommendation_excludes_rated_songs(self):
        results = recommend(
            self.database_path,
            [(1, 10), (2, 9), (3, 8)],
            top_n=2,
        )
        self.assertLessEqual(len(results), 2)
        self.assertTrue(set(results["id"]).isdisjoint({1, 2, 3}))
        if not results.empty:
            self.assertTrue(results["pred_rating"].between(0, 10).all())
            self.assertIn("reason", results.columns)

    def test_profile_round_trip_and_corrupt_profile_error(self):
        profile_path = Path(self.temporary_directory.name) / "user.json"
        save_profile(profile_path, {1: 8, 2: 0})
        self.assertEqual(load_profile(profile_path), {1: 8, 2: 0})
        profile_path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ProfileError):
            load_profile(profile_path)

    def test_cli_check_rate_ratings_and_recommend_commands(self):
        profile_path = Path(self.temporary_directory.name) / "profile.json"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                main(["--database", str(self.database_path), "check"]), 0
            )
            for song_id, rating in ((1, 10), (2, 9), (3, 8)):
                self.assertEqual(
                    main(
                        [
                            "--database",
                            str(self.database_path),
                            "--profile",
                            str(profile_path),
                            "rate",
                            str(song_id),
                            str(rating),
                        ]
                    ),
                    0,
                )
            self.assertEqual(
                main(
                    [
                        "--database",
                        str(self.database_path),
                        "--profile",
                        str(profile_path),
                        "ratings",
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "--database",
                        str(self.database_path),
                        "--profile",
                        str(profile_path),
                        "recommend",
                        "--top",
                        "2",
                    ]
                ),
                0,
            )
        self.assertIn("Catálogo válido", output.getvalue())
        self.assertIn("Track 1", output.getvalue())
        self.assertTrue(profile_path.is_file())

    def test_interactive_interface_searches_and_exits(self):
        output = io.StringIO()
        answers = iter(("1", "Track 1", "", "0"))
        with (
            contextlib.redirect_stdout(output),
            patch("builtins.input", side_effect=answers),
        ):
            result = interactive_main(
                [
                    "--database",
                    str(self.database_path),
                    "--profile",
                    str(Path(self.temporary_directory.name) / "profile.json"),
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn("SONORA", output.getvalue())
        self.assertIn("BIBLIOTECA CONECTADA", output.getvalue())
        self.assertIn("RESULTADOS DE BÚSQUEDA", output.getvalue())
        self.assertIn("Track 1", output.getvalue())
        self.assertIn("¡Gracias por escuchar!", output.getvalue())

    def test_song_table_displays_catalog_text_as_literal_content(self):
        output = io.StringIO()
        console = Console(
            file=output,
            width=80,
            force_terminal=False,
            legacy_windows=False,
        )

        _render_song_table(
            console,
            [{"id": 1, "title": "[bold red]Literal[/bold red]", "artist_display": "Artist"}],
            title="RESULTADOS",
        )

        self.assertIn("[bold red]Literal[/bold red]", output.getvalue())


if __name__ == "__main__":
    unittest.main()
