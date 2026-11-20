"""SQLite-Ablage fürs Jassturnier – alles in einer Datei, auch die Fotos."""

from __future__ import annotations

import io
import os
import re
import sqlite3
import tempfile
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from jass_logic import GAMES_PER_ROUND, JOKER, SEATS, TOTAL, validate_points

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO meta (key, value) VALUES ('version', '0');

CREATE TABLE IF NOT EXISTS players (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    is_joker  INTEGER NOT NULL DEFAULT 0,
    active    INTEGER NOT NULL DEFAULT 1,
    photo     BLOB,
    thumb     BLOB,
    photo_rev INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS players_name
    ON players (name COLLATE NOCASE) WHERE is_joker = 0;

CREATE TABLE IF NOT EXISTS rounds (
    id         INTEGER PRIMARY KEY,
    number     INTEGER NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS seats (
    round_id  INTEGER NOT NULL REFERENCES rounds (id) ON DELETE CASCADE,
    table_no  INTEGER NOT NULL,
    seat_no   INTEGER NOT NULL CHECK (seat_no BETWEEN 1 AND {SEATS}),
    player_id INTEGER NOT NULL REFERENCES players (id),
    PRIMARY KEY (round_id, table_no, seat_no),
    UNIQUE (round_id, player_id)
);

CREATE TABLE IF NOT EXISTS games (
    id         INTEGER PRIMARY KEY,
    round_id   INTEGER NOT NULL REFERENCES rounds (id) ON DELETE CASCADE,
    table_no   INTEGER NOT NULL,
    game_no    INTEGER NOT NULL CHECK (game_no BETWEEN 1 AND {GAMES_PER_ROUND}),
    trump      TEXT,
    points_a   INTEGER NOT NULL CHECK (points_a BETWEEN 0 AND {TOTAL}),
    points_b   INTEGER NOT NULL CHECK (points_b BETWEEN 0 AND {TOTAL}),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    CHECK (points_a + points_b = {TOTAL}),
    UNIQUE (round_id, table_no, game_no)
);
"""

REQUIRED_TABLES = {"meta", "players", "rounds", "seats", "games"}


class GameExists(Exception):
    """Spiel wurde schon (von jemand anderem) eingetragen."""


class RoundConflict(Exception):
    """Runde passt nicht (schon ausgelost / schon gespielt)."""


@dataclass(frozen=True)
class Player:
    id: int
    name: str
    is_joker: bool
    active: bool
    photo_rev: int  # 0 = kein Foto

    @property
    def has_photo(self) -> bool:
        return self.photo_rev > 0


@dataclass(frozen=True)
class Round:
    id: int
    number: int


@dataclass(frozen=True)
class Game:
    id: int
    round_id: int
    table_no: int
    game_no: int
    trump: str | None
    points_a: int
    points_b: int


def clean_name(name: str) -> str:
    return " ".join(str(name or "").split())


def name_keys(text: str) -> set[str]:
    """Vergleichsschlüssel für Namen/Dateinamen («Kägi» = «kagi» = «kaegi»)."""
    low = text.casefold()
    plain = "".join(c for c in unicodedata.normalize("NFKD", low) if not unicodedata.combining(c))
    keys = {re.sub(r"[^a-z0-9]", "", plain)}
    keys.add(re.sub(r"[^a-z0-9]", "", plain.replace("ae", "a").replace("oe", "o").replace("ue", "u")))
    return {k for k in keys if k}


def prepare_photo(data: bytes) -> tuple[bytes, bytes]:
    """Foto drehen (EXIF), auf Hochformat 3:4 zuschneiden -> (gross, klein) als JPEG."""
    from PIL import Image, ImageOps

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:  # kaputte oder unbekannte Datei
        raise ValueError("Das Bild konnte nicht gelesen werden (bitte JPG oder PNG).") from exc

    def jpeg(size, quality):
        out = io.BytesIO()
        fitted = ImageOps.fit(img, size, Image.Resampling.LANCZOS, centering=(0.5, 0.4))
        fitted.save(out, "JPEG", quality=quality, optimize=True)
        return out.getvalue()

    return jpeg((360, 480), 82), jpeg((150, 200), 80)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------ Verbindung

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write(self):
        """Schreibtransaktion; erhöht die Version (dafür pollt die Live-Ansicht)."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute(
                    "UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'version'"
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def version(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
        return int(row[0]) if row else 0

    def setting(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        if key == "version":
            raise ValueError("reserviert")
        with self._write() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ------------------------------------------------------------ Spieler

    def players(self, include_jokers: bool = False) -> list[Player]:
        sql = "SELECT id, name, is_joker, active, photo_rev FROM players"
        if not include_jokers:
            sql += " WHERE is_joker = 0"
        sql += " ORDER BY is_joker, name COLLATE NOCASE, id"
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [
            Player(r["id"], r["name"], bool(r["is_joker"]), bool(r["active"]), r["photo_rev"])
            for r in rows
        ]

    def seed_players(self, names) -> bool:
        """Füllt eine leere Teilnehmerliste (nur beim allerersten Start)."""
        names = [n for n in (clean_name(n) for n in names) if n and n != "?"]
        if not names or self.players():
            return False
        with self._write() as conn:
            if conn.execute("SELECT 1 FROM players WHERE is_joker = 0 LIMIT 1").fetchone():
                return False
            for name in names:
                conn.execute("INSERT OR IGNORE INTO players (name) VALUES (?)", (name,))
        return True

    def add_player(self, name: str) -> int:
        name = self._checked_name(name)
        try:
            with self._write() as conn:
                return conn.execute("INSERT INTO players (name) VALUES (?)", (name,)).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f"«{name}» gibt es schon.") from None

    def rename_player(self, player_id: int, name: str) -> None:
        name = self._checked_name(name)
        try:
            with self._write() as conn:
                conn.execute(
                    "UPDATE players SET name = ? WHERE id = ? AND is_joker = 0", (name, player_id)
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"«{name}» gibt es schon.") from None

    def set_active(self, player_id: int, active: bool) -> None:
        with self._write() as conn:
            conn.execute("UPDATE players SET active = ? WHERE id = ?", (int(active), player_id))

    def delete_player(self, player_id: int) -> None:
        with self._write() as conn:
            if conn.execute("SELECT 1 FROM seats WHERE player_id = ? LIMIT 1", (player_id,)).fetchone():
                raise ValueError("Hat schon gespielt – bitte stattdessen deaktivieren.")
            conn.execute("DELETE FROM players WHERE id = ? AND is_joker = 0", (player_id,))

    @staticmethod
    def _checked_name(name: str) -> str:
        name = clean_name(name)
        if not name:
            raise ValueError("Bitte einen Namen eingeben.")
        if name == "?":
            raise ValueError("«?» ist für freie Plätze reserviert.")
        if len(name) > 30:
            raise ValueError("Name ist zu lang (max. 30 Zeichen).")
        return name

    # ------------------------------------------------------------ Fotos

    def set_photo(self, player_id: int, photo: bytes, thumb: bytes) -> None:
        with self._write() as conn:
            conn.execute(
                "UPDATE players SET photo = ?, thumb = ?, photo_rev = "
                "(SELECT CAST(value AS INTEGER) + 1 FROM meta WHERE key = 'version') "
                "WHERE id = ?",
                (photo, thumb, player_id),
            )

    def clear_photo(self, player_id: int) -> None:
        with self._write() as conn:
            conn.execute(
                "UPDATE players SET photo = NULL, thumb = NULL, photo_rev = 0 WHERE id = ?",
                (player_id,),
            )

    def photo(self, player_id: int, size: str = "thumb") -> bytes | None:
        col = "thumb" if size == "thumb" else "photo"
        with self._connect() as conn:
            row = conn.execute(f"SELECT {col} FROM players WHERE id = ?", (player_id,)).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------ Runden

    def rounds(self) -> list[Round]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, number FROM rounds ORDER BY number").fetchall()
        return [Round(r["id"], r["number"]) for r in rows]

    def tables(self, round_id: int | None = None) -> dict[tuple[int, int], list[int]]:
        """{(round_id, table_no): [Sitz 1, Sitz 2, Sitz 3, Sitz 4]}"""
        sql = "SELECT round_id, table_no, seat_no, player_id FROM seats"
        args: tuple = ()
        if round_id is not None:
            sql += " WHERE round_id = ?"
            args = (round_id,)
        result: dict[tuple[int, int], list] = {}
        with self._connect() as conn:
            for r in conn.execute(sql + " ORDER BY round_id, table_no, seat_no", args):
                seats = result.setdefault((r["round_id"], r["table_no"]), [None] * SEATS)
                seats[r["seat_no"] - 1] = r["player_id"]
        return result

    def create_round(self, tables, number: int) -> Round:
        """Speichert eine ausgeloste Runde. JOKER-Plätze werden zu «?»-Spielern."""
        with self._write() as conn:
            last = conn.execute("SELECT COALESCE(MAX(number), 0) FROM rounds").fetchone()[0]
            if last != number - 1:
                raise RoundConflict(f"Runde {number} wurde bereits ausgelost.")
            round_id = conn.execute("INSERT INTO rounds (number) VALUES (?)", (number,)).lastrowid
            self._insert_seats(conn, round_id, tables)
        return Round(round_id, number)

    def redraw_round(self, round_id: int, tables) -> None:
        """Tische einer Runde neu setzen – nur solange dort noch nichts gespielt wurde."""
        with self._write() as conn:
            if conn.execute("SELECT 1 FROM games WHERE round_id = ? LIMIT 1", (round_id,)).fetchone():
                raise RoundConflict("In dieser Runde wurde schon gespielt.")
            conn.execute("DELETE FROM seats WHERE round_id = ?", (round_id,))
            self._insert_seats(conn, round_id, tables)

    def delete_round(self, round_id: int) -> None:
        with self._write() as conn:
            conn.execute("DELETE FROM rounds WHERE id = ?", (round_id,))

    @staticmethod
    def _insert_seats(conn, round_id: int, tables) -> None:
        n_jokers = sum(p is JOKER for t in tables for p in t)
        jokers = [r[0] for r in conn.execute("SELECT id FROM players WHERE is_joker = 1 ORDER BY id")]
        while len(jokers) < n_jokers:
            jokers.append(conn.execute("INSERT INTO players (name, is_joker) VALUES ('?', 1)").lastrowid)
        free = iter(jokers)
        for table_no, table in enumerate(tables, start=1):
            if len(table) != SEATS:
                raise ValueError("Jeder Tisch braucht genau 4 Plätze.")
            for seat_no, pid in enumerate(table, start=1):
                conn.execute(
                    "INSERT INTO seats (round_id, table_no, seat_no, player_id) VALUES (?, ?, ?, ?)",
                    (round_id, table_no, seat_no, next(free) if pid is JOKER else pid),
                )

    # ------------------------------------------------------------ Spiele

    def games(self, round_id: int | None = None) -> list[Game]:
        sql = "SELECT id, round_id, table_no, game_no, trump, points_a, points_b FROM games"
        args: tuple = ()
        if round_id is not None:
            sql += " WHERE round_id = ?"
            args = (round_id,)
        with self._connect() as conn:
            rows = conn.execute(sql + " ORDER BY round_id, table_no, game_no", args).fetchall()
        return [Game(*tuple(r)) for r in rows]

    def add_game(self, round_id: int, table_no: int, game_no: int, trump, a, b) -> int:
        errors = validate_points(a, b)
        if errors:
            raise ValueError(errors[0])
        try:
            with self._write() as conn:
                return conn.execute(
                    "INSERT INTO games (round_id, table_no, game_no, trump, points_a, points_b) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (round_id, table_no, game_no, trump or None, int(a), int(b)),
                ).lastrowid
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise GameExists(f"Spiel {game_no} an Tisch {table_no} ist schon eingetragen.") from None
            raise ValueError(f"Ungültiges Resultat ({exc}).") from None

    def update_game(self, game_id: int, trump, a, b) -> None:
        errors = validate_points(a, b)
        if errors:
            raise ValueError(errors[0])
        with self._write() as conn:
            conn.execute(
                "UPDATE games SET trump = ?, points_a = ?, points_b = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (trump or None, int(a), int(b), game_id),
            )

    def delete_game(self, game_id: int) -> None:
        with self._write() as conn:
            conn.execute("DELETE FROM games WHERE id = ?", (game_id,))

    # ------------------------------------------------------------ Verwaltung

    def reset_tournament(self) -> None:
        """Löscht alle Runden und Resultate (Teilnehmer und Fotos bleiben)."""
        with self._write() as conn:
            conn.execute("DELETE FROM rounds")
            conn.execute("DELETE FROM players WHERE is_joker = 1")

    def backup_bytes(self) -> bytes:
        """Konsistente Kopie der ganzen Datenbank (inkl. Fotos)."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "backup.db"
            dst = sqlite3.connect(target)
            try:
                with self._connect() as src:
                    src.backup(dst)
            finally:
                dst.close()
            return target.read_bytes()

    def restore(self, data: bytes) -> None:
        """Ersetzt alle Daten durch ein Backup."""
        fd, tmp = tempfile.mkstemp(suffix=".db")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            src = sqlite3.connect(tmp)
            try:
                names = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                if not REQUIRED_TABLES <= names:
                    raise ValueError("Das ist keine Backup-Datei vom Jassturnier.")
                with self._connect() as dst:
                    src.backup(dst)
            except sqlite3.DatabaseError:
                raise ValueError("Das ist keine gültige Backup-Datei.") from None
            finally:
                src.close()
        finally:
            os.unlink(tmp)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
        with self._write():
            pass  # Version erhöhen, damit alle Ansichten neu laden
