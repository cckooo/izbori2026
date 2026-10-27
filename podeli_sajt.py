#!/usr/bin/env python3
"""
Priprema sajt za objavu: izbori2026.html -> <folder>/index.html + <folder>/ulice.json.

Spiskovi ulica čine oko 60 % HTML-a, a trebaju samo za pretragu i za „ulice“ u tabeli po biračkim
mestima, pa se izdvajaju u ulice.json koji sajt preuzima tek kad zatreba. U NASELJA ostaju nazivi
naselja, a umesto ulica stoji 1. Upisuje i vreme objave (BUILD, prikazuje se u podnožju). Izvorni izbori2026.html se ne menja i i dalje radi sam (lokalno).

    python podeli_sajt.py [_site] [izbori2026.html]
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "_site")
SRC = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).with_name("izbori2026.html"))

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
line = "const NASELJA=" + json.dumps(naselja, ensure_ascii=False, separators=(",", ":")) + ";"
html = html[:m.start()] + line + html[m.end():]
try:
    now = datetime.now(ZoneInfo("Europe/Belgrade"))
except ZoneInfoNotFoundError:  # Windows bez paketa tzdata
    now = datetime.now()
html, n = re.subn(r'^const BUILD="[^"]*";', f'const BUILD="{now:%Y-%m-%d %H:%M}";', html, count=1, flags=re.M)
if n != 1:
    raise SystemExit("Nema linije `const BUILD=...;` u HTML-u")

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "index.html").write_text(html, encoding="utf-8", newline="")
(OUT / "ulice.json").write_text(json.dumps(ulice, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"index.html {len(html.encode()) / 1e6:.2f} MB, ulice.json {(OUT / 'ulice.json').stat().st_size / 1e6:.2f} MB")
