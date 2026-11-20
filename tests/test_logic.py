import random
import unittest
from collections import Counter
from types import SimpleNamespace as G

import jass_logic as jl


class PointsTest(unittest.TestCase):
    def test_valid_results(self):
        for a, b in [(97, 60), (157, 0), (0, 157), (78, 79), (2, 155)]:
            self.assertEqual(jl.validate_points(a, b), [], (a, b))

    def test_sum_must_be_157(self):
        self.assertIn("157", jl.validate_points(90, 80)[0])
        self.assertIn("157", jl.validate_points(100, 0)[0])

    def test_range_and_missing(self):
        self.assertTrue(jl.validate_points(None, 60))
        self.assertTrue(jl.validate_points(-3, 160))
        self.assertTrue(jl.validate_points(158, -1))
        self.assertTrue(jl.validate_points(80.5, 76.5))

    def test_one_point_impossible(self):
        self.assertIn("1 Punkt", jl.validate_points(1, 156)[0])
        self.assertIn("1 Punkt", jl.validate_points(156, 1)[0])

    def test_helpers(self):
        self.assertEqual(jl.complement(97), 60)
        self.assertEqual([jl.team_of_seat(s) for s in (1, 2, 3, 4)], ["A", "B", "A", "B"])
        self.assertTrue(jl.is_match(157, 0))
        self.assertFalse(jl.is_match(150, 7))
        self.assertEqual(jl.next_game_no([]), 1)
        self.assertEqual(jl.next_game_no([1, 2]), 3)
        self.assertEqual(jl.next_game_no([1, 3]), 2)
        self.assertIsNone(jl.next_game_no([1, 2, 3, 4]))


class DrawTest(unittest.TestCase):
    def check_round(self, tables, players):
        flat = [p for t in tables for p in t]
        self.assertTrue(all(len(t) == 4 for t in tables))
        self.assertEqual(sorted(p for p in flat if p is not None), sorted(players))
        return flat.count(None)

    def test_jokers_fill_up(self):
        self.assertEqual(jl.jokers_needed(18), 2)
        self.assertEqual(jl.jokers_needed(20), 0)
        self.assertEqual(jl.jokers_needed(17), 3)
        self.assertEqual(jl.jokers_needed(5), 3)

    def test_18_players_two_jokers_on_different_tables(self):
        players = list(range(1, 19))
        for seed in range(20):
            tables = jl.draw_tables(players, rng=random.Random(seed))
            self.assertEqual(len(tables), 5)
            self.assertEqual(self.check_round(tables, players), 2)
            self.assertTrue(all(t.count(None) <= 1 for t in tables))

    def test_no_jokers_when_it_fits(self):
        players = list(range(1, 21))
        tables = jl.draw_tables(players, rng=random.Random(1))
        self.assertEqual(self.check_round(tables, players), 0)

    def test_empty(self):
        self.assertEqual(jl.draw_tables([]), [])

    def test_partners_do_not_repeat(self):
        players = list(range(1, 19))
        past = []
        for r in range(5):
            tables = jl.draw_tables(players, past, rng=random.Random(r))
            self.check_round(tables, players)
            past += tables
        partners, _ = jl.pair_counts(past)
        # niemand hat zweimal den gleichen Partner (auch nicht zweimal «?»)
        self.assertEqual(max(partners.values()), 1)

    def test_more_tables_than_jokers_spread(self):
        tables = jl.draw_tables(list(range(1, 14)), rng=random.Random(3))  # 13 -> 4 Tische, 3 «?»
        self.assertEqual(Counter(t.count(None) for t in tables), Counter({1: 3, 0: 1}))


class StandingsTest(unittest.TestCase):
    def setUp(self):
        self.names = {1: "Lea", 2: "Kev", 3: "Guddi", 4: "Tobi", 5: "Inga"}
        # Runde 10, Tisch 1: Sitz1 Lea, Sitz2 Kev, Sitz3 Guddi, Sitz4 «?» (99)
        self.tables = {(10, 1): [1, 2, 3, 99]}

    def test_points_go_to_both_partners(self):
        games = [G(round_id=10, table_no=1, points_a=97, points_b=60),
                 G(round_id=10, table_no=1, points_a=0, points_b=157)]
        rows = {r.player_id: r for r in jl.standings(self.names, self.tables, games)}
        self.assertEqual(rows[1].points, 97)  # Lea (Sitz 1)
        self.assertEqual(rows[3].points, 97)  # Guddi (Sitz 3, Partner von Lea)
        self.assertEqual(rows[2].points, 217)  # Kev (Sitz 2)
        self.assertEqual(rows[2].matches, 1)
        self.assertEqual(rows[2].games, 2)
        self.assertEqual(rows[5].games, 0)  # Inga hat nicht gespielt
        self.assertNotIn(99, rows)  # «?» kommt nicht in die Rangliste
        self.assertAlmostEqual(rows[2].average, 108.5)

    def test_ties_share_rank(self):
        games = [G(round_id=10, table_no=1, points_a=97, points_b=60)]
        ranking = jl.standings(self.names, self.tables, games)
        self.assertEqual([(r.name, r.rank) for r in ranking[:3]],
                         [("Guddi", 1), ("Lea", 1), ("Kev", 3)])

    def test_trend(self):
        tables = {**self.tables, (11, 1): [2, 1, 4, 3]}
        games = [G(round_id=10, table_no=1, points_a=97, points_b=60),
                 G(round_id=11, table_no=1, points_a=150, points_b=7)]
        now = jl.standings(self.names, tables, games)
        before = jl.standings(self.names, tables, games, skip_round=11)
        rows = {r.player_id: r for r in jl.add_trend(now, before)}
        self.assertEqual(rows[2].rank, 1)  # Kev: 60 + 150
        self.assertEqual(rows[2].trend, 2)  # von Rang 3 auf 1
        self.assertIsNone(rows[4].trend)  # Tobi hatte vorher noch nicht gespielt


if __name__ == "__main__":
    unittest.main()
