#!/usr/bin/env python3
"""
Priprema sajt za objavu: izbori2026.html -> <folder>/index.html + <folder>/ulice.json.

Spiskovi ulica čine oko 60 % HTML-a, a trebaju samo za pretragu i za „ulice“ u tabeli po biračkim
mestima, pa se izdvajaju u ulice.json koji sajt preuzima tek kad zatreba. U NASELJA ostaju nazivi
naselja, a umesto ulica stoji 1. Izvorni izbori2026.html se ne menja i i dalje radi sam (lokalno).

U BUILD (prikazuje se u podnožju) upisuje:
- sajt: vreme poslednjeg commit-a koji menja sajt, bez automatskih commit-a sa rezultatima (izbori-bot);
- podaci: sadašnje vreme, samo uz --podaci (osvezi.yml, posle povlačenja CSV-a sa RIK-a).

    python podeli_sajt.py [_site] [izbori2026.html] [--podaci]
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = Path(ARGS[0] if ARGS else "_site")
SRC = Path(ARGS[1] if len(ARGS) > 1 else Path(__file__).with_name("izbori2026.html"))
SITE_FILES = ["izbori2026.html", "podeli_sajt.py", "prerender.py", "stranice_opstina.py", "mapa_naselja.json", "goatcounter.js", "og.png", "ikona.png"]
BOT = "izbori-bot"
try:
    TZ = ZoneInfo("Europe/Belgrade")
except ZoneInfoNotFoundError:  # Windows bez paketa tzdata
    TZ = None


def fmt(dt):
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M")


def site_changed():
    """Vreme poslednjeg commit-a (ne bota) koji menja sajt; prazno ako git istorija nije dostupna."""
    try:
        log = subprocess.run(["git", "log", "-n", "300", "--format=%ct%x09%an", "--", *SITE_FILES],
                             cwd=Path(__file__).parent, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return ""
    for ln in log.splitlines():
        ts, author = ln.split("\t", 1)
        if author != BOT:
            return fmt(datetime.fromtimestamp(int(ts)).astimezone())
    return ""

html = SRC.read_text(encoding="utf-8")
m = re.search(r"^const NASELJA=(.*);(?=\r?$)", html, re.M)
if not m:
    raise SystemExit("Nema linije `const NASELJA=...;` u HTML-u")
naselja = json.loads(m.group(1))
ulice = {}
for op, mesta in naselja.items():
    for bm, v in mesta.items():
        if v[1]:
            ulice.setdefault(op, {})[bm] = v[1]
            v[1] = 1
line = "const NASELJA=" + json.dumps(naselja, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"  # `<` u podacima ne sme da zatvori <script>
html = html[:m.start()] + line + html[m.end():]
build = {"sajt": site_changed()}
if "--podaci" in sys.argv:
    build["podaci"] = fmt(datetime.now().astimezone())
line = "const BUILD=" + json.dumps(build, separators=(",", ":")) + ";"
html, n = re.subn(r"^const BUILD=[^;\n]*;", lambda _: line, html, count=1, flags=re.M)
if n != 1:
    raise SystemExit("Nema linije `const BUILD=...;` u HTML-u")
print(line)

OUT.mkdir(parents=True, exist_ok=True)
# brže otvaranje: putanje zapisnika (trećina stranice), podaci 2023. i mapa opština u posebne fajlove;
# sajt ih preuzima odmah posle prvog prikaza (LAZY u HTML-u). U HTML-u ostaje null, a putanja zapisnika 0.
m = re.search(r"^const DATA=(.*);(?=\r?$)", html, re.M)
data = json.loads(m.group(1))
(OUT / "zapisnici.json").write_text(json.dumps([r[9] for r in data["rows"]], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
for r in data["rows"]:
    if r[9]:
        r[9] = 0
line = "const DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"  # `<` u podacima ne sme da zatvori <script>
html = html[:m.start()] + line + html[m.end():]
for const, fname in (("PRETHODNI", "prethodni.json"), ("MAPA", "mapa.json")):
    m = re.search(rf"^const {const}=(.*);(?=\r?$)", html, re.M)
    if m:
        (OUT / fname).write_text(m.group(1), encoding="utf-8")
        html = html[:m.start()] + f"const {const}=null;" + html[m.end():]
# veliki podaci kao <script type="application/json"> + JSON.parse: pregledač ih čita brže nego JS literal
blocks = []
for const in ("DATA", "NASELJA", "STANOVNICI"):
    m = re.search(rf"^const {const}=(.*);(?=\r?$)", html, re.M)
    if m:
        blocks.append(f'<script type="application/json" id="j{const}">' + m.group(1).replace("<", "\\u003c") + "</script>")
        html = html[:m.start()] + f'const {const}=JSON.parse(document.getElementById("j{const}").textContent);' + html[m.end():]
i = html.index("<script>\nconst DATA=")
html = html[:i] + "\n".join(blocks) + "\n" + html[i:]
gc = SRC.with_name("goatcounter.js")  # skripta za brojanje poseta, služi se sa našeg sajta
if gc.exists():
    (OUT / gc.name).write_bytes(gc.read_bytes())
nas_map = SRC.with_name("mapa_naselja.json")  # granice naselja (mapa_naselja.py): po fajl za opštinu, preuzima se kad se otvori
if nas_map.exists():
    nd = OUT / "naselja"
    nd.mkdir(exist_ok=True)
    for op, m in json.loads(nas_map.read_text(encoding="utf-8")).items():
        (nd / f"{op}.json").write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
(OUT / "index.html").write_text(html, encoding="utf-8", newline="")
(OUT / "ulice.json").write_text(json.dumps(ulice, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"index.html {len(html.encode()) / 1e6:.2f} MB, ulice.json {(OUT / 'ulice.json').stat().st_size / 1e6:.2f} MB")
