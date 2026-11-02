#!/usr/bin/env python3
"""
Ponovljeno glasanje (1. 11. 2026): rezultati prvog glasanja (25. 10.) na 53 biračka mesta na kojima je glasanje
poništeno i ponovljeno. Izvor: ponovljeno_prvo.csv, ručno prepisan iz starih zapisnika biračkih odbora (skenirani PDF-ovi
koje je RIK objavio pre ponavljanja; putanja u koloni stari_zapisnik, relativno na election_results/). Za Majdanpek
(5 mesta) stari PDF je rešenje OIK da se rezultati ne mogu utvrditi, pa brojeva nema; Kruševac 111 nema upisane glasove.

Upisuje u izbori2026.html liniju (posle `const ODLUKE=`):
  const PONOVLJENO=[[opštinaIdx, brojBM, prvo|null, stariZapisnik, prekid, napomena], ...];
  prvo = [upisani|null, glasali, listićiUKutiji, nevažeći|null, važeći|null, [glasovi lista 1..18]]
Prazno polje u zapisniku ostaje null (ne izmišlja se). Pokreće se ručno.

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
    out.append([op, bm, prvo, r["stari_zapisnik"], r["prekid"], r["napomena"]])

print(f"Mesta: {len(out)}, sa brojevima prvog glasanja: {sum(1 for x in out if x[2])}")
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
