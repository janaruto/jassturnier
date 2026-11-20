"""Jass-Look: Jassteppich, Kreidetafel, Deutschschweizer Farben (SVG) und HTML-Bausteine."""

from __future__ import annotations

import base64
import re
from html import escape

import streamlit as st

from jass_logic import GAMES_PER_ROUND, TOTAL, is_match, next_game_no, validate_points

# ------------------------------------------------------------ Farben-Symbole
# st.html filtert Inline-SVG heraus. Darum sind die Symbole CSS-Hintergrundbilder:
# im HTML steht nur <i class="sv sv-rosen"></i>.

_INK = "#3a2a14"


def _svg(body: str, view: str = "0 0 100 100", extra: str = "") -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}"{extra}>{body}</svg>'


ICONS = {
    "eicheln": _svg(
        f'<path d="M50 99V84" stroke="{_INK}" stroke-width="7" stroke-linecap="round"/>'
        f'<path d="M50 4C70 4 80 26 79 52H21C20 26 30 4 50 4Z" fill="#e8ad35" stroke="{_INK}" stroke-width="4"/>'
        '<path d="M37 16C32 24 30 34 30 44" fill="none" stroke="#fbe3a0" stroke-width="5" stroke-linecap="round"/>'
        f'<path d="M15 52Q50 42 85 52L80 70Q50 96 20 70Z" fill="#7a5426" stroke="{_INK}" stroke-width="4" stroke-linejoin="round"/>'
        f'<path d="M22 56L34 74M34 54L50 80M48 52L62 76M62 53L76 72M74 55L80 64M26 72L40 53M38 80L56 53M54 81L70 57M68 74L80 58" stroke="{_INK}" stroke-width="2.4" opacity=".75"/>'
    ),
    "schellen": _svg(
        f'<circle cx="50" cy="11" r="7" fill="none" stroke="{_INK}" stroke-width="5"/>'
        f'<circle cx="50" cy="57" r="39" fill="#f0bf3a" stroke="{_INK}" stroke-width="4"/>'
        f'<path d="M12.4 50Q50 58 87.6 50L88.8 62Q50 70 11.2 62Z" fill="#c8322b" stroke="{_INK}" stroke-width="3" stroke-linejoin="round"/>'
        '<ellipse cx="34" cy="32" rx="9" ry="5" fill="#fde8a6" transform="rotate(-35 34 32)"/>'
        f'<circle cx="50" cy="80" r="5.5" fill="{_INK}"/>'
        f'<path d="M50 80V93" stroke="{_INK}" stroke-width="4.5" stroke-linecap="round"/>'
    ),
    "rosen": _svg(
        '<g fill="#4f8a3c" stroke="#23401b" stroke-width="2.5" stroke-linejoin="round">'
        + "".join(
            f'<path d="M50 2L57 14L50 22L43 14Z" transform="rotate({a} 50 50)"/>'
            for a in (36, 108, 180, 252, 324)
        )
        + '</g><g fill="#c8322b" stroke="#4a1410" stroke-width="3">'
        '<circle cx="50" cy="27" r="17"/><circle cx="71.9" cy="42.9" r="17"/>'
        '<circle cx="63.5" cy="68.6" r="17"/><circle cx="36.5" cy="68.6" r="17"/>'
        '<circle cx="28.1" cy="42.9" r="17"/></g>'
        '<circle cx="50" cy="50" r="19" fill="#f7efdd" stroke="#4a1410" stroke-width="3"/>'
        '<circle cx="50" cy="50" r="11" fill="#f0bf3a" stroke="#4a1410" stroke-width="2.5"/>'
        '<circle cx="50" cy="50" r="4" fill="#c8322b"/>'
    ),
    "schilten": _svg(
        f'<path d="M12 8H88V44C88 70 70 86 50 95C30 86 12 70 12 44Z" fill="#c8322b" stroke="{_INK}" stroke-width="4" stroke-linejoin="round"/>'
        f'<path d="M22 18H78V44C78 64 65 76 50 83C35 76 22 64 22 44Z" fill="#f0bf3a" stroke="{_INK}" stroke-width="3" stroke-linejoin="round"/>'
        '<path d="M23.5 40H76.5V50H23.5Z" fill="#2b2117"/>'
        '<path d="M30 25H44" stroke="#fde8a6" stroke-width="4" stroke-linecap="round"/>'
    ),
    "obenabe": _svg(
        f'<circle cx="50" cy="50" r="44" fill="#f7efdd" stroke="{_INK}" stroke-width="6"/>'
        '<path d="M50 17L77 52H60V82H40V52H23Z" fill="#2b2117"/>'
    ),
    "undenufe": _svg(
        f'<circle cx="50" cy="50" r="44" fill="#f7efdd" stroke="{_INK}" stroke-width="6"/>'
        '<path d="M50 17L77 52H60V82H40V52H23Z" fill="#2b2117" transform="rotate(180 50 50)"/>'
    ),
    # das «Z» der Schieber-Jasstafel, ganz blass im Hintergrund der Rangliste
    "z": _svg(
        '<path d="M10 12H90L10 88H90" fill="none" stroke="#fff" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round"/>',
        extra=' preserveAspectRatio="none"',
    ),
}

SUIT_ORDER = ("eicheln", "schellen", "rosen", "schilten")
TRUMP_ICON = {
    "Eicheln": "eicheln", "Schellen": "schellen", "Rosen": "rosen",
    "Schilten": "schilten", "Obenabe": "obenabe", "Undenufe": "undenufe",
}


def icon(name: str, cls: str = "") -> str:
    return f'<i class="sv sv-{name} {cls}"></i>'


ICON_CSS = ".sv{display:inline-block; background-position:center; background-size:contain; background-repeat:no-repeat;}\n" + "\n".join(
    f'.sv-{name}{{background-image:url("data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}");}}'
    for name, svg in ICONS.items()
)

# ------------------------------------------------------------ CSS

_NOISE = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E"
    "%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3' "
    "stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 .6 0'/%3E"
    "%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.55'/%3E%3C/svg%3E\")"
)

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Grenze+Gotisch:wght@600;800&family=Kalam:wght@400;700&family=Alegreya+SC:wght@500;700&display=swap');
:root{
  --felt:#174a30; --felt-d:#0e3320; --cream:#fbf5e6; --cream-2:#efe3c4; --edge:#d6c59b;
  --ink:#2b2117; --ink-2:#6d5a3d; --red:#b8332b; --red-l:#f08a7f; --gold:#e3b341; --gold-l:#f5d77f;
  --chalk:#f2f0e6; --chalk-d:#b4b3a8;
}
.stApp{
  background:
    radial-gradient(130% 60% at 50% -5%, rgba(255,255,255,.10), rgba(255,255,255,0) 60%),
    radial-gradient(160% 110% at 50% 115%, rgba(0,0,0,.45), rgba(0,0,0,0) 60%),
    __NOISE__, var(--felt) !important;
}
[data-testid="stHeader"]{background:transparent !important;}
[data-testid="stMainBlockContainer"]{padding-top:1.6rem; padding-bottom:4rem;}
@media (max-width:640px){[data-testid="stMainBlockContainer"]{padding-left:.8rem; padding-right:.8rem;}}

/* Kopf */
.jt-head{text-align:center; margin:0 0 .2rem;}
.jt-suits{display:flex; align-items:center; justify-content:center; gap:.55rem;}
.jt-suits::before,.jt-suits::after{content:""; height:2px; flex:0 1 72px; border-radius:2px;
  background:linear-gradient(90deg, rgba(245,215,127,0), var(--gold-l));}
.jt-suits::after{background:linear-gradient(270deg, rgba(245,215,127,0), var(--gold-l));}
.jt-suits .sv{width:26px; height:26px; filter:drop-shadow(0 1px 1px rgba(0,0,0,.5));}
.jt-title{font-family:'Grenze Gotisch',serif; font-weight:800; font-size:clamp(2.8rem,13vw,4.4rem);
  line-height:.95; color:var(--cream); margin:.2rem 0 .15rem; letter-spacing:.01em;
  text-shadow:0 3px 0 rgba(0,0,0,.35), 0 0 24px rgba(227,179,65,.28);}
.jt-sub{font-family:'Alegreya SC',serif; color:var(--gold-l); font-size:.95rem; letter-spacing:.02em;}
.jt-status{display:flex; align-items:center; gap:.5rem; color:var(--cream); font-size:.95rem; white-space:nowrap;}
.jt-status b{color:var(--gold-l);}
.jt-bar{flex:1; min-width:30px; height:7px; border-radius:4px; background:rgba(0,0,0,.35); overflow:hidden;}
.jt-bar i{display:block; height:100%; border-radius:4px; background:linear-gradient(90deg,var(--gold),var(--gold-l));}
.live{display:inline-flex; align-items:center; gap:.4rem; font-size:.72rem; font-weight:700;
  letter-spacing:.1em; text-transform:uppercase; color:#9fe3b4;}
.live i{width:8px; height:8px; border-radius:50%; background:#5fd38a; animation:jt-pulse 2s infinite;}
.live.stale{color:var(--gold-l);} .live.stale i{background:var(--gold); animation:none;}
@keyframes jt-pulse{0%{box-shadow:0 0 0 0 rgba(95,211,138,.65)}70%{box-shadow:0 0 0 9px rgba(95,211,138,0)}100%{box-shadow:0 0 0 0 rgba(95,211,138,0)}}

/* Streamlit-Elemente */
[data-testid="stTabs"] button[role="tab"] p{font-family:'Alegreya SC',serif; font-weight:700; font-size:1.02rem;}
[data-testid="stNumberInput"] input{font-family:'Kalam',cursive; font-size:1.45rem; font-weight:700;}
[data-testid="stExpander"] details{background:rgba(0,0,0,.18);}
[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primaryFormSubmit"]{color:var(--ink) !important; font-weight:700;}
[data-testid="stBaseButton-primary"] p,[data-testid="stBaseButton-primaryFormSubmit"] p{color:var(--ink) !important; font-weight:700;}

/* Mini-Jasskarte (Spielerbild) */
.pc{--w:42px; position:relative; display:inline-flex; align-items:center; justify-content:center; flex:none;
  box-sizing:border-box; width:var(--w); height:calc(var(--w) * 4 / 3); padding:calc(var(--w) * .06);
  border-radius:calc(var(--w) * .14); background:var(--cream); vertical-align:middle;
  box-shadow:0 2px 5px rgba(0,0,0,.45), inset 0 0 0 1px var(--edge);}
.pc img{display:block; width:100%; height:100%; object-fit:cover; border-radius:calc(var(--w) * .09);}
.pc.blank b{font-family:'Alegreya SC',serif; font-weight:700; color:var(--ink); font-size:calc(var(--w) * .36); line-height:1; margin-top:12%;}
.pc.blank .pip{position:absolute; top:7%; left:9%; width:30%; aspect-ratio:1;}
.pc.back{background:repeating-linear-gradient(45deg,#b8332b 0 5px,#952720 5px 10px);
  box-shadow:0 2px 5px rgba(0,0,0,.45), inset 0 0 0 calc(var(--w) * .07) var(--cream), inset 0 0 0 calc(var(--w) * .09) var(--edge);}
.pc.back b{display:inline-flex; align-items:center; justify-content:center; width:56%; aspect-ratio:1; border-radius:50%;
  background:var(--cream); color:var(--red); font-family:'Grenze Gotisch',serif; font-weight:800; font-size:calc(var(--w) * .42); line-height:1;}
.pc.m{--w:54px;} .pc.l{--w:66px;}
.face{display:flex; flex-direction:column; align-items:center; justify-content:center; gap:8%; width:100%; height:100%;}
.face .sv{display:block; width:44%; aspect-ratio:1;}
.face b{font-family:'Alegreya SC',serif; font-weight:700; font-size:1.6rem; color:var(--ink-2); line-height:1;}

/* Podest: drei Karten wie ein Fächer */
.podium{display:flex; justify-content:center; align-items:flex-end; padding:22px 0 8px; margin:0 0 6px;}
.pod{position:relative; width:30%; max-width:152px; box-sizing:border-box; padding:7px 7px 9px; border-radius:12px;
  background:var(--cream); color:var(--ink); text-align:center;
  box-shadow:0 10px 22px rgba(0,0,0,.5), inset 0 0 0 1px var(--edge), inset 0 0 0 5px var(--cream), inset 0 0 0 6px var(--edge);}
.pod.r1{z-index:3; width:36%; max-width:180px; transform:translateY(-14px);}
.pod.r2{z-index:2; transform:rotate(-7deg) translateX(14px);}
.pod.r3{z-index:1; transform:rotate(7deg) translateX(-14px);}
.pod .ph{aspect-ratio:3/4; border-radius:7px; overflow:hidden; background:var(--cream-2);}
.pod .ph img{display:block; width:100%; height:100%; object-fit:cover;}
.pod .idx{position:absolute; top:10px; left:11px; z-index:2; display:flex; flex-direction:column; align-items:center;
  padding:3px 3px 4px; border-radius:7px; background:rgba(251,245,230,.92);
  font-family:'Grenze Gotisch',serif; font-weight:800; font-size:1.35rem; line-height:1; color:var(--red);}
.pod .idx .sv{width:17px; height:17px; margin-top:1px;}
.pod .crown{position:absolute; top:-21px; left:50%; transform:translateX(-50%); font-size:1.5rem; line-height:1;
  filter:drop-shadow(0 2px 2px rgba(0,0,0,.45));}
.pod .nm{font-family:'Alegreya SC',serif; font-weight:700; font-size:1.02rem; line-height:1.05; margin-top:6px; overflow-wrap:anywhere;}
.pod .pts{font-family:'Kalam',cursive; font-weight:700; font-size:1.35rem; line-height:1.1; color:var(--red);}
.pod .pts small{font-size:.72rem; color:var(--ink-2);}

/* Kreidetafel (Rangliste und Spielblätter) */
.tafel-frame{padding:9px; border-radius:16px; margin:4px 0 18px;
  background:linear-gradient(135deg,#9a6633 0%,#6e4520 28%,#8f5e2e 52%,#5a3716 78%,#7d5027 100%);
  box-shadow:0 12px 26px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.25), inset 0 -2px 0 rgba(0,0,0,.35);}
.tafel{position:relative; overflow:hidden; border-radius:9px; padding:6px 10px; color:var(--chalk);
  background:radial-gradient(120% 80% at 25% 0%,#3b413d 0%,#282d2a 50%,#1f2321 100%);
  box-shadow:inset 0 0 30px rgba(0,0,0,.55), inset 0 0 0 1px rgba(0,0,0,.6);}
.tafel-z.sv{position:absolute; left:6%; top:8%; width:88%; height:84%; opacity:.07; pointer-events:none; background-size:100% 100%;}
.tafel-title{font-family:'Kalam',cursive; font-weight:700; font-size:1.4rem; text-align:center; margin:2px 0 2px;}
.trow{position:relative; display:grid; grid-template-columns:28px 42px minmax(0,1fr) auto 3.1em; align-items:center;
  gap:8px; padding:6px 4px; border-top:1px dashed rgba(242,240,230,.17);}
.trow .rk{font-family:'Kalam',cursive; font-weight:700; font-size:1.35rem; line-height:1; text-align:center;}
.trow.g1 .rk{color:var(--gold-l);} .trow.g2 .rk{color:#dfe3e6;} .trow.g3 .rk{color:#e8ac77;}
.trow .nm{min-width:0; font-family:'Kalam',cursive; font-size:1.2rem; line-height:1.05; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.trow .nm small{display:block; font-family:inherit; font-size:.8rem; color:var(--chalk-d); overflow:hidden; text-overflow:ellipsis;}
.trow .tr{font-size:.78rem; font-weight:700; text-align:right; min-width:1.8em;}
.tr.up{color:#86e0a2;} .tr.down{color:#f28b81;} .tr.eq{color:rgba(242,240,230,.35);}
.trow .pt{font-family:'Kalam',cursive; font-weight:700; font-size:1.5rem; line-height:1; text-align:right;}
.trow.me{background:rgba(227,179,65,.16); border-radius:8px; box-shadow:inset 3px 0 0 var(--gold);}

/* Tische */
.tisch{background:rgba(0,0,0,.2); border-radius:16px; padding:10px 10px 8px; margin-bottom:4px; box-shadow:inset 0 0 0 1px rgba(255,255,255,.06);}
.tisch.me{box-shadow:inset 0 0 0 2px var(--gold);}
.tisch-head{display:flex; justify-content:space-between; align-items:baseline; padding:0 4px 7px;}
.tisch-head .tno{font-family:'Grenze Gotisch',serif; font-weight:800; font-size:1.75rem; line-height:1; color:var(--cream);}
.tisch-head .st{font-size:.85rem; color:var(--gold-l);} .tisch-head .st.done{color:#9fe3b4;}
.matte{display:grid; grid-template-columns:1fr 1.1fr 1fr; align-items:center; justify-items:center; row-gap:2px; padding:12px 4px;
  border-radius:12px; background:radial-gradient(circle at 50% 45%,#2f7f52 0%,#21633f 60%,#1a5434 100%);
  box-shadow:inset 0 0 0 2px var(--felt-d), inset 0 0 0 4px rgba(245,215,127,.55), inset 0 0 0 6px var(--felt-d), inset 0 10px 30px rgba(0,0,0,.35);}
.seat{position:relative; display:flex; flex-direction:column; align-items:center; gap:4px; min-width:0; max-width:100%;}
.seat.s1{grid-area:3/2;} .seat.s2{grid-area:2/3;} .seat.s3{grid-area:1/2;} .seat.s4{grid-area:2/1;}
.tag{display:block; max-width:100%; box-sizing:border-box; padding:1px 8px; border-radius:999px; font-size:.82rem; font-weight:700;
  line-height:1.3; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; box-shadow:0 1px 2px rgba(0,0,0,.35);}
.tag.a{background:var(--red); color:#fff7ef;} .tag.b{background:var(--gold); color:var(--ink);}
.seat.me .tag{outline:2px solid var(--cream); outline-offset:1px;}
.tmark{position:absolute; top:-7px; right:-12px; z-index:2; padding:1px 5px; border-radius:6px; font-size:.6rem; font-weight:800;
  letter-spacing:.05em; text-transform:uppercase; background:var(--cream); color:var(--red); box-shadow:0 1px 3px rgba(0,0,0,.4);}
.matte .mid{grid-area:2/2; text-align:center; line-height:1;}
.mid .score{font-family:'Kalam',cursive; font-weight:700; font-size:1.5rem; color:var(--cream); white-space:nowrap;}
.mid .score .a{color:var(--red-l);} .mid .score .b{color:var(--gold-l);}
.mid .lbl{margin-top:3px; font-size:.66rem; letter-spacing:.08em; text-transform:uppercase; color:rgba(251,245,230,.7);}
.glog{margin-top:8px; padding:3px 9px; border-radius:9px; color:var(--chalk);
  background:linear-gradient(180deg,#2b302d,#222624); box-shadow:inset 0 0 0 1px rgba(0,0,0,.5);}
.grow{display:grid; grid-template-columns:1.2em minmax(0,1fr) 2.4em .5em 2.4em; align-items:center; gap:6px;
  padding:5px 0; border-top:1px dashed rgba(242,240,230,.14); font-size:.93rem;}
.grow:first-child{border-top:0;}
.grow .no{font-family:'Kalam',cursive; color:var(--chalk-d);}
.grow .who{min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.grow .who small{color:var(--chalk-d);}
.ti{width:16px; height:16px; margin-right:5px; vertical-align:-3px;}
.grow .pa,.grow .pb{font-family:'Kalam',cursive; font-weight:700; font-size:1.1rem; line-height:1;}
.grow .pa{color:var(--red-l); text-align:right;} .grow .pb{color:var(--gold-l);}
.grow .sep{color:var(--chalk-d); text-align:center;}
.grow.open{color:var(--chalk-d);} .grow.open .pa,.grow.open .pb{color:rgba(242,240,230,.3);}
.grow.next{margin:0 -6px; padding:5px 6px; border-radius:6px; background:rgba(227,179,65,.13); color:var(--chalk);}
.grow.sum{border-top:1px solid rgba(242,240,230,.35); font-weight:700;}
.badge{display:inline-block; margin-left:5px; padding:1px 6px; border-radius:999px; vertical-align:1px;
  font-size:.62rem; font-weight:800; letter-spacing:.06em; text-transform:uppercase; background:var(--gold); color:var(--ink);}

/* Spieler-Karten */
.pgrid{display:grid; grid-template-columns:repeat(auto-fill,minmax(98px,1fr)); gap:12px; margin:8px 0 18px;}
.pcard{position:relative; box-sizing:border-box; padding:5px 5px 7px; border-radius:10px; text-align:center;
  background:var(--cream); color:var(--ink);
  box-shadow:0 6px 14px rgba(0,0,0,.35), inset 0 0 0 1px var(--edge), inset 0 0 0 4px var(--cream), inset 0 0 0 5px var(--edge);}
.pcard.me{box-shadow:0 0 0 3px var(--gold), 0 6px 14px rgba(0,0,0,.35), inset 0 0 0 1px var(--edge);}
.pcard.off{opacity:.5; filter:grayscale(.7);}
.pcard .ph{aspect-ratio:3/4; border-radius:6px; overflow:hidden; background:var(--cream-2);}
.pcard .ph img{display:block; width:100%; height:100%; object-fit:cover;}
.pcard .nm{margin-top:5px; font-family:'Alegreya SC',serif; font-weight:700; font-size:.98rem; line-height:1.1; overflow-wrap:anywhere;}
.pcard .meta{font-size:.76rem; color:var(--ink-2);}
.pcard.big{max-width:150px; margin:0 auto;}

/* Hinweise */
.me-banner{display:flex; align-items:center; gap:11px; margin:4px 0 6px; padding:8px 12px; border-radius:12px;
  background:var(--cream); color:var(--ink); box-shadow:0 6px 16px rgba(0,0,0,.3), inset 0 0 0 1px var(--edge);}
.me-banner .txt{min-width:0; font-size:.95rem; line-height:1.3;}
.me-banner .big{font-family:'Grenze Gotisch',serif; font-weight:800; font-size:1.3rem; line-height:1.05;}
.me-banner .txt b{color:var(--red);}
.note{margin:4px 0 8px; padding:12px 14px; border-radius:12px; text-align:center; color:var(--cream);
  background:rgba(0,0,0,.22); box-shadow:inset 0 0 0 1px rgba(255,255,255,.07);}
.note .ttl{font-family:'Grenze Gotisch',serif; font-weight:800; font-size:1.5rem; line-height:1.1; margin-bottom:3px;}
.note .suits{display:flex; justify-content:center; gap:6px; margin-bottom:6px;} .note .suits .sv{width:22px; height:22px;}
.entry-head{margin:10px 0 2px; font-size:1.08rem; color:var(--cream);}
.entry-head .k{font-family:'Grenze Gotisch',serif; font-weight:800; font-size:1.55rem; margin-right:2px;}
.entry-head b{color:var(--gold-l);}
.check{display:flex; justify-content:center; align-items:center; gap:.4rem; padding:2px 0 4px; font-family:'Kalam',cursive; font-size:1.3rem;}
.check.ok{color:#9fe3b4;} .check.bad{color:#f6a39a;} .check.idle{color:rgba(251,245,230,.55); font-size:1.05rem;}
""".replace("__NOISE__", _NOISE)


def inject_css() -> None:
    st.html(f"<style>{CSS}\n{ICON_CSS}</style>")


# ------------------------------------------------------------ Bausteine


def esc(value) -> str:
    return escape(str(value), quote=True)


def initials(name: str) -> str:
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    if not words:
        return "?"
    first = words[0][0]
    second = next((c for w in words[1:2] for c in w if c.isalnum()), "")
    return (first + second).upper()


def suit_for(player) -> str:
    return SUIT_ORDER[player.id % len(SUIT_ORDER)]


def avatar(player, uri: str | None = None, size: str = "") -> str:
    """Mini-Jasskarte: Foto, Initialen mit Farbe oder Kartenrücken für «?»."""
    if player is None or player.is_joker:
        return f'<span class="pc back {size}"><b>?</b></span>'
    if uri:
        return f'<span class="pc {size}"><img src="{uri}" alt=""></span>'
    return (
        f'<span class="pc blank {size}">{icon(suit_for(player), "pip")}'
        f"<b>{esc(initials(player.name))}</b></span>"
    )


def face(player, uri: str | None) -> str:
    """Grosses Bild für Karten: Foto oder Farbe + Initialen."""
    if uri:
        return f'<img src="{uri}" alt="">'
    return f'<div class="face">{icon(suit_for(player))}<b>{esc(initials(player.name))}</b></div>'


def trump_icon(trump: str | None) -> str:
    name = TRUMP_ICON.get(trump or "")
    return f'<i class="ti sv sv-{name}" title="{esc(trump)}"></i>' if name else ""


def header_html(title: str, subtitle: str) -> str:
    suits = "".join(icon(s) for s in SUIT_ORDER)
    return (
        f'<div class="jt-head"><div class="jt-suits">{suits}</div>'
        f'<div class="jt-title">{esc(title)}</div><div class="jt-sub">{esc(subtitle)}</div></div>'
    )


def status_html(round_no: int | None, played: int, total: int) -> str:
    if not round_no:
        return '<div class="jt-status">Turnier startet bald …</div>'
    pct = 100 * played / total if total else 0
    return (
        f'<div class="jt-status"><span>Runde <b>{round_no}</b> · {played}/{total} Spiele</span>'
        f'<span class="jt-bar"><i style="width:{pct:.0f}%"></i></span></div>'
    )


def live_html(stale: bool = False) -> str:
    if stale:
        return '<div class="live stale"><i></i>Neue Resultate – nach dem Speichern sichtbar</div>'
    return '<div class="live"><i></i>Live</div>'


def note_html(title: str, text: str = "", suits: bool = False) -> str:
    deco = f'<div class="suits">{"".join(icon(s) for s in SUIT_ORDER)}</div>' if suits else ""
    body = f"<div>{esc(text)}</div>" if text else ""
    return f'<div class="note">{deco}<div class="ttl">{esc(title)}</div>{body}</div>'


def me_banner_html(me, uri, round_no, table_no, seat, partner, opponents) -> str:
    opp = " &amp; ".join(esc(p.name) for p in opponents)
    return (
        f'<div class="me-banner">{avatar(me, uri, "m")}<div class="txt">'
        f'<div class="big">Runde {round_no} · Tisch {table_no}</div>'
        f"Partner: <b>{esc(partner.name)}</b> · Gegen: {opp}<br>"
        f"Du machst Trumpf in Spiel {seat}.</div></div>"
    )


def podium_html(entries) -> str:
    """entries: [(Standing, Player, foto_uri)] für Platz 1-3."""
    order = [i for i in (1, 0, 2) if i < len(entries)]
    suits = ("schellen", "rosen", "eicheln")
    cards = []
    for i in order:
        s, p, uri = entries[i]
        crown = '<div class="crown">👑</div>' if i == 0 else ""
        cards.append(
            f'<div class="pod r{i + 1}">{crown}<div class="idx">{s.rank}{icon(suits[i])}</div>'
            f'<div class="ph">{face(p, uri)}</div><div class="nm">{esc(p.name)}</div>'
            f'<div class="pts">{s.points}<small> Pkt.</small></div></div>'
        )
    return f'<div class="podium">{"".join(cards)}</div>'


def _trend(t: int | None) -> str:
    if t is None:
        return '<span class="tr"></span>'
    if t > 0:
        return f'<span class="tr up">▲{t}</span>'
    if t < 0:
        return f'<span class="tr down">▼{-t}</span>'
    return '<span class="tr eq">–</span>'


def ranking_html(rows, me_id=None, title: str = "Rangliste") -> str:
    """rows: [(Standing, Player, thumb_uri)]"""
    lines = []
    for s, p, uri in rows:
        cls = "trow"
        if s.games and s.rank <= 3:
            cls += f" g{s.rank}"
        if p.id == me_id:
            cls += " me"
        meta = f"{s.games} Spiele · Ø {s.average:.1f}" if s.games else "noch nicht gespielt"
        if s.matches:
            meta += f" · {s.matches} Match" + ("es" if s.matches > 1 else "")
        lines.append(
            f'<div class="{cls}"><span class="rk">{s.rank}</span>{avatar(p, uri)}'
            f'<span class="nm">{esc(p.name)}<small>{meta}</small></span>{_trend(s.trend)}'
            f'<span class="pt">{s.points}</span></div>'
        )
    return (
        '<div class="tafel-frame"><div class="tafel"><i class="tafel-z sv sv-z"></i>'
        f'<div class="tafel-title">{esc(title)}</div>{"".join(lines)}</div></div>'
    )


def table_html(table_no: int, seats, uris: dict, games: dict, me_id=None) -> str:
    """seats: [Player] in Sitzreihenfolge 1-4; games: {game_no: Game}."""
    nxt = next_game_no(games)
    total_a = sum(g.points_a for g in games.values())
    total_b = sum(g.points_b for g in games.values())
    mine = any(p.id == me_id for p in seats)

    seat_html = []
    for i, p in enumerate(seats, start=1):
        team = "a" if i % 2 else "b"
        cls = f"seat s{i}" + (" me" if p.id == me_id else "")
        mark = '<span class="tmark">Trumpf</span>' if nxt == i else ""
        seat_html.append(
            f'<div class="{cls}">{mark}{avatar(p, uris.get(p.id), "m")}'
            f'<span class="tag {team}">{esc(p.name)}</span></div>'
        )
    mid = (
        f'<div class="mid"><div class="score"><span class="a">{total_a}</span> : '
        f'<span class="b">{total_b}</span></div><div class="lbl">{len(games)}/{GAMES_PER_ROUND} Spiele</div></div>'
    )

    rows = []
    for k in range(1, GAMES_PER_ROUND + 1):
        caller = seats[k - 1]
        g = games.get(k)
        if g:
            badge = '<span class="badge">Match</span>' if is_match(g.points_a, g.points_b) else ""
            rows.append(
                f'<div class="grow"><span class="no">{k}</span>'
                f'<span class="who">{trump_icon(g.trump)}{esc(caller.name)}{badge}</span>'
                f'<span class="pa">{g.points_a}</span><span class="sep">:</span><span class="pb">{g.points_b}</span></div>'
            )
        else:
            cls = "grow open" + (" next" if k == nxt else "")
            rows.append(
                f'<div class="{cls}"><span class="no">{k}</span>'
                f'<span class="who">{esc(caller.name)} <small>macht Trumpf</small></span>'
                '<span class="pa">–</span><span class="sep">:</span><span class="pb">–</span></div>'
            )
    state = '<span class="st done">✓ fertig</span>' if nxt is None else f'<span class="st">Spiel {nxt} von {GAMES_PER_ROUND}</span>'
    return (
        f'<div class="tisch{" me" if mine else ""}"><div class="tisch-head"><span class="tno">Tisch {table_no}</span>{state}</div>'
        f'<div class="matte">{"".join(seat_html)}{mid}</div><div class="glog">{"".join(rows)}</div></div>'
    )


def player_grid_html(rows, me_id=None) -> str:
    """rows: [(Player, thumb_uri, Standing | None)]"""
    cards = []
    for p, uri, s in rows:
        cls = "pcard" + (" me" if p.id == me_id else "") + ("" if p.active else " off")
        if s and s.games:
            meta = f"Rang {s.rank} · {s.points} Pkt."
        else:
            meta = "noch keine Punkte" if p.active else "pausiert"
        cards.append(
            f'<div class="{cls}"><div class="ph">{face(p, uri)}</div>'
            f'<div class="nm">{esc(p.name)}</div><div class="meta">{meta}</div></div>'
        )
    return f'<div class="pgrid">{"".join(cards)}</div>'


def photo_card_html(player, uri) -> str:
    return (
        f'<div class="pcard big"><div class="ph">{face(player, uri)}</div>'
        f'<div class="nm">{esc(player.name)}</div></div>'
    )


def entry_head_html(game_no: int, caller) -> str:
    return (
        f'<div class="entry-head"><span class="k">Spiel {game_no}</span> '
        f"von {GAMES_PER_ROUND} · Trumpf macht <b>{esc(caller.name)}</b></div>"
    )


def check_html(a, b) -> str:
    if a is None and b is None:
        return f'<div class="check idle">Zusammen müssen es genau {TOTAL} Punkte sein.</div>'
    a_txt = "?" if a is None else int(a)
    b_txt = "?" if b is None else int(b)
    total = (0 if a is None else int(a)) + (0 if b is None else int(b))
    if a is not None and b is not None and total == TOTAL:
        errors = validate_points(a, b)
        if errors:  # Summe stimmt, aber z.B. 1 Punkt ist unmöglich
            return f'<div class="check bad">{a_txt} : {b_txt} ✗ {esc(errors[0])}</div>'
        return f'<div class="check ok">{a_txt} + {b_txt} = {TOTAL} ✓</div>'
    return f'<div class="check bad">{a_txt} + {b_txt} = {total} ✗ (muss {TOTAL} sein)</div>'
