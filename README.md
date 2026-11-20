# 🃏 Jassturnier

Streamlit-App für unser Jassturnier: Tische auslosen, Resultate am Handy eintragen,
Rangliste live – im Look von Jassteppich, Kreidetafel und Deutschschweizer Karten.

## Spielmodus

- **Schieber zu viert**, Sitz 1+3 gegen Sitz 2+4 (Partner sitzen sich gegenüber).
- Pro Runde macht **jede Person einmal Trumpf** → 4 Spiele pro Tisch.
- **Kein Weis, keine Stöck, alle Farben zählen einfach, Match ohne Bonus** →
  jedes Spiel hat genau **157 Punkte**. Die App lässt nichts anderes zu
  (auch 1 : 156 nicht – 1 Punkt gibt es im Jass nicht).
- Jede Person bekommt die Punkte ihres Teams. Rangliste nach Total, bei Punktgleichheit gleicher Rang.
- Geht die Anzahl nicht auf, füllt die App mit **«?»-Plätzen** auf (höchstens einer pro Tisch).
  «?» kommt nicht in die Rangliste. Mit 19 Personen gibt es 5 Tische und einen «?».
- Sind alle Tische fertig, kann **jede Person «Runde X auslosen»** drücken. Die Auslosung
  vermeidet möglichst gleiche Partner und Tischnachbarn wie in früheren Runden.

## Was die App kann

| Ansicht | |
|---|---|
| 🏆 Rangliste | Podest, Kreidetafel mit Punkten, Schnitt, Matches und Trend seit der letzten Runde – aktualisiert sich alle 5 Sekunden von selbst |
| 🃏 Tische | Sitzplan pro Tisch, wer als Nächstes Trumpf macht, Spielblatt mit allen Resultaten |
| ✍️ Eintragen | Punkte eines Teams eingeben, das andere Team bekommt automatisch den Rest auf 157. Korrigieren und Löschen möglich |
| 📸 Spieler | Alle Spielerkarten; jede Person kann ihr Foto selbst ändern (auf dem Handy direkt ein Selfie) |
| ⚙️ Admin | Teilnehmer, Runden auslosen / neu auslosen / löschen, alle Resultate korrigieren, Fotos sammelweise hochladen, Backup |

**«Wer bist du?»** oben rechts: Wer seinen Namen wählt, sieht seinen Platz (Tisch, Partner, Gegner,
in welchem Spiel man Trumpf macht), und beim Eintragen ist der eigene Tisch schon ausgewählt.
Der Link (`…?ich=Name`) lässt sich als Lesezeichen speichern.

**Admin-PIN:** Standard ist `157` – für das Turnier unbedingt eine eigene setzen (siehe unten).

## Lokal starten

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Damit die Handys im **gleichen WLAN** mitmachen können:

```bash
streamlit run app.py --server.address 0.0.0.0
```

und auf den Handys `http://<IP-des-Laptops>:8501` öffnen. Eigene PIN lokal: Datei
`.streamlit/secrets.toml` mit `admin_pin = "..."` anlegen (Vorlage: `.streamlit/secrets.toml.example`).

## Online stellen (Streamlit Community Cloud, gratis)

1. Auf <https://share.streamlit.io> mit GitHub anmelden → **Create app** → Repository
   `janaruto/jassturnier`, Branch `main`, Datei `app.py`.
2. Unter **Advanced settings → Secrets** eintragen: `admin_pin = "deine-pin"`.
3. **Deploy** – danach in den App-Einstellungen unter **Sharing** auf «public» stellen,
   damit alle ohne Login reinschauen können (das Repo selbst bleibt privat).
4. Link an alle schicken oder als QR-Code auf die Tische legen.

> ⚠️ **Daten sichern:** Streamlit Cloud hat keinen dauerhaften Speicher. Startet die App neu
> (z.B. nach längerem Schlafen oder einem Update), sind Resultate und Fotos weg. Darum:
> - Nach dem Erfassen der Fotos und **nach jeder Runde** im Admin-Bereich «Backup herunterladen».
> - Ist die App plötzlich leer: «Backup wiederherstellen» – alles ist wieder da.
> - Während des Turniers keinen neuen Code pushen.
>
> Lokal auf dem Laptop bleiben die Daten in `data/jassturnier.db` erhalten.

## Teilnehmer

`teilnehmer.txt` wird nur beim allerersten Start eingelesen. Danach im Admin-Bereich
Personen hinzufügen, umbenennen oder auf «nicht aktiv» setzen (die Punkte bleiben).
Fotos kann man im Admin-Bereich auch alle auf einmal hochladen – Dateiname = Name,
z.B. `Lea.jpg` oder `kaegi.png`.

## Entwicklung

```bash
python -m unittest        # Regeln, Datenbank und App-Abläufe
```

| Datei | Inhalt |
|---|---|
| `app.py` | Oberfläche (Streamlit) |
| `jass_logic.py` | Regeln: Punkte-Check, Auslosung, Rangliste |
| `jass_db.py` | SQLite-Ablage – eine Datei, inkl. Fotos |
| `jass_theme.py` | Jass-Look: Farben-Symbole, Jassteppich, Kreidetafel |
| `tests/` | Tests (`unittest`, ohne Zusatzpakete) |

Datenordner ändern: `JASS_DATA_DIR=/pfad streamlit run app.py`
