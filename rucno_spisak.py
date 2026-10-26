#!/usr/bin/env python3
"""
Spisak biračkih mesta bez naselja, sa stranom odluke na kojoj se verovatno nalaze (po susednim
spojenim mestima iz iste odluke), za ručnu dopunu u rucno_naselja.csv.

    python rucno_spisak.py rezultati.csv    ->  rucno_zadaci.json  [{opstina, bm, naziv, izvor, strane}]
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8-sig", newline="")))
    det = json.loads((HERE / "spajanje_detalji.json").read_text(encoding="utf-8"))
    rucno = set()
    if (HERE / "rucno_naselja.csv").exists():
        rucno = {(r["opstina"], int(r["bm_broj"])) for r in csv.DictReader(open(HERE / "rucno_naselja.csv", encoding="utf-8"))}
    have = {(d["opstina"], d["bm"]): d for d in det}
    by_op = defaultdict(dict)
    for d in det:
        by_op[d["opstina"]][d["bm"]] = d
    tasks = []
    for r in rows:
        op, k = r["opstina"], int(r["bm_broj"])
        if (op, k) in have or (op, k) in rucno or op in ("Иностранство", "Заводи за извршење кривичних санкција"):
            continue
        m = by_op.get(op, {})
        lo = max((j for j in m if j < k), default=None)
        hi = min((j for j in m if j > k), default=None)
        ref = [m[j] for j in (lo, hi) if j is not None]
        if not ref:
            tasks.append({"opstina": op, "bm": k, "naziv": r["bm_naziv"], "izvor": None, "strane": []})
            continue
        src = ref[0]["izvor"]
        pages = sorted({x["strana"] for x in ref if x["izvor"] == src})
        if len(pages) == 2 and pages[1] - pages[0] > 1:
            pages = list(range(pages[0], pages[1] + 1))
        tasks.append({"opstina": op, "bm": k, "naziv": r["bm_naziv"], "izvor": src, "strane": pages})
    (HERE / "rucno_zadaci.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    pages = {(t["izvor"], p) for t in tasks for p in t["strane"]}
    print(f"Mesta bez naselja: {len(tasks)}; strana za pregled: {len(pages)}; bez poznatog izvora: "
          f"{sum(1 for t in tasks if not t['izvor'])}")


if __name__ == "__main__":
    main()
