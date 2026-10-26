#!/usr/bin/env python3
"""
Zvanični spisak naselja po opštinama i broj stanovnika, iz Popisa 2022 (RZS):
  - G20234005 „Домаћинства према броју чланова – подаци по насељима“ (spisak naselja, gradska „г“)
  - G20234003 „Старост и пол – подаци по насељима“ (ukupno stanovnika i punoletnih)

Obe knjige imaju iste redove istim redom (region, oblast, opština, „Градска/Остала“, naselja),
pa se broj stanovnika uparuje po redu, uz proveru da se imena poklapaju.

Izlaz: naselja_rzs.csv  (opstina, naselje, gradsko, stanovnika, punoletnih)
Popis nije sproveden na Kosovu i Metohiji, pa tih opština nema.

    python naselja_rzs.py [folder_sa_pdf]
"""
import csv
import re
import sys
import urllib.request
from pathlib import Path

import pypdfium2 as pdfium

BASE = "https://publikacije.stat.gov.rs/G2023/Pdf/"
HERE = Path(__file__).resolve().parent
NUM = r"(?:\d{1,3}(?: \d{3})*|\d+|-)"
# kod malih naselja PDF ponekad spoji dve cifre ("5 5" -> "55"), pa red ima broj manje: 5-7 brojeva
HH = re.compile(rf"^(?P<ime>[^\d]+?)(?P<g> г)? (?P<ukupno>{NUM})(?: {NUM}){{5,7}} (?:\d+,\d+|-) (?P<lat>.+)$")
POP_C = re.compile(r"^(?P<ime>[^\d]+?)(?: г)? С (?P<uk>\d+)\b")        # parna strana: ukupno (С = svega)
POP_T = re.compile(r"(?P<pun>\d+) \d+,\d+ T (?P<lat>.+)$")             # neparna: punoletni, prosečna starost
NOT_OP = re.compile(r"^(Република|Србија|Регион|Град Београд$|Град Ниш$)|област$")
SUM = {"Urban", "Other"}  # zbirni redovi „Градска/Остала“ (u Crnoj Travi postoji i selo Градска / Gradska)


def pages(folder, code):
    f = folder / f"{code}.pdf"
    if not f.exists():
        req = urllib.request.Request(BASE + f"{code}.pdf", headers={"User-Agent": "Mozilla/5.0"})
        f.write_bytes(urllib.request.urlopen(req, timeout=300).read())
    doc = pdfium.PdfDocument(str(f))
    return [[ln.strip() for ln in doc[i].get_textpage().get_text_range().splitlines()] for i in range(len(doc))]


def table2(pgs):
    return [pg for pg in pgs if any(ln.startswith("Табела 2.") for ln in pg)]


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
    # 1) svi redovi Tabele 2 iz knjige o domaćinstvima: (ime, gradsko, zbirni)
    hh = []
    for pg in table2(pages(folder, "G20234005")):
        for ln in pg:
            m = HH.match(ln)
            if m:
                hh.append((m.group("ime").strip(), 1 if m.group("g") else 0, m.group("lat").strip() in SUM))
    # 2) isti redovi iz knjige o stanovništvu: ukupno (parna strana) i punoletni (sledeća strana)
    P = pages(folder, "G20234003")
    pop = []
    for i, pg in enumerate(P[:-1]):
        if not any(ln.startswith("Табела 2.") for ln in pg):
            continue
        c = [m for m in (POP_C.match(ln) for ln in pg) if m]
        t = [m for m in (POP_T.search(ln) for ln in P[i + 1]) if m]
        if not c:
            continue
        pun = [int(m.group("pun")) for m in t] if len(t) == len(c) else [None] * len(c)
        pop += [(m.group("ime").strip(), int(m.group("uk")), p) for m, p in zip(c, pun)]
    # poravnanje dva niza imena (knjiga o stanovništvu ima i redove koji u drugoj nedostaju)
    import difflib
    sm = difflib.SequenceMatcher(None, [h[0] for h in hh], [p[0] for p in pop], autojunk=False)
    match = {}
    for a, b, size in sm.get_matching_blocks():
        for j in range(size):
            match[a + j] = b + j
    # 3) opština = red iza kojeg sledi zbirni red; naselja su ostali redovi
    out, op, area = [], None, ""
    for k, (ime, g, is_sum) in enumerate(hh):
        if is_sum:
            continue
        if k + 1 < len(hh) and hh[k + 1][2]:
            if ime.endswith("област"):
                area = ime
            op = None if NOT_OP.search(ime) else ime
            if op == "Палилула":  # dve gradske opštine istog imena
                op = "Палилула (Ниш)" if "Нишав" in area else "Палилула (Београд)"
            continue
        if op:
            uk, pun = (pop[match[k]][1], pop[match[k]][2]) if k in match else ("", None)
            out.append((op, ime, g, uk, "" if pun is None else pun))
    with open(HERE / "naselja_rzs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["opstina", "naselje", "gradsko", "stanovnika", "punoletnih"])
        w.writerows(out)
    print(f"Naselja: {len(out)}, opština: {len({o[0] for o in out})}, "
          f"bez broja stanovnika: {sum(1 for o in out if o[3] == '')}, bez punoletnih: {sum(1 for o in out if o[4] == '')}")


if __name__ == "__main__":
    main()
