#!/usr/bin/env python3
"""
Za ručnu dopunu: ispisuje OCR redove sa strana potrebnih za jednu opštinu (iz rucno_zadaci.json),
da se vizuelno utvrdi koji red je koje biračko mesto.

    python rucno_redovi.py "<opština>"
"""
import json
import sys
from pathlib import Path

import parse_odluke as P

HERE = Path(__file__).resolve().parent


def main():
    op = sys.argv[1]
    tasks = [t for t in json.loads((HERE / "rucno_zadaci.json").read_text(encoding="utf-8")) if t["opstina"] == op]
    srcs = sorted({t["izvor"] for t in tasks if t["izvor"]})
    pages = {(t["izvor"], p) for t in tasks if t["izvor"] for p in t["strane"]}
    for src in srcs:
        jf = HERE / "rik_ocr" / (Path(src).parent.name + "__" + Path(src).stem + ".json")
        recs = P.extract_records(json.loads(jf.read_text(encoding="utf-8")), [op])
        print("##", Path(src).name)
        for r in recs:
            if (src, r["str"]) in pages:
                print(f"  str{r['str']:>3} br={str(r['br']):>4} | {r['naziv'][:28]:28s} | {r['adresa'][:26]:26s} | {r['naselja'][:70]}")


if __name__ == "__main__":
    main()
