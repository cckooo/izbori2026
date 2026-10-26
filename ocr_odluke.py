#!/usr/bin/env python3
"""
Izvlači tabele i tekst iz odluka o biračkim mestima (rik_fajlovi/**.pdf).

Za svaku stranu:
  1. render u 300 dpi i OpenCV: linije tabele -> ćelije,
  2a. PDF sa ispravnim tekstualnim slojem ("pdf"): reči sa koordinatama iz pdfplumber-a,
  2b. skenirani ili pokvaren tekstualni sloj ("ocr"): Tesseract OSD (rotacija, pismo), pa jedan
      Tesseract poziv po strani (image_to_data); redni brojevi BM se čitaju posebno, samo cifre,
  3. reči se raspoređuju u ćelije; ono što je van tabele ide u "tekst".

Izlaz: rik_ocr/<opstina>__<fajl>.json  ->
  {"izvor","nacin","strane":[{"rot","pismo","elementi":[[y,"t",linija] | [y,"r",[ćelije]]]}]}
Već obrađeni fajlovi se preskaču (obriši JSON da se ponovo obradi).

Pokretanje:  python ocr_odluke.py [broj_procesa] [--deo i n] [--ponovi]
  --deo i n  obradi samo i-ti od n delova (0..n-1), podeljenih po broju strana (GitHub Actions matrica)
  --ponovi   ponovo obradi samo sumnjive strane (tabela bez teksta) u već gotovim JSON fajlovima
"""
import json
import os
import re
import shutil
import sys
from multiprocessing import Pool
from pathlib import Path

os.environ.setdefault("OMP_THREAD_LIMIT", "1")

HERE = Path(__file__).resolve().parent
SRC = HERE / "rik_fajlovi"
OUT = HERE / "rik_ocr"
TESS = Path(shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe")
# tessdata_fast je ~4x brži od tessdata_best, uz nešto slabiju tačnost (OCR_MODEL=tessdata za best)
TD = "--tessdata-dir " + (HERE / os.environ.get("OCR_MODEL", "tessdata_fast")).as_posix()
DPI = 300


def has_text(path: Path) -> bool:
    """Da li PDF ima upotrebljiv tekstualni sloj (a ne prazan ili pokvaren, npr. 'Ha ocHoBy')."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    n = len(doc)
    txt = "".join(pg.get_textpage().get_text_range() for pg in doc)
    if len(re.sub(r"\s", "", txt)) < 150 * max(1, n):
        return False
    low = txt.lower()
    hits = len(re.findall(r"бирач|biračk|birack|места|mesta|општин|opštin|улиц|ulic|насељ|naselj|школ|škol", low))
    if hits < 3 * max(1, n) ** 0.5:
        return False
    # sloj koji je i sam loš OCR meša pisma u rečima ("Адамовиhа", "Jовина")
    words = re.findall(r"\w{3,}", txt)
    mixed = sum(1 for w in words if re.search(r"[а-яђјљњћџ]", w, re.I) and re.search(r"[a-z]", w, re.I))
    return mixed <= 0.01 * max(1, len(words))


# ------------------------------------------------------------ tabela sa slike
def find_cells(gray):
    """Vraća (listu ćelija (x,y,w,h), masku linija)."""
    import cv2
    import numpy as np
    H, W = gray.shape
    # svetlosive i tanke linije: adaptivni prag, pa malo podebljamo da nagib ne prekine liniju
    inv = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    inv = cv2.dilate(inv, np.ones((3, 3), np.uint8))
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, W // 40), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, H // 50)))
    hl = cv2.morphologyEx(inv, cv2.MORPH_OPEN, hk)
    vl = cv2.morphologyEx(inv, cv2.MORPH_OPEN, vk)
    # premošćavanje prekida u linijama
    hl = cv2.morphologyEx(hl, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (60, 1)))
    vl = cv2.morphologyEx(vl, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 60)))
    # red koji se nastavlja na sledećoj strani nema gornju/donju liniju: zatvaramo ga
    # (linija ide malo ispod vrha/iznad dna najkraće vertikale, da preseče sve)
    nv, _, vst, _ = cv2.connectedComponentsWithStats(vl)
    segs = [vst[i] for i in range(1, nv) if vst[i][3] > H // 25]
    if segs and len(np.nonzero(hl)[0]):
        x0, x1 = min(s[0] for s in segs), max(s[0] + s[2] for s in segs)
        top = min(s[1] for s in segs)
        bot = max(s[1] + s[3] for s in segs)
        ytop = max(s[1] for s in segs if s[1] < top + 80) + 4
        ybot = min(s[1] + s[3] for s in segs if s[1] + s[3] > bot - 80) - 4
        cv2.line(vl, (int(x0), int(ytop)), (int(x1), int(ytop)), 255, 3)
        cv2.line(vl, (int(x0), int(ybot)), (int(x1), int(ybot)), 255, 3)
    # isto levo/desno: poslednja kolona bez spoljne linije (odsečen sken)
    nh, _, hst, _ = cv2.connectedComponentsWithStats(hl)
    hsegs = [hst[i] for i in range(1, nh) if hst[i][2] > W // 6]
    if hsegs and segs:
        y0, y1 = min(s[1] for s in hsegs), max(s[1] + s[3] for s in hsegs)
        left = min(s[0] for s in hsegs)
        right = max(s[0] + s[2] for s in hsegs)
        xl = max(s[0] for s in hsegs if s[0] < left + 80) + 4
        xr = min(s[0] + s[2] for s in hsegs if s[0] + s[2] > right - 80) - 4
        cv2.line(hl, (int(xl), int(y0)), (int(xl), int(y1)), 255, 3)
        cv2.line(hl, (int(xr), int(y0)), (int(xr), int(y1)), 255, 3)
    grid = cv2.dilate(cv2.bitwise_or(hl, vl), np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(255 - grid, connectivity=4)
    cells = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if x <= 2 or y <= 2 or x + w >= W - 2 or y + h >= H - 2:
            continue  # spoljašnji prostor (dodiruje ivicu)
        if w < 25 or h < 18 or w > W * 0.98:
            continue
        if a < 0.6 * w * h:
            continue  # nije pravougaonik (prostor van tabele okružen linijama)
        cells.append((int(x), int(y), int(w), int(h)))
    return cells, grid


def skew_angle(gray):
    """Nagib strane u stepenima, iz dugih skoro horizontalnih linija (tabela); 0 ako ih nema."""
    import cv2
    import numpy as np
    H, W = gray.shape
    inv = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    lines = cv2.HoughLinesP(inv, 1, np.pi / 1800, threshold=300, minLineLength=W // 4, maxLineGap=12)
    if lines is None:
        return 0.0
    ang, wts = [], []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(a) < 5:
            ang.append(a)
            wts.append(np.hypot(x2 - x1, y2 - y1))
    if len(ang) < 3:
        return 0.0
    order = np.argsort(ang)
    cum = np.cumsum(np.array(wts)[order])
    return float(np.array(ang)[order][np.searchsorted(cum, cum[-1] / 2)])  # težinska medijana


def group_rows(cells):
    rows = []
    for c in sorted(cells, key=lambda c: (c[1], c[0])):
        for r in rows:
            a = r[0]
            ov = min(a[1] + a[3], c[1] + c[3]) - max(a[1], c[1])
            if ov > 0.5 * min(a[3], c[3]):
                r.append(c)
                break
        else:
            rows.append([c])
    return [sorted(r, key=lambda c: c[0]) for r in rows]


def text_lines(words):
    """Reči (x,y,w,h,txt) -> [(y, linija)] odozgo nadole."""
    lines = []
    for wd in sorted(words, key=lambda w: (w[1] + w[3] / 2, w[0])):
        cy = wd[1] + wd[3] / 2
        for ln in lines:
            if abs(ln["cy"] - cy) <= max(12, wd[3] * 0.6):
                ln["w"].append(wd)
                break
        else:
            lines.append({"cy": cy, "w": [wd]})
    return [(int(ln["cy"]), " ".join(w[4] for w in sorted(ln["w"], key=lambda w: w[0]))) for ln in lines]


def words_to_text(words):
    return "\n".join(t for _, t in text_lines(words))


def read_numbers(clean, numcells, pytesseract, Image, np):
    """Sve ćelije sa rednim brojem slaže jednu ispod druge i čita ih jednim pozivom (samo cifre)."""
    if not numcells:
        return {}
    gap, crops, W = 40, [], max(c[2] for c in numcells.values())
    for ri, (x, y, w, h) in numcells.items():
        crops.append((ri, clean[y + 3:y + h - 3, x + 3:x + w - 3]))
    H = sum(c.shape[0] + gap for _, c in crops) + gap
    sheet = np.full((H, W + 2 * gap), 255, np.uint8)
    spans, yy = [], gap
    for ri, c in crops:
        sheet[yy:yy + c.shape[0], gap:gap + c.shape[1]] = c
        spans.append((ri, yy, yy + c.shape[0]))
        yy += c.shape[0] + gap
    d = pytesseract.image_to_data(Image.fromarray(sheet), lang="eng",
                                  config=f"{TD} --psm 6 -c tessedit_char_whitelist=0123456789.",
                                  output_type=pytesseract.Output.DICT)
    got = {}
    for i, t in enumerate(d["text"]):
        t = t.strip()
        if not re.match(r"\d", t):
            continue
        cy = d["top"][i] + d["height"][i] / 2
        for ri, a, b in spans:
            if a - 5 <= cy <= b + 5 and ri not in got:
                m = re.match(r"(\d{1,4})", t)
                got[ri] = m.group(1)
    return got


def pdf_words(path, idx):
    """Reči iz tekstualnog sloja PDF-a, u koordinatama slike (DPI). None ako je strana rotirana."""
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        pg = pdf.pages[idx]
        if (pg.rotation or 0) % 360:
            return None
        k = DPI / 72
        return [(w["x0"] * k, w["top"] * k, (w["x1"] - w["x0"]) * k, (w["bottom"] - w["top"]) * k, w["text"])
                for w in pg.extract_words(keep_blank_chars=False, use_text_flow=False)]


def ocr_page(args):
    path, idx, mode = args
    import numpy as np
    import pypdfium2 as pdfium
    import pytesseract
    from PIL import Image
    pytesseract.pytesseract.tesseract_cmd = str(TESS)
    img = pdfium.PdfDocument(str(path))[idx].render(scale=DPI / 72).to_pil().convert("L")
    words = pdf_words(path, idx) if mode == "pdf" else None
    if words is not None:
        gray = np.array(img)
        cells, grid = find_cells(gray)
        cyr = sum(len(re.findall(r"[а-шА-Ш]", w[4])) for w in words)
        return assemble(words, cells, gray, grid, None, 0, "Cyrillic" if cyr * 2 > sum(len(w[4]) for w in words) else "Latin")
    rot, script = 0, "Cyrillic"
    try:
        small = img.resize((img.width // 2, img.height // 2))
        osd = pytesseract.image_to_osd(small, config=f"--psm 0 {TD}")
        rot = int(re.search(r"Rotate: (\d+)", osd).group(1))
        script = re.search(r"Script: (\w+)", osd).group(1)
    except Exception:
        pass
    out, score = ocr_oriented(img, rot, script)
    if score < 0:
        # tabela je nađena, a teksta skoro nema: OSD je verovatno pogrešio rotaciju, probaj ostale
        for r2 in ((rot + 90) % 360, (rot + 270) % 360):
            o2, s2 = ocr_oriented(img, r2, script)
            if s2 > score:
                out, score = o2, s2
    return out


def ocr_oriented(img, rot, script):
    """OCR strane okrenute za `rot` stepeni. Vraća (izlaz, ocena); ocena < 0 = sumnjivo malo teksta."""
    import numpy as np
    import pytesseract
    from PIL import Image
    if rot:
        img = img.rotate(-rot, expand=True)
    sk = skew_angle(np.array(img))
    if abs(sk) > 0.15:  # nakošen sken: inače se ćelije susednih redova mešaju
        img = img.rotate(sk, resample=Image.BICUBIC, fillcolor=255)
    lang = "srp_latn" if script == "Latin" else "srp"
    gray = np.array(img)
    cells, grid = find_cells(gray)
    clean = gray.copy()
    clean[grid > 0] = 255  # brišemo linije tabele pre OCR-a

    def read(lang):
        d = pytesseract.image_to_data(Image.fromarray(clean), lang=lang, config=f"{TD} --psm 4",
                                      output_type=pytesseract.Output.DICT)
        ws = [(d["left"][i], d["top"][i], d["width"][i], d["height"][i], d["text"][i].strip(), float(d["conf"][i]))
              for i in range(len(d["text"])) if d["text"][i].strip() and float(d["conf"][i]) > 10]
        conf = sum(w[5] * len(w[4]) for w in ws) / max(1, sum(len(w[4]) for w in ws))
        return [w[:5] for w in ws], conf

    words, conf = read(lang)
    if lang == "srp_latn":
        # OSD često proglasi ćirilicu latinicom (ОСНОВНА -> "OCHOBHA"): probaj i ćirilicu, uzmi pouzdanije
        w2, c2 = read("srp")
        if c2 > conf:
            words, script, conf = w2, "Cyrillic", c2
    out = assemble(words, cells, clean, grid, pytesseract, rot, script)
    out["nagib"] = round(sk, 2)
    letters = sum(len(re.findall(r"[^\W\d_]", w[4])) for w in words)
    nrows = sum(1 for e in out["elementi"] if e[1] == "r")
    score = letters * conf / 100
    if len(cells) >= 8 and letters < 25 * nrows + 100:
        score -= 10 ** 6
    return out, score


def assemble(words, cells, clean, grid, pytesseract, rot, script):
    """Raspoređuje reči u ćelije tabele; pytesseract=None znači da se brojevi ne čitaju posebno (tekstualni PDF)."""
    import numpy as np
    from PIL import Image
    rows = []
    if len(cells) >= 4:
        used = set()
        tx0 = min(c[0] for c in cells)
        tw = max(c[0] + c[2] for c in cells) - tx0
        grows = group_rows(cells)
        numcells = {}
        for ri, r in enumerate(grows):
            x, y, w, h = r[0]
            if x - tx0 < 20 and w < 0.12 * tw and len(r) >= 3 and h > 12 and w > 12:
                numcells[ri] = r[0]  # uska prva kolona = redni broj biračkog mesta
        nums = read_numbers(clean, numcells, pytesseract, Image, np) if pytesseract else {}
        for ri, r in enumerate(grows):
            out = []
            for k, (x, y, w, h) in enumerate(r):
                inside = [wd for wd in words
                          if x - 4 <= wd[0] + wd[2] / 2 <= x + w + 4 and y - 4 <= wd[1] + wd[3] / 2 <= y + h + 4]
                used.update(id(wd) for wd in inside)
                t = " ".join(words_to_text(inside).split())
                if k == 0 and ri in nums:
                    t = nums[ri] + "."
                out.append(t)
            if any(out):
                rows.append([min(c[1] for c in r), "r", out])
        outside = [wd for wd in words if id(wd) not in used]
    else:
        outside = words
    # jedan niz po redosledu na strani: [y, "t", linija teksta] ili [y, "r", [ćelije reda tabele]]
    items = rows + [[y, "t", t] for y, t in text_lines(outside)]
    items.sort(key=lambda e: e[0])
    return {"rot": rot, "pismo": script, "elementi": items}


def suspicious(page) -> bool:
    """Strana sa tabelom, a skoro bez teksta (pogrešna rotacija)."""
    rows = [e[2] for e in page["elementi"] if e[1] == "r"]
    txt = " ".join(" ".join(e[2]) if e[1] == "r" else e[2] for e in page["elementi"])
    return sum(len(r) for r in rows) >= 8 and len(re.findall(r"[^\W\d_]", txt)) < 25 * len(rows) + 100


def redo(nproc):
    """Ponovo obradi samo sumnjive strane u već gotovim JSON fajlovima."""
    jobs = []
    for jf in sorted(OUT.glob("*.json")):
        d = json.loads(jf.read_text(encoding="utf-8"))
        if d["nacin"] == "ocr":
            jobs += [(jf, HERE / d["izvor"], i) for i, p in enumerate(d["strane"]) if suspicious(p)]
    print(f"Sumnjivih strana: {len(jobs)}", flush=True)
    with Pool(nproc) as pool:
        res = pool.map(ocr_page, [(f, i, "ocr") for _, f, i in jobs], chunksize=1)
    for (jf, _, i), r in zip(jobs, res):
        d = json.loads(jf.read_text(encoding="utf-8"))
        d["strane"][i] = r
        jf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        print("  ", jf.stem[:60], "str.", i + 1, "->", "i dalje sumnjiva" if suspicious(r) else "popravljena")


def main():
    import pypdfium2 as pdfium
    args = sys.argv[1:]
    if "--ponovi" in args:
        args.remove("--ponovi")
        redo(int(args[0]) if args else 2)
        return
    part = None
    if "--deo" in args:
        k = args.index("--deo")
        part = (int(args[k + 1]), int(args[k + 2]))
        del args[k:k + 3]
    nproc = int(args[0]) if args else max(1, (os.cpu_count() or 2))
    OUT.mkdir(exist_ok=True)
    todo = []
    for f in sorted(SRC.rglob("*")):
        if f.suffix.lower() != ".pdf":
            continue
        o = OUT / (f.parent.name + "__" + f.stem + ".json")
        if o.exists():
            continue
        todo.append((f, o, len(pdfium.PdfDocument(str(f)))))
    if part:
        # podela po broju strana: najveći fajl ide u najmanje opterećen deo (isto na svakoj mašini)
        load, mine = [0] * part[1], []
        for f, o, n in sorted(todo, key=lambda t: (-t[2], str(t[0]))):
            d = load.index(min(load))
            load[d] += n
            if d == part[0]:
                mine.append((f, o, n))
        todo = mine
    scans, jobs = [], []
    for f, o, n in todo:
        mode = "pdf" if has_text(f) else "ocr"
        scans.append((f, o, n, mode))
        jobs += [(f, i, mode) for i in range(n)]
    print(f"Fajlova: {len(scans)} (tekstualnih {sum(s[3] == 'pdf' for s in scans)}), strana: {len(jobs)}, "
          f"procesa: {nproc}", flush=True)
    res = {}
    with Pool(nproc) as pool:
        for k, r in enumerate(pool.imap(ocr_page, jobs, chunksize=1)):
            f, i, _ = jobs[k]
            res.setdefault(f, {})[i] = r
            for sf, so, sn, mode in scans:
                if sf == f and len(res[f]) == sn:
                    so.write_text(json.dumps({"izvor": f.relative_to(HERE).as_posix(), "nacin": mode,
                                              "strane": [res[f][j] for j in range(sn)]},
                                             ensure_ascii=False), encoding="utf-8")
                    print(f"OCR {k + 1}/{len(jobs)}", f.parent.name, f.name, flush=True)
                    del res[f]


if __name__ == "__main__":
    main()
