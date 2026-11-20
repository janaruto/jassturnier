import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import jass_logic as jl
from jass_db import GameExists, RoundConflict, Store, name_keys, prepare_photo


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.db")
        self.store.seed_players(["Lea", "Kev", "Guddi", "Tobi", "Inga", "Kägi"])
        self.ids = {p.name: p.id for p in self.store.players()}

    def tearDown(self):
        self.tmp.cleanup()

    def draw(self, number=1):
        tables = jl.draw_tables(list(self.ids.values()))
        return self.store.create_round(tables, number)

    def test_seed_only_once(self):
        self.assertFalse(self.store.seed_players(["Neu"]))
        self.assertEqual(len(self.store.players()), 6)

    def test_names_unique_case_insensitive(self):
        with self.assertRaises(ValueError):
            self.store.add_player("lea")
        with self.assertRaises(ValueError):
            self.store.add_player("?")
        self.store.add_player("  Stjepi   +1 ")
        self.assertIn("Stjepi +1", [p.name for p in self.store.players()])

    def test_round_with_jokers(self):
        rnd = self.draw()  # 6 Spieler -> 2 Tische, 2 «?»
        tables = self.store.tables(rnd.id)
        self.assertEqual(len(tables), 2)
        jokers = [p for p in self.store.players(include_jokers=True) if p.is_joker]
        self.assertEqual(len(jokers), 2)
        seated = [p for seats in tables.values() for p in seats]
        self.assertEqual(sorted(seated), sorted(list(self.ids.values()) + [j.id for j in jokers]))
        with self.assertRaises(RoundConflict):
            self.store.create_round(jl.draw_tables(list(self.ids.values())), 1)

    def test_games_and_checks(self):
        rnd = self.draw()
        v0 = self.store.version()
        gid = self.store.add_game(rnd.id, 1, 1, "Rosen", 97, 60)
        self.assertGreater(self.store.version(), v0)
        with self.assertRaises(GameExists):
            self.store.add_game(rnd.id, 1, 1, None, 100, 57)
        with self.assertRaises(ValueError):
            self.store.add_game(rnd.id, 1, 2, None, 90, 80)
        self.store.update_game(gid, "Obenabe", 157, 0)
        game = self.store.games(rnd.id)[0]
        self.assertEqual((game.trump, game.points_a, game.points_b), ("Obenabe", 157, 0))
        self.store.delete_game(gid)
        self.assertEqual(self.store.games(), [])

    def test_database_rejects_wrong_sum(self):
        rnd = self.draw()
        with sqlite3.connect(self.store.path) as conn, self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO games (round_id, table_no, game_no, points_a, points_b) VALUES (?, 1, 1, 90, 80)",
                (rnd.id,),
            )

    def test_redraw_only_without_games(self):
        rnd = self.draw()
        self.store.redraw_round(rnd.id, jl.draw_tables(list(self.ids.values())))
        self.store.add_game(rnd.id, 1, 1, None, 80, 77)
        with self.assertRaises(RoundConflict):
            self.store.redraw_round(rnd.id, jl.draw_tables(list(self.ids.values())))

    def test_cannot_delete_player_who_played(self):
        self.draw()
        with self.assertRaises(ValueError):
            self.store.delete_player(self.ids["Lea"])

    def test_backup_and_restore(self):
        rnd = self.draw()
        self.store.add_game(rnd.id, 1, 1, None, 97, 60)
        backup = self.store.backup_bytes()
        self.store.reset_tournament()
        self.assertEqual(self.store.rounds(), [])
        self.store.restore(backup)
        self.assertEqual(len(self.store.rounds()), 1)
        self.assertEqual(self.store.games()[0].points_a, 97)
        with self.assertRaises(ValueError):
            self.store.restore(b"kein backup")

    def test_photo(self):
        buf = io.BytesIO()
        Image.new("RGB", (1200, 800), "red").save(buf, "PNG")
        photo, thumb = prepare_photo(buf.getvalue())
        self.assertEqual(Image.open(io.BytesIO(photo)).size, (360, 480))
        self.assertEqual(Image.open(io.BytesIO(thumb)).size, (150, 200))
        self.store.set_photo(self.ids["Lea"], photo, thumb)
        lea = next(p for p in self.store.players() if p.name == "Lea")
        self.assertTrue(lea.has_photo)
        self.assertEqual(self.store.photo(lea.id), thumb)
        self.store.clear_photo(lea.id)
        self.assertIsNone(self.store.photo(lea.id))
        with self.assertRaises(ValueError):
            prepare_photo(b"no image")

    def test_name_keys_for_file_names(self):
        self.assertTrue(name_keys("Kägi") & name_keys("kaegi"))
        self.assertTrue(name_keys("Stjepi +1") & name_keys("stjepi+1"))
        self.assertFalse(name_keys("Lea") & name_keys("Leo"))


if __name__ == "__main__":
    unittest.main()
