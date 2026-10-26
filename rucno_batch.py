#!/usr/bin/env python3
"""
Za ručnu dopunu: renderuje sve strane potrebne za zadatke iz rucno_zadaci.json (opciono samo
za navedene opštine) u jedan folder, i ispisuje koja slika pripada kojim mestima.

    python rucno_batch.py <izlazni_folder> [opština ...]
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import pypdfium2 as pdfium

HERE = Path(__file__).resolve().parent


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[2:])
    tasks = [t for t in json.loads((HERE / "rucno_zadaci.json").read_text(encoding="utf-8"))
             if t["izvor"] and (not only or t["opstina"] in only)]
    pages = defaultdict(list)
    for t in tasks:
        for p in t["strane"]:
            pages[(t["izvor"], p)].append(f"{t['opstina']} {t['bm']} ({t['naziv']})")
    rots = {}
    for n, ((src, p), who) in enumerate(sorted(pages.items()), 1):
        jf = HERE / "rik_ocr" / (Path(src).parent.name + "__" + Path(src).stem + ".json")
        if jf not in rots:
            rots[jf] = [s["rot"] for s in json.loads(jf.read_text(encoding="utf-8"))["strane"]]
        img = pdfium.PdfDocument(str(HERE / src))[p - 1].render(scale=105 / 72).to_pil()
        if rots[jf][p - 1]:
            img = img.rotate(-rots[jf][p - 1], expand=True)
        img.save(out / f"b{n:03d}.png")
        print(f"b{n:03d}  {Path(src).name[:50]} str.{p}  <- " + "; ".join(who))


if __name__ == "__main__":
    main()
