"""Durchspielen der App ohne Browser (streamlit.testing)."""

import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")
ADMIN, EINTRAGEN = "⚙️ Admin", "✍️ Eintragen"


class AppFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = os.environ.get("JASS_DATA_DIR")
        os.environ["JASS_DATA_DIR"] = self.tmp.name
        self.at = AppTest.from_file(APP, default_timeout=30)
        self.at.secrets["admin_pin"] = "4242"

    def tearDown(self):
        if self.old_env is None:
            os.environ.pop("JASS_DATA_DIR", None)
        else:
            os.environ["JASS_DATA_DIR"] = self.old_env
        self.tmp.cleanup()

    def run_app(self):
        self.at.run()
        self.assertFalse(self.at.exception, self.at.exception)
        return self.at

    def store(self):
        from jass_db import Store
        return Store(Path(self.tmp.name) / "jassturnier.db")

    def login_and_draw(self):
        at = self.at
        at.session_state["view"] = ADMIN
        self.run_app()
        at.text_input[0].input("4242")
        at.button[0].click()  # «Anmelden»
        self.run_app()
        self.assertTrue(at.session_state["is_admin"])
        at.button(key="adm_first").click()
        self.run_app()

    def test_start_page_lists_all_players(self):
        self.run_app()
        players = self.store().players()
        self.assertEqual(len(players), 19)
        self.assertIn("Stjepi +1", [p.name for p in players])

    def test_wrong_pin(self):
        self.at.session_state["view"] = ADMIN
        self.run_app()
        self.at.text_input[0].input("1234")
        self.at.button[0].click()
        self.run_app()
        self.assertIn("Falsche PIN.", [e.value for e in self.at.error])

    def test_draw_and_enter_result(self):
        self.login_and_draw()
        store = self.store()
        rnd = store.rounds()[0]
        tables = store.tables(rnd.id)
        self.assertEqual(len(tables), 5)
        jokers = [p for p in store.players(include_jokers=True) if p.is_joker]
        self.assertEqual(len(jokers), 1)  # 19 Personen -> ein «?»

        at = self.at
        at.session_state["view"] = EINTRAGEN
        at.session_state["entry_table"] = 1
        self.run_app()
        base = f"{rnd.id}_1_1"
        at.number_input(key=f"pa_{base}").set_value(97)
        self.run_app()
        self.assertEqual(at.number_input(key=f"pb_{base}").value, 60)  # automatisch ergänzt
        at.button(key=f"save_{base}").click()
        self.run_app()
        games = store.games(rnd.id)
        self.assertEqual([(g.table_no, g.game_no, g.points_a, g.points_b) for g in games], [(1, 1, 97, 60)])

        # nächstes Spiel: 1 Punkt ist unmöglich
        base2 = f"{rnd.id}_1_2"
        at.number_input(key=f"pa_{base2}").set_value(1)
        self.run_app()
        at.button(key=f"save_{base2}").click()
        self.run_app()
        self.assertTrue(any("1 Punkt" in e.value for e in at.error))
        self.assertEqual(len(store.games(rnd.id)), 1)

        # Korrektur von Spiel 1: 100 eintragen -> Gegenteam 57
        gid = games[0].id
        at.number_input(key=f"fix_{gid}_a").set_value(100)
        self.run_app()
        self.assertEqual(at.number_input(key=f"fix_{gid}_b").value, 57)
        at.button(key=f"fix_{gid}_save").click()
        self.run_app()
        fixed = store.games(rnd.id)[0]
        self.assertEqual((fixed.points_a, fixed.points_b), (100, 57))


if __name__ == "__main__":
    unittest.main()
