#!/usr/bin/env python3
"""
Renderuje strane odluka potrebne za ručnu dopunu jedne opštine (iz rucno_zadaci.json).

    python rucno_render.py "<opština>" <izlazni_folder> [dpi]
"""
import json
import sys
from pathlib import Path

import pypdfium2 as pdfium

HERE = Path(__file__).resolve().parent


def main():
    op, out = sys.argv[1], Path(sys.argv[2])
    dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 120
    out.mkdir(parents=True, exist_ok=True)
    tasks = [t for t in json.loads((HERE / "rucno_zadaci.json").read_text(encoding="utf-8")) if t["opstina"] == op]
    print("Mesta:", ", ".join(f"{t['bm']} ({t['naziv']})" for t in tasks))
    pages = sorted({(t["izvor"], p) for t in tasks if t["izvor"] for p in t["strane"]})
    for n, (src, p) in enumerate(pages, 1):
        jf = HERE / "rik_ocr" / (Path(src).parent.name + "__" + Path(src).stem + ".json")
        rot = json.loads(jf.read_text(encoding="utf-8"))["strane"][p - 1]["rot"]
        img = pdfium.PdfDocument(str(HERE / src))[p - 1].render(scale=dpi / 72).to_pil()
        if rot:
            img = img.rotate(-rot, expand=True)
        f = out / f"p{n:02d}.png"
        img.save(f)
        print(f"{f}  <- {Path(src).name} str. {p}")


if __name__ == "__main__":
    main()
