#!/usr/bin/env python3
"""
Spaja rezultate izbora 2023. (rezultati_2023.csv, iz prethodni_2023.py) sa biračkim mestima 2026.
i upisuje u izbori2026.html `const PRETHODNI={m, o, liste, fp};`:
- m: {"opština":{"broj BM":[upisani, glasali, važeći, Vučić, Dačić]}} za spojena biračka mesta;
- o: {"opština":[upisani, glasali, važeći, glasovi listi-naslednika redom kao `liste`]} za sva mesta iz 2023;
- liste: indeksi listi 2026 (od 0) koje imaju naslednika iz 2023 (NASLEDNICI ispod);
- fp: otisak prsta 2023, {"first" | indeks liste: [[polje, broj mesta], ...]}, polje = y*50 + x;
- fpx: isto bez inostranstva, zatvora i Kosova i Metohije.

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
    out.setdefault(op, {})[n] = [up0, int(a["glasali_biraci"]), int(a["vazeci_glasovi"]), int(a["lista_1"]), int(a["lista_2"])]

print("Spojeno:", sum(stat.values()), stat, "| nije spojeno:", miss)
for d in diff[:10]:
    print("  drugo mesto:", d)

# Zbirovi po opštini (sva mesta iz 2023, bez spajanja po BM) za liste koje imaju naslednika 2026.
# Ključ: indeks liste 2026 (od 0); vrednost: brojevi listi 2023 koje se sabiraju.
NASLEDNICI = {0: [1], 1: [2], 4: [6], 5: [8], 9: [9], 16: [13, 18], 6: [16]}
SPOJENE_OPSTINE = {"Градска општина Врањска Бања": "Град Врање"}  # 2026. nema posebnih rezultata
ops26 = {o[0] for o in data["opstine"]}
opagg = {}
FP_N = 50
fp = {"first": {}, **{str(k): {} for k in NASLEDNICI}}
fpx = {k: {} for k in fp}  # isto, bez inostranstva, zatvora i KiM (prekidač na sajtu)
BEZ = ("Иностранство", "Заводи", "Косово")
for a in old.values():
    op = SPOJENE_OPSTINE.get(a["opstina"].strip(), a["opstina"].strip())
    if op not in ops26:
        raise SystemExit(f"Opština iz 2023. ne postoji 2026: {op}")
    up, gl, va = int(a["upisani_biraci"]), int(a["glasali_biraci"]), int(a["vazeci_glasovi"])
    votes = {i: int(a.get(f"lista_{i}") or 0) for i in range(1, 31) if f"lista_{i}" in a}
    lv = [sum(votes[i] for i in NASLEDNICI[k]) for k in NASLEDNICI]
    s = opagg.setdefault(op, [0] * (3 + len(lv)))
    for j, x in enumerate([up, gl, va, *lv]):
        s[j] += x
    if up > 0 and va > 0:  # otisak prsta 2023: isto polje 2 × 2 p.p. kao na sajtu
        x = min(FP_N - 1, int(min(1, gl / up) * FP_N))
        cell = lambda v: min(FP_N - 1, int(v / va * FP_N)) * FP_N + x
        grids = [fp] if any(b in a["region"] for b in BEZ) else [fp, fpx]
        for grid in grids:
            c = cell(max(votes.values()))
            grid["first"][c] = grid["first"].get(c, 0) + 1
            for k, v in zip(NASLEDNICI, lv):
                c = cell(v)
                grid[str(k)][c] = grid[str(k)].get(c, 0) + 1
fp = {k: [[c, n] for c, n in sorted(v.items())] for k, v in fp.items()}
fpx = {k: [[c, n] for c, n in sorted(v.items())] for k, v in fpx.items()}
print("Opština 2023:", len(opagg), "| liste sa naslednikom (indeks 2026 <- broj 2023):", NASLEDNICI)

if "--dry-run" in sys.argv:
    sys.exit(0)
prev = {"m": out, "o": opagg, "liste": list(NASLEDNICI), "fp": fp, "fpx": fpx}
line = "const PRETHODNI=" + json.dumps(prev, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"  # `<` u podacima ne sme da zatvori <script>
html, k = re.subn(r"^const PRETHODNI=.*;(?=\r?$)", lambda _: line, html, count=1, flags=re.M)
if k != 1:  # prvi put: nova linija odmah posle STANOVNICI
    html, k = re.subn(r"^(const STANOVNICI=.*;)(\r?\n)", lambda m: m.group(1) + m.group(2) + line + m.group(2), html, count=1, flags=re.M)
    if k != 1:
        raise SystemExit("Nema linije `const STANOVNICI=...;` u HTML-u")
HTML.write_bytes(html.encode("utf-8"))
print("PRETHODNI upisani u", HTML.name, f"({len(line) / 1e3:.0f} kB)")
