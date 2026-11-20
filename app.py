"""Jassturnier – Tische auslosen, Resultate eintragen, Rangliste live.

Start:  streamlit run app.py
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import jass_logic as jl
import jass_theme as ui
from jass_db import (
    Game, GameExists, Player, Round, RoundConflict, Store, clean_name, name_keys, prepare_photo,
)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("JASS_DATA_DIR") or APP_DIR / "data")
DEFAULT_PIN = "157"
POLL_SECONDS = 5
PHOTO_TYPES = ["jpg", "jpeg", "png", "webp"]
SUBTITLE = "Schieber · 157 Punkte pro Spiel · ohne Weis · Match ohne Bonus"
RANGLISTE, TISCHE, EINTRAGEN, SPIELER, ADMIN = VIEWS = (
    "🏆 Rangliste", "🃏 Tische", "✍️ Eintragen", "📸 Spieler", "⚙️ Admin",
)

st.set_page_config(page_title="Jassturnier", page_icon="🃏", layout="centered")


@st.cache_resource
def get_store(path: str) -> Store:
    store = Store(path)
    seed = APP_DIR / "teilnehmer.txt"
    if seed.exists():
        lines = seed.read_text(encoding="utf-8").splitlines()
        store.seed_players(line for line in lines if not line.lstrip().startswith("#"))
    return store


store = get_store(str(DATA_DIR / "jassturnier.db"))


# ------------------------------------------------------------ Daten pro Durchlauf


@dataclass
class Snap:
    players: dict[int, Player]  # alle, inkl. «?»-Plätze
    rounds: list[Round]
    tables: dict[tuple[int, int], list[int]]
    games: list[Game]
    title: str

    @property
    def current(self) -> Round | None:
        return self.rounds[-1] if self.rounds else None

    @property
    def real(self) -> list[Player]:
        return [p for p in self.players.values() if not p.is_joker]

    def round_tables(self, rnd: Round) -> dict[int, list[Player]]:
        return {
            t: [self.players[p] for p in seats]
            for (r, t), seats in sorted(self.tables.items())
            if r == rnd.id
        }

    def round_games(self, rnd: Round) -> dict[int, dict[int, Game]]:
        result: dict[int, dict[int, Game]] = {}
        for g in self.games:
            if g.round_id == rnd.id:
                result.setdefault(g.table_no, {})[g.game_no] = g
        return result

    def played(self, rnd: Round) -> int:
        return sum(1 for g in self.games if g.round_id == rnd.id)

    def complete(self, rnd: Round) -> bool:
        games = self.round_games(rnd)
        tables = self.round_tables(rnd)
        return bool(tables) and all(jl.next_game_no(games.get(t, {})) is None for t in tables)

    def seat_of(self, rnd: Round, player_id: int) -> tuple[int, int] | None:
        for (r, t), seats in self.tables.items():
            if r == rnd.id and player_id in seats:
                return t, seats.index(player_id) + 1
        return None

    def past_tables(self, exclude_round: int | None = None) -> list[list]:
        return [
            [jl.JOKER if self.players[p].is_joker else p for p in seats]
            for (r, _), seats in self.tables.items()
            if r != exclude_round
        ]

    def ranking(self) -> list[jl.Standing]:
        names = {p.id: p.name for p in self.real}
        now = jl.standings(names, self.tables, self.games)
        if self.games:  # Trend: Vergleich mit dem Stand vor der letzten Runde
            last = max(g.round_id for g in self.games)
            jl.add_trend(now, jl.standings(names, self.tables, self.games, skip_round=last))
        return now


def load() -> Snap:
    return Snap(
        players={p.id: p for p in store.players(include_jokers=True)},
        rounds=store.rounds(),
        tables=store.tables(),
        games=store.games(),
        title=store.setting("title") or "Jassturnier",
    )


@st.cache_data(max_entries=2000, show_spinner=False)
def _photo_uri(player_id: int, rev: int, size: str) -> str | None:
    data = store.photo(player_id, size)
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii") if data else None


def photo(p: Player | None, size: str = "thumb") -> str | None:
    if p is None or not p.has_photo:
        return None
    return _photo_uri(p.id, p.photo_rev, size)


def thumbs(players) -> dict[int, str | None]:
    return {p.id: photo(p) for p in players}


# ------------------------------------------------------------ kleine Helfer


def flash(kind: str, text: str) -> None:
    """Meldung für den nächsten Durchlauf merken (kind: toast/success/info/warning/error)."""
    st.session_state.setdefault("_flash", []).append((kind, text))


def show_flash() -> None:
    for kind, text in st.session_state.pop("_flash", []):
        if kind == "toast":
            st.toast(text)
        else:
            getattr(st, kind)(text)
    if st.session_state.pop("_balloons", False):
        st.balloons()


def admin_pin() -> tuple[str, bool]:
    """(PIN, ist_standard) – aus Secrets, Umgebungsvariable oder Standard."""
    pin = os.environ.get("JASS_ADMIN_PIN")
    try:
        pin = st.secrets.get("admin_pin", pin)
    except Exception:  # keine secrets.toml vorhanden
        pass
    return (str(pin), False) if pin else (DEFAULT_PIN, True)


def trump_label(trump: str) -> str:
    return {"Obenabe": ":material/north: Obenabe", "Undenufe": ":material/south: Undenufe"}.get(trump, trump)


@st.fragment(run_every=POLL_SECONDS)
def live_sync(watch: tuple[str, ...] = ()) -> None:
    """Fragt alle paar Sekunden die Version ab und lädt neu, sobald jemand etwas einträgt.

    Solange in `watch` (Eingabefelder) etwas steht, wird nicht neu geladen.
    """
    if store.version() != st.session_state.get("seen_version"):
        if any(st.session_state.get(k) is not None for k in watch):
            st.html(ui.live_html(stale=True))
            return
        st.rerun()
    st.html(ui.live_html())


# ------------------------------------------------------------ Aktionen (Callbacks)


def sync_points(src: str, dst: str) -> None:
    """Das andere Team bekommt automatisch den Rest auf 157."""
    value = st.session_state.get(src)
    if value is not None and 0 <= value <= jl.TOTAL:
        st.session_state[dst] = jl.complement(int(value))


def _read_points(ka: str, kb: str):
    a, b = st.session_state.get(ka), st.session_state.get(kb)
    if a is None and b is not None:
        a = jl.complement(int(b))
    elif b is None and a is not None:
        b = jl.complement(int(a))
    return a, b


def form_message(key: str) -> None:
    """Meldung direkt beim Formular anzeigen (auf dem Handy sieht man oben nichts)."""
    msg = st.session_state.pop(key, None)
    if msg:
        getattr(st, msg[0])(msg[1])


def save_game(round_id: int, table_no: int, game_no: int, ka: str, kb: str, kt: str) -> None:
    a, b = _read_points(ka, kb)
    errors = jl.validate_points(a, b)
    if errors:
        st.session_state.entry_msg = ("error", errors[0])
        return
    try:
        store.add_game(round_id, table_no, game_no, st.session_state.get(kt), int(a), int(b))
    except GameExists:
        st.session_state.entry_msg = (
            "warning", f"Spiel {game_no} an Tisch {table_no} hat gerade jemand anderes eingetragen – bitte oben kontrollieren.",
        )
        return
    except ValueError as exc:
        st.session_state.entry_msg = ("error", str(exc))
        return
    flash("toast", f"✅ Spiel {game_no} gespeichert: {int(a)} : {int(b)}")
    if jl.is_match(int(a), int(b)):
        st.session_state._balloons = True


def update_game(game_id: int, game_no: int, ka: str, kb: str, kt: str, msg_key: str) -> None:
    a, b = _read_points(ka, kb)
    errors = jl.validate_points(a, b)
    if errors:
        st.session_state[msg_key] = ("error", errors[0])
        return
    store.update_game(game_id, st.session_state.get(kt), int(a), int(b))
    flash("toast", f"✏️ Spiel {game_no} korrigiert: {int(a)} : {int(b)}")


def delete_game(game_id: int, game_no: int, table_no: int) -> None:
    store.delete_game(game_id)
    flash("toast", f"🗑️ Spiel {game_no} an Tisch {table_no} gelöscht")


def go_entry(table_no: int) -> None:
    st.session_state.entry_table = table_no
    st.session_state.entry_pinned = True
    st.session_state.view = EINTRAGEN


def draw_round(number: int, force: bool) -> None:
    snap = load()  # frisch laden: vielleicht hat schon jemand anderes ausgelost
    cur = snap.current
    if cur and not force and not snap.complete(cur):
        flash("warning", "Es sind noch nicht alle Tische fertig.")
        return
    active = [p.id for p in snap.real if p.active]
    if len(active) < 2:
        flash("error", "Es braucht mindestens 2 aktive Spieler.")
        return
    try:
        store.create_round(jl.draw_tables(active, snap.past_tables()), number)
    except RoundConflict as exc:
        flash("info", f"{exc} Die Ansicht ist jetzt aktuell.")
        return
    flash("toast", f"🔀 Runde {number} ist ausgelost – guet Jass!")
    st.session_state.view = TISCHE


def redraw_round(round_id: int, number: int) -> None:
    snap = load()
    active = [p.id for p in snap.real if p.active]
    try:
        store.redraw_round(round_id, jl.draw_tables(active, snap.past_tables(exclude_round=round_id)))
    except RoundConflict as exc:
        flash("warning", str(exc))
        return
    flash("toast", f"🔁 Runde {number} neu ausgelost")


def delete_round(round_id: int, number: int) -> None:
    store.delete_round(round_id)
    flash("toast", f"🗑️ Runde {number} gelöscht")


def remove_photo(player_id: int, name: str) -> None:
    store.clear_photo(player_id)
    flash("toast", f"Foto von {name} entfernt")


def delete_player(player_id: int | None) -> None:
    if player_id is None:
        return
    try:
        store.delete_player(player_id)
    except ValueError as exc:
        flash("error", str(exc))
        return
    flash("toast", "Spieler gelöscht")


def reset_tournament() -> None:
    store.reset_tournament()
    st.session_state.reset_word = ""
    flash("success", "Turnier zurückgesetzt – alle Runden und Resultate sind gelöscht.")


def logout() -> None:
    st.session_state.is_admin = False


# ------------------------------------------------------------ Kopfbereich


def identity_row(snap: Snap) -> Player | None:
    rnd = snap.current
    total = len(snap.round_tables(rnd)) * jl.GAMES_PER_ROUND if rnd else 0
    left, right = st.columns([1.25, 1], wrap=False, vertical_alignment="center")
    left.html(ui.status_html(rnd.number if rnd else None, snap.played(rnd) if rnd else 0, total))
    by_name = {p.name: p for p in snap.real}
    with right:
        name = st.selectbox(
            "Ich bin", sorted(by_name, key=str.casefold), index=None, key="ich",
            placeholder="👤 Wer bist du?", bind="query-params", label_visibility="collapsed",
        )
    return by_name.get(name)


def my_banner(snap: Snap, me: Player | None) -> None:
    rnd = snap.current
    if not me or not rnd:
        return
    where = snap.seat_of(rnd, me.id)
    if not where:
        st.html(ui.note_html("Diese Runde pausierst du", f"{me.name}, du bist in Runde {rnd.number} nicht eingeteilt."))
        return
    table_no, seat = where
    seats = snap.round_tables(rnd)[table_no]
    i = seat - 1
    partner, opponents = seats[(i + 2) % 4], [seats[(i + 1) % 4], seats[(i + 3) % 4]]
    st.html(ui.me_banner_html(me, photo(me), rnd.number, table_no, seat, partner, opponents))


def next_round_button(snap: Snap, force: bool = False, key: str = "next_round") -> None:
    number = (snap.current.number if snap.current else 0) + 1
    st.button(
        f"🔀 Runde {number} auslosen", key=key, type="primary", width="stretch",
        on_click=draw_round, args=(number, force),
    )


# ------------------------------------------------------------ Seiten


def page_rangliste(snap: Snap, me: Player | None) -> None:
    live_sync()
    rows = snap.ranking()
    if not rows:
        st.html(ui.note_html("Noch keine Teilnehmer", "Im Admin-Bereich Spieler erfassen.", suits=True))
        return
    if any(r.games for r in rows):
        top = [(r, snap.players[r.player_id], photo(snap.players[r.player_id], "photo")) for r in rows[:3]]
        st.html(ui.podium_html(top))
    else:
        st.html(ui.note_html("Noch keine Resultate", "Sobald das erste Spiel eingetragen ist, geht's hier live los.", suits=True))
    entries = [(r, snap.players[r.player_id], photo(snap.players[r.player_id])) for r in rows]
    st.html(ui.ranking_html(entries, me.id if me else None))


def page_tische(snap: Snap, me: Player | None) -> None:
    live_sync()
    rnd = snap.current
    if not rnd:
        st.html(ui.note_html("Noch keine Runde ausgelost", "Die Turnierleitung lost Runde 1 im Admin-Bereich aus.", suits=True))
        return
    tables = snap.round_tables(rnd)
    games = snap.round_games(rnd)
    if snap.complete(rnd):
        st.success(f"Alle Tische haben Runde {rnd.number} fertig gespielt.")
        next_round_button(snap)
    me_id = me.id if me else None
    # eigener Tisch zuerst
    order = sorted(tables, key=lambda t: (not any(p.id == me_id for p in tables[t]), t))
    uris = thumbs(p for seats in tables.values() for p in seats)
    for pair in (order[i:i + 2] for i in range(0, len(order), 2)):
        for col, t in zip(st.columns(2), pair):
            with col:
                st.html(ui.table_html(t, tables[t], uris, games.get(t, {}), me_id))
                if jl.next_game_no(games.get(t, {})) is not None:
                    st.button(f"✍️ Resultat Tisch {t} eintragen", key=f"go_{t}", width="stretch",
                              on_click=go_entry, args=(t,))


def page_eintragen(snap: Snap, me: Player | None) -> None:
    rnd = snap.current
    if not rnd:
        live_sync()
        st.html(ui.note_html("Noch keine Runde ausgelost", "Sobald die Tische ausgelost sind, kannst du hier Resultate eintragen.", suits=True))
        return
    tables = snap.round_tables(rnd)
    games = snap.round_games(rnd)
    options = sorted(tables)
    where = snap.seat_of(rnd, me.id) if me else None
    mine = where[0] if where else None

    # automatisch den eigenen Tisch wählen (bei neuer Runde oder anderer Person)
    pinned = st.session_state.pop("entry_pinned", False)
    auto = (me.id if me else None, rnd.id)
    if st.session_state.get("entry_auto") != auto:
        st.session_state.entry_auto = auto
        if mine and not pinned:
            st.session_state.entry_table = mine
    if st.session_state.get("entry_table") not in options:
        st.session_state.entry_table = mine or options[0]

    t = st.selectbox(
        "Tisch", options, key="entry_table", persist_state="session",
        format_func=lambda n: f"Tisch {n} – " + ", ".join(p.name for p in tables[n]),
    )
    seats = tables[t]
    table_games = games.get(t, {})
    k = jl.next_game_no(table_games)
    base = f"{rnd.id}_{t}_{k}"
    keys = (f"pa_{base}", f"pb_{base}", f"tr_{base}") if k else ()

    live_sync(keys)
    st.html(ui.table_html(t, seats, thumbs(seats), table_games, me.id if me else None))

    if k is None:
        if snap.complete(rnd):
            st.success("Alle Tische sind fertig!")
            next_round_button(snap)
        else:
            waiting = [str(n) for n in options if jl.next_game_no(games.get(n, {})) is not None]
            st.info(f"✓ Tisch {t} ist fertig. Es spielen noch: Tisch {', '.join(waiting)}.")
    else:
        ka, kb, kt = keys
        st.html(ui.entry_head_html(k, seats[k - 1]))
        st.pills("Trumpf (freiwillig)", jl.TRUMPS, key=kt, format_func=trump_label)
        points_inputs(seats, ka, kb)
        st.button(
            f"Spiel {k} speichern", key=f"save_{base}", type="primary", width="stretch",
            on_click=save_game, args=(rnd.id, t, k, ka, kb, kt),
        )
    form_message("entry_msg")

    with st.expander("✏️ Resultat korrigieren"):
        correction_editor(rnd, t, seats, table_games, "fix")


def points_inputs(seats: list[Player], ka: str, kb: str) -> None:
    c1, c2 = st.columns(2, wrap=False)
    c1.number_input(
        f"🔴 {seats[0].name} & {seats[2].name}", min_value=0, max_value=jl.TOTAL, value=None, step=1,
        key=ka, placeholder="Punkte", on_change=sync_points, args=(ka, kb),
    )
    c2.number_input(
        f"🟡 {seats[1].name} & {seats[3].name}", min_value=0, max_value=jl.TOTAL, value=None, step=1,
        key=kb, placeholder="Punkte", on_change=sync_points, args=(kb, ka),
    )
    st.html(ui.check_html(st.session_state.get(ka), st.session_state.get(kb)))


def correction_editor(rnd: Round, t: int, seats: list[Player], table_games: dict[int, Game], prefix: str) -> None:
    if not table_games:
        st.caption("An diesem Tisch ist noch kein Spiel eingetragen.")
        return
    nos = sorted(table_games)
    k = st.selectbox(
        "Welches Spiel?", nos, index=len(nos) - 1, key=f"{prefix}_sel_{rnd.id}_{t}",
        format_func=lambda n: f"Spiel {n} · {seats[n - 1].name} · {table_games[n].points_a} : {table_games[n].points_b}",
    )
    g = table_games[k]
    base = f"{prefix}_{g.id}"
    ka, kb, kt = f"{base}_a", f"{base}_b", f"{base}_t"
    if ka not in st.session_state:  # erstmals: Werte aus der Datenbank übernehmen
        st.session_state[ka], st.session_state[kb] = g.points_a, g.points_b
        st.session_state[kt] = g.trump if g.trump in jl.TRUMPS else None
    st.pills("Trumpf", jl.TRUMPS, key=kt, format_func=trump_label)
    points_inputs(seats, ka, kb)
    c1, c2 = st.columns(2, wrap=False)
    c1.button("Änderung speichern", key=f"{base}_save", type="primary", width="stretch",
              on_click=update_game, args=(g.id, k, ka, kb, kt, f"{prefix}_msg"))
    with c2.popover("🗑️ Löschen", width="stretch"):
        st.write(f"Spiel {k} an Tisch {t} wirklich löschen?")
        st.button("Ja, löschen", key=f"{base}_del", type="primary", on_click=delete_game, args=(g.id, k, t))
    form_message(f"{prefix}_msg")


def page_spieler(snap: Snap, me: Player | None) -> None:
    players = sorted(snap.real, key=lambda p: p.name.casefold())
    ranks = {r.player_id: r for r in snap.ranking()}
    st.html(ui.player_grid_html([(p, photo(p), ranks.get(p.id)) for p in players], me.id if me else None))

    st.markdown("#### 📸 Foto ändern")
    by_name = {p.name: p for p in players}
    names = list(by_name)
    pick = st.selectbox(
        "Wessen Foto?", names, index=names.index(me.name) if me and me.name in by_name else None,
        placeholder="Name wählen", key=f"photo_for_{me.id if me else 0}",
    )
    if not pick:
        return
    p = by_name[pick]
    c1, c2 = st.columns([1, 1.6], vertical_alignment="center")
    c1.html(ui.photo_card_html(p, photo(p, "photo")))
    with c2:
        n = st.session_state.get("upload_n", 0)
        upload = st.file_uploader(
            "Neues Foto", type=PHOTO_TYPES, key=f"upload_{p.id}_{n}", max_upload_size=25,
            help="Auf dem Handy kannst du hier auch direkt ein Selfie machen.",
        )
        if upload is not None:
            try:
                big, small = prepare_photo(upload.getvalue())
            except ValueError as exc:
                st.error(str(exc))
            else:
                store.set_photo(p.id, big, small)
                st.session_state.upload_n = n + 1
                flash("toast", f"📸 Foto von {p.name} gespeichert")
                st.rerun()
        if p.has_photo:
            st.button("Foto entfernen", key=f"rm_{p.id}", on_click=remove_photo, args=(p.id, p.name))


def page_admin(snap: Snap, me: Player | None) -> None:
    pin, is_default = admin_pin()
    if not st.session_state.get("is_admin"):
        with st.form("login"):
            entered = st.text_input("Admin-PIN", type="password")
            ok = st.form_submit_button("Anmelden", type="primary")
        if ok:
            if entered.strip() == pin:
                st.session_state.is_admin = True
                st.rerun()
            st.error("Falsche PIN.")
        st.caption("Hier verwaltet die Turnierleitung Teilnehmer, Runden, Korrekturen und Backups.")
        return
    if is_default:
        st.warning(f"Es ist noch die Standard-PIN «{DEFAULT_PIN}» aktiv – bitte `admin_pin` in den Secrets setzen (siehe README).")
    admin_rounds(snap)
    admin_players(snap)
    admin_photos(snap)
    admin_results(snap)
    admin_backup(snap)
    st.button("Abmelden", on_click=logout)


def admin_rounds(snap: Snap) -> None:
    with st.expander("🎲 Runden auslosen", expanded=True):
        active = [p for p in snap.real if p.active]
        n, jokers = len(active), jl.jokers_needed(len(active))
        info = f"{n} aktive Spieler → {jl.tables_needed(n)} Tische"
        st.caption(info + (f", dazu {jokers}× «?» als freier Platz" if jokers else " – geht genau auf"))
        cur = snap.current
        if cur is None:
            next_round_button(snap, force=True, key="adm_first")
            return
        complete, played = snap.complete(cur), snap.played(cur)
        st.markdown(f"Aktuell: **Runde {cur.number}** – " + ("alle Tische fertig ✓" if complete else f"{played} Spiele eingetragen"))
        if complete or st.checkbox("Neue Runde auslosen, obwohl noch nicht alle Tische fertig sind", key="adm_force"):
            next_round_button(snap, force=True, key="adm_next")
        if played == 0:
            st.button(f"🔁 Runde {cur.number} neu auslosen", key="adm_redraw", width="stretch",
                      on_click=redraw_round, args=(cur.id, cur.number),
                      help="Z.B. wenn noch jemand dazugekommen ist. Geht nur, solange niemand gespielt hat.")
        with st.popover(f"🗑️ Runde {cur.number} löschen", width="stretch"):
            st.write(f"Löscht Runde {cur.number} mit allen {played} Resultaten. Das kann man nicht rückgängig machen.")
            st.button("Ja, Runde löschen", key="adm_del_round", type="primary",
                      on_click=delete_round, args=(cur.id, cur.number))


def admin_players(snap: Snap) -> None:
    with st.expander("👥 Teilnehmer"):
        players = sorted(snap.real, key=lambda p: p.name.casefold())
        df = pd.DataFrame(
            {
                "Name": [p.name for p in players],
                "Aktiv": [p.active for p in players],
                "Foto": ["📸" if p.has_photo else "–" for p in players],
            },
            index=[p.id for p in players],
        )
        signature = hash(tuple((p.id, p.name, p.active, p.has_photo) for p in players))
        edited = st.data_editor(
            df, key=f"players_{signature}", hide_index=True, disabled=["Foto"], width="stretch",
            column_config={
                "Name": st.column_config.TextColumn("Name", required=True, max_chars=30),
                "Aktiv": st.column_config.CheckboxColumn("Aktiv", help="Nur aktive Spieler werden ausgelost."),
                "Foto": st.column_config.TextColumn("Foto", width="small"),
            },
        )
        st.caption("Wer pausiert oder heimgeht: «Aktiv» abwählen – die Punkte bleiben in der Rangliste.")
        if st.button("Änderungen speichern", key="players_save"):
            changed = 0
            for pid, row in edited.iterrows():
                p = snap.players.get(int(pid))
                if p is None:
                    continue
                try:
                    if clean_name(row["Name"]) != p.name:
                        store.rename_player(p.id, row["Name"])
                        changed += 1
                    if bool(row["Aktiv"]) != p.active:
                        store.set_active(p.id, bool(row["Aktiv"]))
                        changed += 1
                except ValueError as exc:
                    flash("error", f"{p.name}: {exc}")
            if changed:
                flash("toast", "👥 Teilnehmer gespeichert")
            st.rerun()

        with st.form("add_player", clear_on_submit=True):
            c1, c2 = st.columns([3, 1.4], wrap=False, vertical_alignment="bottom")
            new_name = c1.text_input("Neuer Spieler", placeholder="Name")
            if c2.form_submit_button("Hinzufügen", width="stretch"):
                try:
                    store.add_player(new_name)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    flash("toast", f"👋 {clean_name(new_name)} ist dabei")
                    st.rerun()

        seated = {p for seats in snap.tables.values() for p in seats}
        deletable = [p for p in players if p.id not in seated]
        if deletable:
            c1, c2 = st.columns([3, 1.4], wrap=False, vertical_alignment="bottom")
            victim = c1.selectbox("Löschen (nur wer noch nie gespielt hat)", deletable, index=None,
                                  format_func=lambda p: p.name, key="del_player", placeholder="Name wählen")
            c2.button("Löschen", key="del_player_go", width="stretch", disabled=victim is None,
                      on_click=delete_player, args=(victim.id if victim else None,))


def admin_photos(snap: Snap) -> None:
    with st.expander("🖼️ Fotos für alle auf einmal"):
        st.caption("Dateiname = Spielername, z.B. «Lea.jpg» oder «kaegi.png» (Gross/klein und Umlaute egal).")
        n = st.session_state.get("bulk_n", 0)
        files = st.file_uploader("Fotos", type=PHOTO_TYPES, accept_multiple_files=True, key=f"bulk_{n}",
                                 label_visibility="collapsed", max_upload_size=25)
        if files and st.button(f"{len(files)} Fotos zuordnen", type="primary", key="bulk_go"):
            keys = {p.id: name_keys(p.name) for p in snap.real}
            done, missing = [], []
            for f in files:
                stem_keys = name_keys(Path(f.name).stem)
                hits = [pid for pid, k in keys.items() if k & stem_keys]
                if len(hits) != 1:
                    missing.append(f.name)
                    continue
                try:
                    big, small = prepare_photo(f.getvalue())
                except ValueError:
                    missing.append(f.name)
                    continue
                store.set_photo(hits[0], big, small)
                done.append(snap.players[hits[0]].name)
            if done:
                flash("success", f"{len(done)} Fotos gespeichert: {', '.join(done)}")
            if missing:
                flash("warning", "Nicht zugeordnet (bitte einzeln unter «Spieler» hochladen): " + ", ".join(missing))
            st.session_state.bulk_n = n + 1
            st.rerun()


def admin_results(snap: Snap) -> None:
    with st.expander("✏️ Resultate korrigieren (alle Runden)"):
        if not snap.rounds:
            st.caption("Noch keine Runden.")
            return
        rnd = st.selectbox("Runde", snap.rounds[::-1], format_func=lambda r: f"Runde {r.number}", key="adm_round")
        tables = snap.round_tables(rnd)
        t = st.selectbox("Tisch", sorted(tables), key=f"adm_table_{rnd.id}",
                         format_func=lambda n: f"Tisch {n} – " + ", ".join(p.name for p in tables[n]))
        correction_editor(rnd, t, tables[t], snap.round_games(rnd).get(t, {}), "adm")


def admin_backup(snap: Snap) -> None:
    with st.expander("💾 Backup, Name & Zurücksetzen"):
        st.caption("Tipp: Nach jeder Runde ein Backup herunterladen – darin ist alles (Spieler, Fotos, Runden, Resultate).")
        st.download_button(
            "💾 Backup herunterladen", data=store.backup_bytes, on_click="ignore", width="stretch",
            file_name=f"jassturnier-{datetime.now():%Y-%m-%d-%H%M}.db", mime="application/octet-stream",
        )
        n = st.session_state.get("restore_n", 0)
        upload = st.file_uploader("Backup wiederherstellen", type=["db"], key=f"restore_{n}")
        if upload is not None and st.button("⚠️ Backup einspielen (ersetzt alle aktuellen Daten)", key="restore_go"):
            try:
                store.restore(upload.getvalue())
            except ValueError as exc:
                st.error(str(exc))
            else:
                _photo_uri.clear()
                st.session_state.restore_n = n + 1
                flash("success", "Backup eingespielt.")
                st.rerun()

        st.divider()
        title = st.text_input("Turniername (oben auf der Seite)", value=snap.title, max_chars=40, key="title_in")
        if clean_name(title) != snap.title and st.button("Namen speichern", key="title_go"):
            store.set_setting("title", clean_name(title) or "Jassturnier")
            flash("toast", "🏷️ Name gespeichert")
            st.rerun()

        st.divider()
        with st.popover("⚠️ Turnier zurücksetzen", width="stretch"):
            st.write("Löscht **alle Runden und Resultate**. Teilnehmer und Fotos bleiben.")
            word = st.text_input("Zum Bestätigen RESET eintippen", key="reset_word")
            st.button("Alles zurücksetzen", key="reset_go", type="primary",
                      disabled=word.strip() != "RESET", on_click=reset_tournament)


PAGES = {
    RANGLISTE: page_rangliste,
    TISCHE: page_tische,
    EINTRAGEN: page_eintragen,
    SPIELER: page_spieler,
    ADMIN: page_admin,
}


def main() -> None:
    st.session_state.seen_version = store.version()
    snap = load()
    ui.inject_css()
    st.html(ui.header_html(snap.title, SUBTITLE))
    me = identity_row(snap)
    my_banner(snap, me)
    tabs = st.tabs(VIEWS, key="view", on_change="rerun")
    for name, tab in zip(VIEWS, tabs):
        if tab.open is False:
            continue
        with tab:
            show_flash()
            PAGES[name](snap, me)


main()
