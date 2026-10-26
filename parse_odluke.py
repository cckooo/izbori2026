#!/usr/bin/env python3
"""
Od izlaza ocr_odluke.py (rik_ocr/*.json) pravi spisak biračkih mesta sa naseljima,
spaja ga sa CSV-om rezultata po (opština, broj BM) i upisuje NASELJA u izbori2026.html.

Pokretanje:
    python parse_odluke.py rezultati.csv            # biracka_mesta.csv + izvestaj_spajanja.txt
    python parse_odluke.py rezultati.csv --html     # i upiše `const NASELJA=...;` u izbori2026.html

Pravila:
- broj BM mora da postoji u odluci (ili da se jednoznačno izvede iz suseda u istoj tabeli);
- spoj se prihvata ako je naziv mesta iz odluke dovoljno sličan nazivu u CSV-u, ili ako je
  numeracija cele odluke za tu opštinu potvrđena (većina naziva se poklapa); ostalo ostaje prazno;
- od više odluka za isto mesto (izmene, dopune) bira se najnovija koja se poklapa po nazivu.
"""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz

HERE = Path(__file__).resolve().parent
OCR = HERE / "rik_ocr"
DOCS = HERE / "rik_dokumenti.json"
HTML = HERE / "izbori2026.html"

# ------------------------------------------------------------------ normalizacija
CYR2LAT = dict(zip("абвгдђежзијклљмнњопрстћуфхцчџш",
                   ["a", "b", "v", "g", "d", "dj", "e", "z", "z", "i", "j", "k", "l", "lj", "m", "n", "nj", "o",
                    "p", "r", "s", "t", "c", "u", "f", "h", "c", "c", "dz", "s"]))
LAT_FIX = str.maketrans({"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "dj"})
ABBR = [(r"\bosnovn\w* skol\w*", "os"), (r"\bmesn\w* zajednic\w*", "mz"), (r"\bmesn\w* kancelarij\w*", "mk"),
        (r"\bdom kulture\b", "dk"), (r"\bzgrada\b", ""), (r"\bprostorij\w*", ""), (r"\bsala\b", ""),
        (r"\bbr\b", ""), (r"\bul\b", ""), (r"\bulica\b", "")]


def asc(s: str) -> str:
    """Ćirilica/latinica -> mala ASCII latinica (za poređenje)."""
    s = s.lower()
    s = "".join(CYR2LAT.get(ch, ch) for ch in s)
    return s.translate(LAT_FIX)


def name_key(s: str) -> str:
    s = asc(s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    for a, b in ABBR:
        s = re.sub(a, b, s)
    return " ".join(s.split())


def name_sim(a: str, b: str) -> float:
    """Sličnost naziva 0-100; otporna na razbijene reči iz OCR-a i skraćenice (ОШ, МЗ, ДК)."""
    best = 0.0
    for f in (name_key, lambda s: " ".join(re.sub(r"[^a-z0-9 ]+", " ", asc(s)).split())):
        x, y = f(a), f(b)
        if not x or not y:
            continue
        xs, ys = x.replace(" ", ""), y.replace(" ", "")
        best = max(best, fuzz.token_set_ratio(x, y), fuzz.ratio(x, y), fuzz.ratio(xs, ys))
        if min(len(xs), len(ys)) >= 8:
            best = max(best, fuzz.partial_ratio(xs, ys) - 10)
    return best


def op_key(s: str) -> str:
    """Naziv opštine bez 'Градска општина', 'Општина', 'Град' i dodatka u zagradi."""
    s = re.sub(r"^\s*(градска општина|општина|град)\s+", "", s.strip(), flags=re.I)
    return asc(s).strip()


# ------------------------------------------------------------------ CSV rezultata
def load_results(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig", newline="")))
    ops = {}
    for r in rows:
        ops.setdefault(r["opstina"], {"okrug": r["okrug_region"], "bm": {}})["bm"][int(r["bm_broj"])] = r["bm_naziv"]
    return ops


# ------------------------------------------------------------------ dokument -> opštine
FAMILIES = {  # odluka grada pokriva i gradske opštine
    "nis": ["Градска општина Медијана", "Градска општина Палилула (Ниш)", "Градска општина Пантелеј",
            "Градска општина Црвени крст", "Градска општина Нишка Бања"],
    "pozarevac": ["Град Пожаревац", "Градска општина Костолац"],
    "uzice": ["Град Ужице", "Градска општина Севојно"],
}


def doc_targets(folder: str, fname: str, title: str, text: str, ops: dict) -> list:
    """Kojim opštinama iz CSV-a može pripadati dokument."""
    fk = op_key(folder)
    if folder == "РИК":
        t = asc(title + " " + fname)
        if "inostran" in t:
            return ["Иностранство"]
        if "zavod" in t:
            return ["Заводи за извршење кривичних санкција"]
        return []
    if fk.startswith("palilula"):
        return ["Градска општина Палилула (Београд)"] if "beograd" in fk else ["Градска општина Палилула (Ниш)"]
    if fk in FAMILIES:
        return FAMILIES[fk]
    exact = [o for o in ops if op_key(o) == fk and "палилула" not in o.lower()]
    okrug = ops[exact[0]]["okrug"] if exact else ""
    # dokument iz fascikle jedne opštine koji se odnosi na drugu (Kosovo: Gnjilane, K. Mitrovica, Priština, Peć, Gora)
    if okrug.split("/")[0].startswith("Регион Косова") or fk in ("gora",):
        cand = [o for o in ops if ops[o]["okrug"].split("/")[0].startswith("Регион Косова")]
        hay = asc(fname + " " + title)
        best, score = None, 0
        for o in cand:
            k = op_key(o)
            s = fuzz.partial_ratio(k, hay) if len(k) > 3 else (100 if re.search(rf"\b{k}\b", hay) else 0)
            if s > score:
                best, score = o, s
        if best and score >= 85:
            return [best]
        # naziv opštine u tekstu odluke ("на територији општине ...")
        m = re.search(r"teritorij\w*\s+(?:opstin\w*|grad\w*)\s+([a-z ]{3,30})", asc(text[:3000]))
        if m:
            for o in cand:
                if fuzz.partial_ratio(op_key(o), m.group(1)) >= 85:
                    return [o]
    return exact


# ------------------------------------------------------------------ tabela -> zapisi
HDR = {"br": r"^(р\.?\s*б|ред|бр|r\.?\s*b|red|br|број|broj)\b",
       "naziv": r"назив|naziv",
       "adresa": r"адрес|adres",
       "podr": r"подручј|područ|podruc|обухват|obuhvat|бирачи из|birači iz|улиц|ulic|насељ|naselj|сел[оа]|sel[oa]"}


def header_roles(cells):
    """Ako je red zaglavlje tabele, vraća ulogu svake kolone; inače None."""
    low = [c.lower() for c in cells]
    if any(len(c) > 120 for c in cells) or any(parse_num(c) is not None for c in cells if c):
        return None  # zaglavlje nema dug tekst ni redni broj
    if not any(re.search(HDR["naziv"], c) for c in low) and not any(re.search(r"подручј|podru", c) for c in low):
        return None
    roles = []
    for i, c in enumerate(low):
        if re.search(HDR["adresa"], c):
            roles.append("adresa")
        elif re.search(r"подручј|područ|podruc|обухват|obuhvat", c):
            roles.append("podr")
        elif re.search(HDR["naziv"], c):
            roles.append("naziv")
        elif re.search(HDR["br"], c.strip()) or (i == 0 and len(c.strip()) <= 8):
            roles.append("br")
        elif re.search(HDR["podr"], c):
            roles.append("podr")
        else:
            roles.append("?")
    # podeljeno zaglavlje ("НАЗИВ БИРАЧКОГ" / "МЕСТА"): neprepoznata kolona posle broja je naziv
    if "naziv" not in roles and "?" in roles[1:]:
        roles[roles.index("?", 1)] = "naziv"
    if "adresa" not in roles and "naziv" in roles and "?" in roles[roles.index("naziv"):]:
        roles[roles.index("?", roles.index("naziv"))] = "adresa"
    return roles if "podr" in roles or "naziv" in roles else None


def default_roles(cells):
    n = len(cells)
    first_num = bool(re.match(r"^\s*\d{1,4}\s*\.?\s*$", cells[0])) or cells[0].strip() == ""
    if n >= 4:
        return ["br", "naziv", "adresa"] + ["?"] * (n - 4) + ["podr"]
    if n == 3:
        return ["br", "naziv", "podr"] if first_num else ["naziv", "adresa", "podr"]
    if n == 2:
        return ["naziv", "podr"]
    return ["podr"]


def parse_num(s):
    """Redni broj iz ćelije; dozvoljava OCR šum oko broja ("5 —", "[6]", "12,")."""
    s = s.strip().replace("O", "0").replace("О", "0")
    if len(s) > 8:
        return None
    m = re.match(r"^\W*(\d{1,4})\W*$", s)
    return int(m.group(1)) if m else None


def clean(s):
    s = re.sub(r"\s+", " ", s or "").strip(" ,;|—–-~_")
    s = re.sub(r"\s+([,.;:])", r"\1", s)
    return s


BOILER = re.compile(r"^(на овом бирачком месту гласају бирачи|na ovom biračkom mestu glasaju birači)"
                    r"[^:]*?(пребивалиште|prebivalište)\s+(на подручју\s+|na području\s+)?", re.I)


def clean_naselja(s):
    s = clean(s)
    s = BOILER.sub("", s)
    s = re.sub(r",\s*[„“\"_–—|~]+\s*(?=\w)", ", ", s)  # ",„Војвођанска"  ", _ Рибарска"
    s = re.sub(r"\s+[_|~]+\s+", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s[:1].upper() + s[1:] if s else s


def extract_records(doc, targets):
    """Iz elemenata dokumenta vadi zapise {br, naziv, adresa, naselja, cilj}."""
    recs, roles, cur_target = [], None, (targets[0] if len(targets) == 1 else None)
    target_keys = [(t, op_key(t)) for t in targets]
    for pg in doc["strane"]:
        for y, kind, val in pg["elementi"]:
            if kind == "t":
                if len(targets) > 1:  # naslov odeljka: "ГРАДСКА ОПШТИНА МЕДИЈАНА"
                    a = asc(val)
                    for t, k in target_keys:
                        if re.search(rf"\b{re.escape(k.split(' (')[0])}\b", a) and len(a) < 80:
                            cur_target = t
                continue
            cells = [c.strip() for c in val]
            while len(cells) > 1 and not cells[-1] and (not roles or len(cells) > len(roles)):
                cells.pop()  # prazna ćelija uz ivicu tabele (ostatak veštačke linije)
            hr = header_roles(cells)
            if hr:
                roles = hr
                continue
            partial = roles and len(cells) < len(roles)
            if partial and parse_num(cells[0]) is None and recs:
                txt = " ".join(c for c in cells if c)
                if len(txt) > 60 or txt.count(",") >= 2:
                    # delimičan red sa spiskom ulica: nastavak prethodnog mesta
                    recs[-1]["naselja"] = (recs[-1]["naselja"] + " " + txt).strip()
                    continue
            # delimičan red sa nazivom/adresom: kolone redom po zaglavlju (nedostaju poslednje)
            r = roles if roles and len(roles) == len(cells) else (roles[:len(cells)] if partial else default_roles(cells))
            f = {"br": "", "naziv": "", "adresa": "", "podr": ""}
            for role, c in zip(r, cells):
                if role in f:
                    f[role] = (f[role] + " " + c).strip()
            num = parse_num(f["br"]) if f["br"] else None
            if num is None and "br" not in r:
                # tabela bez kolone sa brojem (npr. odsečen sken): svaki red sa nazivom je novo mesto
                cont = not f["naziv"]
            else:
                cont = num is None and not f["naziv"]
            if cont and recs:
                p = recs[-1]
                for k in ("naziv", "adresa"):
                    if f[k]:
                        p[k] = (p[k] + " " + f[k]).strip()
                if f["podr"]:
                    p["naselja"] = (p["naselja"] + " " + f["podr"]).strip()
                continue
            if cont:
                continue
            recs.append({"br": num, "naziv": clean(f["naziv"]), "adresa": clean(f["adresa"]),
                         "naselja": f["podr"], "cilj": cur_target, "imaBr": "br" in r})
    for r in recs:
        r["naselja"] = clean_naselja(r["naselja"])
    # broj koji OCR nije pročitao ili je pročitao pogrešno: između k i k+2 je k+1
    for i, r in enumerate(recs):
        if r["imaBr"] and 0 < i < len(recs) - 1:
            a, b = recs[i - 1]["br"], recs[i + 1]["br"]
            if a is not None and b == a + 2 and r["br"] != a + 1:
                r["br"], r["izveden"] = a + 1, True
            elif a is not None and r["br"] is not None and r["br"] != a + 1 \
                    and str(a + 1).endswith(str(r["br"])) and b in (None, a + 2):
                r["br"], r["izveden"] = a + 1, True  # izgubljena prva cifra: "2" umesto 12
    # niz redova bez broja između a i b, kojih ima tačno b-a-1 (ili na početku pre broja k: k-1 redova)
    known = [i for i, r in enumerate(recs) if r["br"] is not None and r["imaBr"]]
    for i0, i1 in zip([-1] + known, known):
        a = recs[i0]["br"] if i0 >= 0 else 0
        gap = [i for i in range(i0 + 1, i1) if recs[i]["br"] is None and recs[i]["imaBr"]]
        if gap and len(gap) == i1 - i0 - 1 and recs[i1]["br"] - a - 1 == len(gap):
            for k, i in enumerate(gap, 1):
                recs[i]["br"], recs[i]["izveden"] = a + k, True
    return recs


# ------------------------------------------------------------------ glavni tok
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    ops = load_results(sys.argv[1])
    meta = {}
    for d in json.loads(DOCS.read_text(encoding="utf-8")):
        for f in d.get("fajlovi", []):
            meta[Path(f).name] = d
    by_op = defaultdict(list)  # opština -> [(vreme, dokument, zapis)]
    out_rows, doc_report = [], []
    for jf in sorted(OCR.glob("*.json")):
        doc = json.loads(jf.read_text(encoding="utf-8"))
        src = Path(doc["izvor"])
        m = meta.get(src.name, {})
        text = " ".join(str(e[2]) for p in doc["strane"][:2] for e in p["elementi"] if e[1] == "t")
        targets = doc_targets(src.parent.name, src.stem, m.get("naziv", ""), text, ops)
        recs = extract_records(doc, targets)
        # tabela bez brojeva (odsečen sken): numeracija po redu ako se broj mesta slaže sa CSV-om
        if recs and all(r["br"] is None for r in recs) and len(targets) == 1:
            if len(recs) == len(ops[targets[0]]["bm"]):
                for i, r in enumerate(recs, 1):
                    r["br"], r["po_redu"] = i, True
        doc_report.append((src, doc["nacin"], targets, recs))
        for r in recs:
            tgt = r["cilj"] or (targets[0] if len(targets) == 1 else None)
            out_rows.append([tgt or src.parent.name, r["br"] if r["br"] is not None else "", r["naziv"],
                             r["adresa"], r["naselja"]])
            cands = [tgt] if tgt else targets
            for t in cands:
                by_op[t].append((m.get("vreme", 0), src, r))

    with open(HERE / "biracka_mesta.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["opstina", "bm_broj", "naziv", "adresa", "naselja"])
        w.writerows(out_rows)

    # ---- spajanje
    naselja, rep = {}, []
    stats = defaultdict(int)
    for op, info in ops.items():
        cands = by_op.get(op, [])
        if not cands:
            stats["bez_odluke"] += len(info["bm"])
            rep.append(f"[BEZ ODLUKE] {op}: {len(info['bm'])} mesta (nema odluke ili nije pročitana)")
            continue
        # potvrda numeracije: koliki deo numerisanih zapisa se poklapa po nazivu
        scored = []
        for t, src, r in cands:
            if r["br"] in info["bm"] and r["naselja"]:
                scored.append((name_sim(r["naziv"] + " " + r["adresa"], info["bm"][r["br"]]),
                               max(name_sim(r["naziv"], info["bm"][r["br"]]), 0), t, src, r))
        ok_share = (sum(1 for s in scored if max(s[0], s[1]) >= 70) / len(scored)) if scored else 0
        best = {}
        for s_full, s_nm, t, src, r in scored:
            s = max(s_full, s_nm)
            k = r["br"]
            # prednost: poklapanje naziva, pa novija odluka
            key = (s >= 70, t, s)
            if k not in best or key > best[k][0]:
                best[k] = (key, s, src, r)
        miss_reasons = []
        for k, nm in sorted(info["bm"].items()):
            if k not in best:
                miss_reasons.append(f"BM {k} ({nm}): nije nađeno u odluci")
                stats["nije_nadjeno"] += 1
                continue
            _, s, src, r = best[k]
            blank = len(name_key(r["naziv"])) < 3 and not r.get("izveden")  # OCR nije pročitao naziv
            if s >= 70 or (ok_share >= 0.8 and (s >= 35 or blank)):
                naselja.setdefault(op, {})[str(k)] = r["naselja"]
                stats["spojeno"] += 1
                if s < 70:
                    stats["spojeno_po_broju"] += 1
                    miss_reasons.append(f"BM {k}: spojeno po broju (numeracija potvrđena {ok_share:.0%}), "
                                        f"naziv se razlikuje: odluka „{r['naziv']}“ / CSV „{nm}“")
            else:
                stats["odbijeno"] += 1
                miss_reasons.append(f"BM {k} ({nm}): odbijeno, naziv u odluci „{r['naziv']}“ "
                                    f"(sličnost {s:.0f}, potvrda numeracije {ok_share:.0%})")
        n_ok = len(naselja.get(op, {}))
        rep.append(f"[{n_ok}/{len(info['bm'])}] {op}" + ("" if not miss_reasons else ""))
        rep += ["    " + x for x in miss_reasons]

    total = sum(len(i["bm"]) for i in ops.values())
    head = [
        "IZVEŠTAJ O SPAJANJU ODLUKA O BIRAČKIM MESTIMA SA REZULTATIMA",
        f"Ukupno biračkih mesta u CSV-u: {total}",
        f"Spojeno (naselja upisana): {stats['spojeno']} ({stats['spojeno'] / total:.1%}), "
        f"od toga samo po broju uz potvrđenu numeraciju: {stats['spojeno_po_broju']}",
        f"Opština bez odluke ili bez pročitanih redova: {stats['bez_odluke']} mesta",
        f"Mesto nije nađeno u odluci (OCR nije pročitao broj ili red): {stats['nije_nadjeno']}",
        f"Odbijeno zbog nepoklapanja naziva: {stats['odbijeno']}",
        "",
        "DOKUMENTI (način čitanja, opštine, broj pročitanih mesta):",
    ]
    for src, nacin, targets, recs in doc_report:
        nb = sum(1 for r in recs if r["br"] is not None)
        flag = "  <-- ništa nije pročitano" if not recs else ""
        head.append(f"  {nacin:4s} {src.parent.name} / {src.name}: {', '.join(targets) or '?'}; "
                    f"zapisa {len(recs)}, sa brojem {nb}{flag}")
    head += ["", "PO OPŠTINAMA:"]
    (HERE / "izvestaj_spajanja.txt").write_text("\n".join(head + rep) + "\n", encoding="utf-8")
    print("\n".join(head[:7]))

    if "--html" in sys.argv:
        html = HTML.read_bytes().decode("utf-8")
        line = "const NASELJA=" + json.dumps(naselja, ensure_ascii=False, separators=(",", ":")) + ";"
        html, n = re.subn(r"^const NASELJA=.*;(?=\r?$)", lambda _: line, html, count=1, flags=re.M)
        if n != 1:
            raise SystemExit("Nema linije `const NASELJA=...;` u HTML-u")
        HTML.write_bytes(html.encode("utf-8"))
        print("NASELJA upisana u", HTML.name)


if __name__ == "__main__":
    main()
