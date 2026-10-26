#!/usr/bin/env python3
"""
Dodaje ručno prepisana mesta u rucno_naselja.csv; izvor (PDF) se uzima iz rucno_zadaci.json.

    python rucno_dodaj.py unos.txt
Format unosa (UTF-8), jedno mesto po redu:  opština | broj | adresa | područje | strana
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    tasks = {(t["opstina"], t["bm"]): t for t in json.loads((HERE / "rucno_zadaci.json").read_text(encoding="utf-8"))}
    rows = []
    for ln in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        op, bm, adr, area, page = [x.strip() for x in ln.split("|")]
        t = tasks.get((op, int(bm)))
        if not t or not t["izvor"]:
            print("NEMA ZADATKA:", op, bm)
            continue
        rows.append([op, int(bm), adr, area, Path(t["izvor"]).name, int(page)])
    with open(HERE / "rucno_naselja.csv", "a", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    print("Dodato:", len(rows))


if __name__ == "__main__":
    main()
