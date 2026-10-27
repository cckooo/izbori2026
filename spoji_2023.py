#!/usr/bin/env python3
"""
Spaja rezultate izbora 2023. (rezultati_2023.csv, iz prethodni_2023.py) sa biračkim mestima 2026.
i upisuje `const PRETHODNI={"opština":{"broj BM":[upisani, glasali, važeći, Vučićeva lista]}};` u izbori2026.html.

Mesto 2026. se spaja sa mestom iste opštine i istog broja iz 2023. ako je naziv mesta isti ili sličan, ili,
kad se naziv promenio (preseljeno biračko mesto), ako se broj upisanih birača razlikuje najviše 15 %.
U oba slučaja broj upisanih sme da se promeni najviše 40 %: veći skok znači promenjene granice biračkog mesta ili
drugo mesto pod istim brojem (opšti nazivi kao „Основна школа“ se poklapaju i kad nije isto mesto).
Na obe liste Vučićeva lista je pod brojem 1 („Србија не сме да стане“ 2023, „Уједињена Србија“ 2026).

    python spoji_2023.py [--dry-run]
"""
import csv
import difflib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / "izbori2026.html"
SRC = HERE / "rezultati_2023.csv"
norm = lambda s: re.sub(r"[^0-9А-Яа-яЂђЈјЉљЊњЋћЏџA-Za-z]", "", s.upper())

html = HTML.read_bytes().decode("utf-8")
data = json.loads(re.search(r"^const DATA=(.*);(?=\r?$)", html, re.M).group(1))
old = {(r["opstina"].strip(), r["bm_broj"].strip()): r for r in csv.DictReader(open(SRC, encoding="utf-8-sig"))}

out, stat, diff = {}, {"isti naziv": 0, "sličan naziv": 0, "preseljeno, isti broj birača": 0}, []
miss = {"nema u 2023": 0, "drugo mesto": 0, "broj upisanih ±40 %": 0}
for r in data["rows"]:
    op, n, name, up = data["opstine"][r[1]][0], str(r[2]), r[3], r[4]
    a = old.get((op.strip(), n))
    if not a:
        miss["nema u 2023"] += 1
        continue
    s = difflib.SequenceMatcher(None, norm(a["bm_naziv"]), norm(name)).ratio()
    up0 = int(a["upisani_biraci"])
    if not up0 or abs(up - up0) / up0 > .4:
        miss["broj upisanih ±40 %"] += 1
        continue
    if s >= .99:
        stat["isti naziv"] += 1
    elif s >= .6:
        stat["sličan naziv"] += 1
    elif abs(up - up0) / up0 <= .15:
        stat["preseljeno, isti broj birača"] += 1
    else:
        miss["drugo mesto"] += 1
        diff.append((op, n, a["bm_naziv"], name, up0, up))
        continue
    out.setdefault(op, {})[n] = [up0, int(a["glasali_biraci"]), int(a["vazeci_glasovi"]), int(a["lista_1"])]

print("Spojeno:", sum(stat.values()), stat, "| nije spojeno:", miss)
for d in diff[:10]:
    print("  drugo mesto:", d)
if "--dry-run" in sys.argv:
    sys.exit(0)
line = "const PRETHODNI=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";"
html, k = re.subn(r"^const PRETHODNI=.*;(?=\r?$)", lambda _: line, html, count=1, flags=re.M)
if k != 1:  # prvi put: nova linija odmah posle STANOVNICI
    html, k = re.subn(r"^(const STANOVNICI=.*;)(\r?\n)", lambda m: m.group(1) + m.group(2) + line + m.group(2), html, count=1, flags=re.M)
    if k != 1:
        raise SystemExit("Nema linije `const STANOVNICI=...;` u HTML-u")
HTML.write_bytes(html.encode("utf-8"))
print("PRETHODNI upisani u", HTML.name, f"({len(line) / 1e3:.0f} kB)")
