#!/usr/bin/env python3
"""
Ponovljeno glasanje (1. 11. 2026): rezultati prvog glasanja (25. 10.) na 53 biračka mesta na kojima je glasanje
poništeno i ponovljeno. Izvor: ponovljeno_prvo.csv, ručno prepisan iz starih zapisnika biračkih odbora (skenirani PDF-ovi
koje je RIK objavio pre ponavljanja; putanja u koloni stari_zapisnik, relativno na election_results/). Za Majdanpek
(5 mesta) stari PDF je rešenje OIK da se rezultati ne mogu utvrditi, pa brojeva nema; Kruševac 111 nema upisane glasove.

Upisuje u izbori2026.html liniju (posle `const ODLUKE=`):
  const PONOVLJENO=[[opštinaIdx, brojBM, prvo|null, stariZapisnik, prekid, napomena], ...];
  prvo = [upisani|null, glasali, listićiUKutiji, nevažeći|null, važeći|null, [glasovi lista 1..18]]
  ... , g2023]  g2023 = [upisani, glasali, listićiUKutiji, [glasovi po listi 2026 (naslednik) ili null]] | null
Prazno polje u zapisniku ostaje null (ne izmišlja se). 2023: rezultati_2023.csv, samo za mesta koja je spoji_2023.py
spojio (PRETHODNI.m: isti ili sličan naziv, broj upisanih ±40 %); liste-naslednici kao u spoji_2023.py. Pokreće se ručno.

    python ponovljeno.py [--dry-run]
"""
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / "izbori2026.html"
SRC = HERE / "ponovljeno_prvo.csv"

html = HTML.read_bytes().decode("utf-8")
data = json.loads(re.search(r"^const DATA=(.*);(?=\r?$)", html, re.M).group(1))
ops = {o[0]: i for i, o in enumerate(data["opstine"])}
rows = {(r[1], r[2]): r for r in data["rows"]}
num = lambda s: int(s) if s.strip() else None
# 2023: samo spojena mesta (PRETHODNI.m iz spoji_2023.py); liste 2026 (indeks od 0) <- liste 2023
NASLEDNICI = {0: [1], 1: [2], 4: [6], 5: [8], 9: [9], 16: [13, 18], 6: [16]}
prev = json.loads(re.search(r"^const PRETHODNI=(.*);(?=\r?$)", html, re.M).group(1))
old = {(r["opstina"].strip(), r["bm_broj"].strip()): r for r in csv.DictReader(open(HERE / "rezultati_2023.csv", encoding="utf-8-sig"))}
def g2023(op_name, bm):
    if str(bm) not in prev["m"].get(op_name, {}):
        return None
    a = old[(op_name, str(bm))]
    v = [None] * 18
    for k, src in NASLEDNICI.items():
        v[k] = sum(int(a[f"lista_{j}"] or 0) for j in src)
    return [int(a["upisani_biraci"]), int(a["glasali_biraci"]), int(a["vazeci_glasovi"]) + int(a["nevazeci_listici"]), v]

out, warn = [], []
for r in csv.DictReader(open(SRC, encoding="utf-8"), delimiter=";"):
    if None in r:
        raise SystemExit(f"Red {r['red']}: višak polja (znak ; u tekstu?)")
    op = ops.get(r["opstina"])
    if op is None:
        raise SystemExit(f"Nepoznata opština: {r['opstina']}")
    bm = int(r["bm"])
    if (op, bm) not in rows:
        raise SystemExit(f"Nema BM {bm} u opštini {r['opstina']}")
    prvo = None
    if r["glasovi_1_18"].strip():
        v = [int(x) for x in r["glasovi_1_18"].split(",")]
        if len(v) != 18:
            raise SystemExit(f"Red {r['red']}: {len(v)} listi umesto 18")
        prvo = [num(r["upisani"]), num(r["glasali"]), num(r["listici"]), num(r["nevazeci"]), num(r["vazeci"]), v]
        va, nv = prvo[4], prvo[3]
        if va is not None and sum(v) != va:
            warn.append(f"{r['opstina']} {bm}: zbir listi {sum(v)} ≠ važeći {va}")
        if va is not None and nv is not None and va + nv != prvo[2]:
            warn.append(f"{r['opstina']} {bm}: važeći + nevažeći {va + nv} ≠ listići {prvo[2]}")
    out.append([op, bm, prvo, r["stari_zapisnik"], r["prekid"], r["napomena"], g2023(r["opstina"], bm)])

print(f"Mesta: {len(out)}, sa brojevima prvog glasanja: {sum(1 for x in out if x[2])}, spojeno sa 2023: {sum(1 for x in out if x[6])}")
for w in warn:
    print("  nesklad u zapisniku (prepisano kako piše):", w)
if "--dry-run" in sys.argv:
    sys.exit(0)
line = "const PONOVLJENO=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"
html, k = re.subn(r"^const PONOVLJENO=.*;(?=\r?$)", lambda _: line, html, count=1, flags=re.M)
if k != 1:  # prvi put: odmah posle ODLUKE
    html, k = re.subn(r"^(const ODLUKE=.*;)(\r?\n)", lambda m: m.group(1) + m.group(2) + line + m.group(2), html, count=1, flags=re.M)
    if k != 1:
        raise SystemExit("Nema linije `const ODLUKE=...;` u HTML-u")
HTML.write_bytes(html.encode("utf-8"))
print("PONOVLJENO upisano u", HTML.name, f"({len(line) / 1e3:.1f} kB)")
