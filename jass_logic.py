"""Jass-Regeln fürs Turnier: Punkte prüfen, Tische auslosen, Rangliste.

Modus: Schieber zu viert, Sitz 1+3 gegen Sitz 2+4. Pro Runde macht jede Person
einmal Trumpf, also 4 Spiele pro Tisch. Kein Weis, keine Stöck, alle Farben
zählen einfach, Match ohne Bonus -> jedes Spiel hat genau 157 Punkte.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

TOTAL = 157  # Punkte pro Spiel
SEATS = 4  # Personen pro Tisch
GAMES_PER_ROUND = 4  # jede Person macht einmal Trumpf
PARTNER_IDX = ((0, 2), (1, 3))  # Sitz 1+3 und Sitz 2+4 (0-basiert)
JOKER = None  # Platzhalter «?» beim Auslosen

TRUMPS = ("Eicheln", "Schellen", "Rosen", "Schilten", "Obenabe", "Undenufe")

# Gewichte für die Auslosung: Wiederholungen möglichst vermeiden
W_PARTNER = 10  # gleiche Partnerschaft wie in einer früheren Runde
W_MATE = 3  # wieder am gleichen Tisch
W_JOKERS = 1000  # zwei «?» am gleichen Tisch


# ---------------------------------------------------------------- Punkte


def team_of_seat(seat: int) -> str:
    """Sitz 1-4 -> 'A' (Sitz 1+3) oder 'B' (Sitz 2+4)."""
    return "A" if seat % 2 == 1 else "B"


def complement(points: int) -> int:
    """Punkte des anderen Teams."""
    return TOTAL - points


def validate_points(a, b) -> list[str]:
    """Prüft ein Spielresultat. Leere Liste = alles in Ordnung."""
    if a is None or b is None:
        return ["Bitte für beide Teams Punkte eintragen."]
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return ["Punkte müssen Zahlen sein."]
    if not (fa.is_integer() and fb.is_integer()):
        return ["Bitte nur ganze Punkte eintragen."]
    a, b = int(fa), int(fb)
    if not (0 <= a <= TOTAL and 0 <= b <= TOTAL):
        return [f"Punkte müssen zwischen 0 und {TOTAL} liegen."]
    if a + b != TOTAL:
        return [f"{a} + {b} = {a + b} – es müssen genau {TOTAL} Punkte sein."]
    if 1 in (a, b):
        # keine Karte zählt 1 Punkt, der letzte Stich zählt 5
        return ["1 Punkt gibt es im Jass nicht – bitte nachzählen."]
    return []


def is_match(a: int, b: int) -> bool:
    return TOTAL in (a, b)


def next_game_no(played) -> int | None:
    """Nächstes offenes Spiel (1-4) an einem Tisch, None wenn fertig."""
    done = set(played)
    return next((k for k in range(1, GAMES_PER_ROUND + 1) if k not in done), None)


# ---------------------------------------------------------------- Auslosung


def tables_needed(n_players: int) -> int:
    return -(-n_players // SEATS)


def jokers_needed(n_players: int) -> int:
    """Wie viele «?» es braucht, damit alle Tische voll sind (18 -> 2)."""
    return tables_needed(n_players) * SEATS - n_players


def pair_counts(past_tables) -> tuple[Counter, Counter]:
    """Zählt frühere Partner- und Tischpaare (Tische in Sitzreihenfolge)."""
    partners, mates = Counter(), Counter()
    for table in past_tables:
        for i, j in combinations(range(len(table)), 2):
            key = frozenset((table[i], table[j]))
            mates[key] += 1
            if (i, j) in PARTNER_IDX:
                partners[key] += 1
    return partners, mates


def penalty(tables, partners: Counter, mates: Counter) -> int:
    """Je kleiner, desto weniger Wiederholungen gegenüber früheren Runden."""
    total = 0
    for table in tables:
        jokers = sum(p is JOKER for p in table)
        if jokers > 1:
            total += W_JOKERS * (jokers - 1)
        for i, j in combinations(range(len(table)), 2):
            if table[i] is JOKER and table[j] is JOKER:
                continue
            key = frozenset((table[i], table[j]))
            total += W_MATE * mates[key]
            if (i, j) in PARTNER_IDX:
                total += W_PARTNER * partners[key]
    return total


def _random_tables(players: list, n_jokers: int, n_tables: int, rng: random.Random):
    tables = [[] for _ in range(n_tables)]
    # «?» auf verschiedene Tische verteilen
    order = rng.sample(range(n_tables), n_tables)
    for k in range(n_jokers):
        tables[order[k % n_tables]].append(JOKER)
    pool = players[:]
    rng.shuffle(pool)
    for table in tables:
        while len(table) < SEATS:
            table.append(pool.pop())
        rng.shuffle(table)
    return tables


def draw_tables(player_ids, past_tables=(), rng: random.Random | None = None,
                restarts: int = 40, steps: int = 300) -> list[list]:
    """Lost neue Tische aus.

    Fehlende Plätze werden mit JOKER («?») aufgefüllt, höchstens einer pro Tisch.
    Frühere Partner und Tischnachbarn werden möglichst vermieden (zufälliger
    Start + Tauschen, solange es besser wird). Rückgabe: Liste von Tischen mit
    je 4 Einträgen in Sitzreihenfolge 1-4.
    """
    rng = rng or random.Random()
    players = list(player_ids)
    if len(set(players)) != len(players):
        raise ValueError("Spieler doppelt in der Liste.")
    n_tables = tables_needed(len(players))
    if n_tables == 0:
        return []
    n_jokers = n_tables * SEATS - len(players)
    partners, mates = pair_counts(past_tables)

    best, best_score = None, None
    for _ in range(restarts):
        tables = _random_tables(players, n_jokers, n_tables, rng)
        score = penalty(tables, partners, mates)
        for _ in range(steps):
            if score == 0:
                break
            t1, s1 = rng.randrange(n_tables), rng.randrange(SEATS)
            t2, s2 = rng.randrange(n_tables), rng.randrange(SEATS)
            a, b = tables[t1][s1], tables[t2][s2]
            if (t1, s1) == (t2, s2) or (a is JOKER and b is JOKER):
                continue
            tables[t1][s1], tables[t2][s2] = b, a
            new = penalty(tables, partners, mates)
            if new <= score:
                score = new
            else:
                tables[t1][s1], tables[t2][s2] = a, b
        if best_score is None or score < best_score:
            best, best_score = [t[:] for t in tables], score
        if best_score == 0:
            break
    return best


# ---------------------------------------------------------------- Rangliste


@dataclass
class Standing:
    player_id: int
    name: str
    points: int = 0
    games: int = 0
    matches: int = 0
    rank: int = 0
    prev_rank: int | None = None

    @property
    def average(self) -> float:
        return self.points / self.games if self.games else 0.0

    @property
    def trend(self) -> int | None:
        """Gewonnene Plätze seit vor der letzten Runde (negativ = verloren)."""
        return None if self.prev_rank is None else self.prev_rank - self.rank


def standings(names: dict, tables: dict, games, skip_round=None) -> list[Standing]:
    """Rangliste aus allen Spielen.

    names: {player_id: name} – nur echte Spieler (ohne «?»)
    tables: {(round_id, table_no): [p1, p2, p3, p4]}
    games: Objekte mit round_id, table_no, points_a, points_b
    """
    rows = {pid: Standing(pid, name) for pid, name in names.items()}
    for g in games:
        if g.round_id == skip_round:
            continue
        seat_ids = tables.get((g.round_id, g.table_no))
        if not seat_ids:
            continue
        for seat, pid in enumerate(seat_ids, start=1):
            row = rows.get(pid)
            if row is None:
                continue
            pts = g.points_a if team_of_seat(seat) == "A" else g.points_b
            row.points += pts
            row.games += 1
            row.matches += pts == TOTAL
    ordered = sorted(rows.values(), key=lambda r: (-r.points, r.name.casefold()))
    rank, last = 0, None
    for i, row in enumerate(ordered, start=1):
        if row.points != last:  # Punktgleich = gleicher Rang
            rank, last = i, row.points
        row.rank = rank
    return ordered


def add_trend(current: list[Standing], previous: list[Standing]) -> list[Standing]:
    """Setzt prev_rank aus einer früheren Rangliste (nur wer schon gespielt hat)."""
    prev = {r.player_id: r.rank for r in previous if r.games}
    for r in current:
        r.prev_rank = prev.get(r.player_id)
    return current
