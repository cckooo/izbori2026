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
    # dokument iz fascikle jedne opštine koji se odnosi na drugu (Kosovo: Gnjilane, K. Mitrovica, Priština, Peć, Gora):
    # opština iz imena fajla ima prednost nad fasciklom
    if okrug.split("/")[0].startswith("Регион Косово") or fk in ("gora",):
        cand = [o for o in ops if ops[o]["okrug"].split("/")[0].startswith("Регион Косово")]
        hay = asc(fname)
        best, score = None, 0
        for o in cand:
            k = op_key(o)
            s = fuzz.partial_ratio(k, hay) if len(k) > 4 else (100 if re.search(rf"\b{k}\b", hay) else 0)
            if s > score or (s == score and best and len(k) > len(op_key(best))):
                best, score = o, s  # duže ime pobeđuje ("kosovska kamenica" pre "kosovo")
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
HDR = {"br": r"^(р\.?\s*б|ред|бр|r\.?\s*b|red|br)",
       "naziv": r"назив|naziv",
       "adresa": r"адрес|adres",
       "podr": r"подручј|područ|podruc|обухват|obuhvat|бирачи из|birači iz|улиц|ulic|насељ|naselj|сел[оа]|sel[oa]"}


def header_roles(cells):
    """Ako je red zaglavlje tabele, vraća ulogu svake kolone; inače None."""
    low = [c.lower() for c in cells]
    if any(len(c) > 120 for c in cells):
        return None  # zaglavlje nema dug tekst (a "Ред. бр." čitač cifara često pročita kao "6.")
    if not any(re.search(HDR["naziv"], c) for c in low) and not any(re.search(r"подручј|podru", c) for c in low):
        return None
    # bar dve kratke ćelije sa ključnim rečima (red podataka može slučajno da sadrži "назив" ili "подручју")
    kw = r"назив|naziv|адрес|adres|подручј|područ|podruc|обухват|obuhvat"
    if sum(1 for c in low if re.search(kw, c) and len(c) < 70) < 2:
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
    if roles[0] == "?" and "naziv" in roles[1:2]:
        roles[0] = "br"  # prva kolona ispred naziva je redni broj
    # podeljeno zaglavlje ("НАЗИВ БИРАЧКОГ" / "МЕСТА"): neprepoznata kolona posle broja je naziv
    if "naziv" not in roles and "?" in roles[1:]:
        roles[roles.index("?", 1)] = "naziv"
    if "podr" not in roles and roles[-1] == "?":
        roles[-1] = "podr"  # nečitljiv naslov poslednje kolone: to je područje
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
    # OCR čita ćirilično "бб" (bez broja) kao "66"; ispravljamo samo jednoznačne slučajeve
    s = re.sub(r"(улице|ulice)\s*66\b", r"\1 бб", s, flags=re.I)
    s = re.sub(r"(\d+\s*-\s*\d+\s+и)\s+66(?=\s*[,.;)]|\s*$)", r"\1 бб", s)
    return s[:1].upper() + s[1:] if s else s


def load_rzs():
    """Zvanična naselja (Popis 2022, naselja_rzs.csv): op_key(opština) -> [(ime, osnovno ime, gradsko, stan, pun)]."""
    f = HERE / "naselja_rzs.csv"
    ref = defaultdict(list)
    if f.exists():
        for r in csv.DictReader(open(f, encoding="utf-8")):
            base = re.sub(r"\s*\(.*\)$", "", r["naselje"])  # "Београд (Врачар)" -> "Београд"
            ref[op_key(r["opstina"])].append((r["naselje"], base, r["gradsko"] == "1",
                                             int(r["stanovnika"] or 0) or None, int(r["punoletnih"] or 0) or None))
    return ref


def join_names(names):
    """Spisak imena -> "A, B и C" (bez ponavljanja)."""
    n = list(dict.fromkeys(names))
    return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " и " + n[-1]


def official(name, cands, cut=88):
    """Zvanično ime naselja za dati tekst (tačno ili blisko, jednoznačno), inače None."""
    k = asc(name)
    for c in cands:
        if asc(c[1]) == k:
            return c[1]
    sc = sorted(((fuzz.ratio(k, asc(c[1])), c) for c in cands), key=lambda x: -x[0])
    if sc and sc[0][0] >= cut and (len(sc) == 1 or sc[0][0] - sc[1][0] >= 8):
        return sc[0][1][1]
    return None


def canon_naselje(nas, op, ref, stats, area=""):
    """Ime naselja iz odluke -> zvanično ime iz popisa (ili isto, ako se ne može potvrditi)."""
    cands = ref.get(op_key(op))
    if not cands or not nas:
        stats["naselje_bez_spiska"] += 1
        return nas
    # područje koje počinje selima ("Набоје и Шипче", "Горња Бејашница, Горња Топоница, …") ima prednost
    # nad mestom iz adrese biračkog mesta; bar pola prvih stavki mora biti zvanično naselje
    t = re.sub(r"^[\W\d_]*(за\s+)?(насељен[оа]\s+мест[оа]|насеља|насеље|мз|месна заједница)\s*[:.]?\s*", "",
               area.strip(), flags=re.I)
    items = [re.sub(r"[\s\d\-–/.,:;()]+$", "", x).strip() for x in re.split(r",|;|:|\s+и\s+|\s+i\s+", t, flags=re.I)][:6]
    items = [x for x in items if x]
    hits = [h for h in (official(x, cands) for x in items) if h]
    if items and len(hits) * 2 >= len(items):
        stats["naselje_potvrdjeno"] += 1
        return join_names(hits)
    parts = [p.strip() for p in re.split(r",|\s+и\s+|\s+i\s+", nas) if p.strip()]
    fixed = []
    for p in parts:
        k = asc(p)
        exact = [c for c in cands if asc(c[1]) == k]
        if exact:
            fixed.append(exact[0][1])
            continue
        sc = sorted(((fuzz.ratio(k, asc(c[1])), c) for c in cands), key=lambda x: -x[0])
        if sc and sc[0][0] >= 85 and (len(sc) == 1 or sc[0][0] - sc[1][0] >= 8):
            fixed.append(sc[0][1][1])
            stats["naselje_ispravljeno"] += 1
            continue
        fixed.append(None)
    if all(fixed):
        stats["naselje_potvrdjeno"] += 1
        return join_names(fixed)
    if any(fixed):
        stats["naselje_potvrdjeno"] += 1  # deo imena je potvrđen (ostalo su zaseoci, delovi naselja)
        return join_names(f for f in fixed if f)
    # tekst sadrži ime zvaničnog naselja ("Сакуле Трг Маршала" -> Сакуле)
    full = asc(nas)
    inside = [c for c in cands if len(c[1]) > 3 and re.search(rf"\b{re.escape(asc(c[1]))}\b", full)]
    if inside:
        stats["naselje_potvrdjeno"] += 1
        return max(inside, key=lambda c: len(c[1]))[1]
    # ime opštine iz adrese, ulica ili nečitljiv OCR ostatak: najveće gradsko naselje opštine
    # (Вождовац -> Београд, Ада -> Ада); to su gradska biračka mesta čije područje odluka daje samo ulicama
    opn = re.sub(r"^(Градска општина|Општина|Град)\s+|\s*\(.*\)$", "", op)
    streetlike = re.search(r"(ска|чка|шка|цка|ића|ић|ина|ова|ева|ског|ских|ата|ника)$|\bбб\b|\bпут\b|улиц|трг|\d",
                           nas.strip(" |.,'\""), re.I) or len(nas.split()) >= 2 and re.search(r"(е|и|ља)$", nas.split()[0]) \
        or not re.search(r"[а-яђјљњћџ]{4}", nas, re.I)
    if not streetlike:
        # OCR greška u imenu sela ("Кобишнишџа" -> Кобишница): slabiji prag, ali jednoznačno
        sc = sorted(((fuzz.ratio(full, asc(c[1])), c) for c in cands), key=lambda x: -x[0])
        if sc and sc[0][0] >= 75 and (len(sc) == 1 or sc[0][0] - sc[1][0] >= 8):
            stats["naselje_ispravljeno"] += 1
            return sc[0][1][1]
    urban = sorted((c for c in cands if c[2]), key=lambda c: -(c[3] or 0))
    if urban and (asc(nas) == asc(opn) or streetlike):
        stats["naselje_gradsko"] += 1
        return urban[0][1]
    # zaselak koji nije u popisu (Росуље, Даутовац): ostaje ime iz odluke, ne pripisuje se gradu;
    # ako se ime ponavlja i u području (adresa i područje se čitaju odvojeno, pa OCR ostatak teško prođe);
    # naziv ustanove ("Основна школа", "Дом културе") ili nepotvrđen OCR ostatak: prazno
    stats["naselje_nepotvrdjeno"] += 1
    clean = re.fullmatch(r"[А-ЯЂЈЉЊЋЏ][а-яђјљњћџ]+(?:[ -][А-ЯЂЈЉЊЋЏа-яђјљњћџ][а-яђјљњћџ]+){0,2}", nas.strip())
    inst = re.search(r"школ|\bдом\b|заједниц|кућа|локал|мотел|ресторан|\bош\b|\bмз\b|^село$|ић\s", nas, re.I) or \
        re.fullmatch(r"(Горњ|Доњ|Велик|Мал|Нов|Стар|Бачк|Војвод|Четрдесет|Анастас)\w*", nas.strip(), re.I)
    seen = re.search(rf"\b{re.escape(asc(nas.strip()))}\b", asc(area))
    return nas.strip() if clean and not inst and seen else ""


def nice(s):
    """"СТАРО ГЛОГОВЦЕ" -> "Старо Глоговце"; tekst koji nije sav velikim slovima ostaje."""
    s = s.strip(" .,;:-–")
    return s.title() if s.isupper() else s


def split_area(area, adresa, opstina):
    """Područje iz odluke -> (naselje, ulice). Naselje je kratko ime mesta, ulice ostatak (ili prazno)."""
    t = re.sub(r"^(улице|ulice)\s*:\s*", "", area.strip(), flags=re.I)
    m = re.match(r"^(?:насеље|naselje)\s+([^:,]{2,40}):\s*(.+)$", t, re.I | re.S) or \
        re.match(r"^(?:насеље|naselje)\s*:\s*(.{2,40}?)\s+(?:улице|ulice)\s*[;:]\s*(.+)$", t, re.I | re.S)
    if m:
        return nice(m.group(1)), m.group(2)
    m = re.match(r"^([^,(:\d]{3,40}?)\s*(?:\(\s*нема улице\s*\)|[-–]\s*нема улице|\(\s*nema ulice\s*\)|[-–]\s*nema ulice)",
                 t, re.I)
    if m:
        return nice(m.group(1)), t
    a = adresa.strip()
    first = a.split(",")[0].strip() if "," in a else (a if not re.search(r"\d", a) else "")
    first = re.split(r"\s+(?:трг|ул\.?|улица|бр\.?|trg|ul\.?|ulica|br\.?)(?:\s|$)", first, flags=re.I)[0].strip()
    items = [x.strip(" .") for x in re.split(r",|;|\s+и\s+|\s+i\s+", t) if x.strip(" .")]
    street = re.compile(r"(ска|чка|шка|цка|ића|ина|ова|ева|ског|ских|ата|ника|ska|čka|ića|ina|ova|eva)$"
                        r"|улиц|ulic|трг|trg|пут|put|булевар|bulevar|\d", re.I)
    if t and items and len(items) <= 4 and all(len(x.split()) <= 3 for x in items) \
            and not any(street.search(x) for x in items) \
            and (not a or any(fuzz.ratio(asc(x), asc(first or a)) >= 85 for x in items)):
        return nice(t), ""  # samo sela, a jedno je mesto biračkog mesta: "Папратиште и Табановићи"
    if items and not street.search(items[0]) and len(items[0].split()) <= 3 \
            and first and fuzz.ratio(asc(items[0]), asc(first)) >= 85:
        return nice(items[0]), t  # selo pa ulice: "Пауне, Виноградарска, Солунских ратника"
    m = re.match(r"^([^,(:\d]{3,30}?)\s+[–-]\s+\S", t)
    if m:
        return nice(m.group(1)), t[m.end(1):].strip(" –-")
    if first and not re.search(r"\d|^ул\b|^ul\b|улиц|ulic", first, re.I) and len(first.split()) <= 4:
        return nice(first), t
    return re.sub(r"^(Градска општина|Општина|Град)\s+|\s*\(.*\)$", "", opstina), t


def extract_records(doc, targets):
    """Iz elemenata dokumenta vadi zapise {br, naziv, adresa, naselja, cilj}."""
    recs, roles, cur_target = [], None, (targets[0] if len(targets) == 1 else None)
    target_keys = [(t, op_key(t)) for t in targets]
    for pno, pg in enumerate(doc["strane"], 1):
        for y, kind, val in pg["elementi"]:
            filled = [c for c in val if c.strip()] if kind == "r" else [val]
            if len(targets) > 1 and len(filled) == 1 and len(filled[0]) < 80:
                # naslov odeljka ("1.2. ГРАДСКА ОПШТИНА ПАЛИЛУЛА"), kao linija teksta ili red sa jednom ćelijom
                a = asc(filled[0])
                hit = [t for t, k in target_keys if re.search(rf"\b{re.escape(k.split(' (')[0])}\b", a)]
                if hit:
                    cur_target = hit[0]
                    continue
            if kind == "t":
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
                         "naselja": f["podr"], "cilj": cur_target, "imaBr": "br" in r, "str": pno})
    for i, r in enumerate(recs):
        if not r["naselja"].strip():
            # pomerene kolone: spisak ulica je završio u nazivu ili adresi
            lists = [k for k in ("naziv", "adresa") if len(re.findall(r"[,;]", r[k])) >= 2 and len(r[k]) > 30]
            if lists:
                k = max(lists, key=lambda k: len(r[k]))
                r["naselja"], r[k] = r[k], ""
                if k == "naziv":
                    r["naziv_pomeren"] = True
        r["naselja"] = clean_naselja(r["naselja"])
        r["i"] = i  # redosled u odluci (za dodelu između potvrđenih suseda)
    # broj koji OCR nije pročitao ili je pročitao pogrešno: između k i k+2 je k+1
    for i, r in enumerate(recs):
        if r["imaBr"] and 0 < i < len(recs) - 1:
            a, b = recs[i - 1]["br"], recs[i + 1]["br"]
            if a is not None and b == a + 2 and r["br"] != a + 1:
                r["br"], r["izveden"] = a + 1, True
            elif a is not None and r["br"] is not None and r["br"] != a + 1 \
                    and str(a + 1).endswith(str(r["br"])) and b in (None, a + 2):
                r["br"], r["izveden"] = a + 1, True  # izgubljena prva cifra: "2" umesto 12
    # prvi red tabele: ako slede k i k+1, on je k-1 ("1." pročitano kao "4.")
    nums = [r for r in recs if r["imaBr"]]
    if len(nums) >= 3 and nums[1]["br"] is not None and nums[2]["br"] == nums[1]["br"] + 1 \
            and nums[1]["br"] > 1 and nums[0]["br"] != nums[1]["br"] - 1:
        nums[0]["br"], nums[0]["izveden"] = nums[1]["br"] - 1, True
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
    naselja, rep, detalji = {}, [], []
    ref = load_rzs()
    rucno = defaultdict(dict)
    if (HERE / "rucno_naselja.csv").exists():
        for rr in csv.DictReader(open(HERE / "rucno_naselja.csv", encoding="utf-8")):
            rucno[rr["opstina"]][int(rr["bm_broj"])] = rr
    # broj stanovnika po naselju (Popis 2022) za opštine iz CSV-a: {opština: {naselje: [stanovnika, punoletnih]}}
    stanovnici = {}
    for op in ops:
        for _, base, _, st, pun in ref.get(op_key(op), []):
            if st:
                stanovnici.setdefault(op, {})[base] = [st, pun]
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
        miss_reasons, acc, why = [], {}, {}
        for k, nm in sorted(info["bm"].items()):
            if k not in best:
                why[k] = f"BM {k} ({nm}): nije nađeno u odluci"
                continue
            _, s, src, r = best[k]
            blank = len(name_key(r["naziv"])) < 3 and not r.get("izveden")  # OCR nije pročitao naziv
            if s >= 70 or (ok_share >= 0.8 and (s >= 35 or blank)):
                acc[k] = (src, r, s, "broj")
            else:
                why[k] = (f"BM {k} ({nm}): odbijeno, naziv u odluci „{r['naziv']}“ "
                          f"(sličnost {s:.0f}, potvrda numeracije {ok_share:.0%})")
        by_src = defaultdict(list)
        for _, src, r in cands:
            by_src[src].append(r)
        # provera položaja: red za mesto k mora u odluci da stoji između redova za k-1 i k+1
        # (inače je broj pogrešno pročitan, npr. dva reda "4." sa istim nazivom škole)
        for k in sorted(acc):
            src, r, s, how = acc[k]
            lo, hi = acc.get(k - 1), acc.get(k + 1)
            if not lo or not hi or lo[0] != src or hi[0] != src or lo[1]["i"] < r["i"] < hi[1]["i"]:
                continue
            alt = [x for x in by_src[src] if x is not r and x["br"] == k and lo[1]["i"] < x["i"] < hi[1]["i"]
                   and x["naselja"]]
            if alt:
                acc[k] = (src, alt[0], name_sim(alt[0]["naziv"] + " " + alt[0]["adresa"], info["bm"][k]), how)
            else:
                del acc[k]
                why[k] = f"BM {k} ({info['bm'][k]}): red sa tim brojem nije između susednih mesta (sumnjiv broj)"
                stats["polozaj_prazno"] += 1
            stats["popravljen_polozaj"] += 1
        # drugi prolaz: mesto bez pročitanog broja traži se po nazivu, samo među redovima odluke
        # koji stoje između dva već potvrđena suseda (redosled u odluci prati redosled mesta)
        used = {(src, r["i"]) for src, r, _, _ in acc.values()}
        for k in sorted(why):
            nm = info["bm"][k]
            lo = max((j for j in acc if j < k), default=None)
            hi = min((j for j in acc if j > k), default=None)
            srcs = {acc[j][0] for j in (lo, hi) if j is not None}
            if len(srcs) != 1:
                continue
            src = srcs.pop()
            if lo is not None and acc[lo][0] == src:
                i0 = acc[lo][1]["i"]
            else:
                i0 = acc[hi][1]["i"] - (hi - k) - 2
            if hi is not None and acc[hi][0] == src:
                i1 = acc[hi][1]["i"]
            else:
                i1 = acc[lo][1]["i"] + (k - lo) + 2
            win = sorted((r for r in by_src[src] if i0 < r["i"] < i1 and r["naselja"]), key=lambda r: r["i"])
            pick, ps = None, 0
            if lo is not None and hi is not None and acc[lo][0] == acc[hi][0] == src and len(win) == hi - lo - 1:
                # u prozoru je tačno onoliko redova koliko mesta nedostaje: red po poziciji, naziv mora da se slaže
                r = win[k - lo - 1]
                if (src, r["i"]) not in used:
                    pick, ps = r, name_sim(r["naziv"] + " " + r["adresa"], nm)
            else:
                sc = sorted(((name_sim(r["naziv"] + " " + r["adresa"], nm), r) for r in win
                             if (src, r["i"]) not in used), key=lambda x: -x[0])
                # samo nedvosmislen kandidat (npr. ne bira se jedna od više "ОСНОВНА ШКОЛА")
                if sc and (len(sc) == 1 or sc[0][0] - sc[1][0] >= 10):
                    ps, pick = sc[0]
            if pick and ps >= 70:
                acc[k] = (src, pick, ps, "redosled")
                used.add((src, pick["i"]))
                del why[k]
        # ručna dopuna (rucno_naselja.csv): prepisano sa strane odluke, ima prednost
        for k, rr in rucno.get(op, {}).items():
            if k in info["bm"]:
                acc[k] = (Path("rik_fajlovi") / rr["izvor"], {"naziv": "", "adresa": rr["adresa"],
                          "naselja": clean_naselja(rr["podrucje"]), "str": int(rr["strana"] or 0)}, 100, "rucno")
                why.pop(k, None)
        for k, nm in sorted(info["bm"].items()):
            if k in why:
                miss_reasons.append(why[k])
                stats["odbijeno" if "odbijeno" in why[k] else "nije_nadjeno"] += 1
                continue
            src, r, s, how = acc[k]
            nas, ul = split_area(r["naselja"], r["adresa"], op)
            nas = canon_naselje(nas, op, ref, stats, r["naselja"])
            naselja.setdefault(op, {})[str(k)] = [nas, ul]
            detalji.append({"opstina": op, "bm": k, "csv_naziv": nm, "naziv": r["naziv"], "slicnost": round(s),
                            "izvor": src.as_posix(), "strana": r["str"], "naselje": nas, "naselja": r["naselja"],
                            "nacin": how})
            stats["spojeno"] += 1
            if how == "rucno":
                stats["spojeno_rucno"] += 1
            elif how == "redosled":
                stats["spojeno_po_redosledu"] += 1
            elif s < 70:
                stats["spojeno_po_broju"] += 1
                miss_reasons.append(f"BM {k}: spojeno po broju (numeracija potvrđena {ok_share:.0%}), "
                                    f"naziv se razlikuje: odluka „{r['naziv']}“ / CSV „{nm}“")
        n_ok = len(naselja.get(op, {}))
        rep.append(f"[{n_ok}/{len(info['bm'])}] {op}" + ("" if not miss_reasons else ""))
        rep += ["    " + x for x in miss_reasons]

    total = sum(len(i["bm"]) for i in ops.values())
    head = [
        "IZVEŠTAJ O SPAJANJU ODLUKA O BIRAČKIM MESTIMA SA REZULTATIMA",
        f"Ukupno biračkih mesta u CSV-u: {total}",
        f"Spojeno (naselja upisana): {stats['spojeno']} ({stats['spojeno'] / total:.1%}), "
        f"od toga samo po broju uz potvrđenu numeraciju: {stats['spojeno_po_broju']}, "
        f"po nazivu između potvrđenih suseda (broj nije pročitan): {stats['spojeno_po_redosledu']}, "
        f"ručno prepisano sa strane odluke (rucno_naselja.csv): {stats['spojeno_rucno']}",
        f"Opština bez odluke ili bez pročitanih redova: {stats['bez_odluke']} mesta",
        f"Mesto nije nađeno u odluci (OCR nije pročitao broj ili red): {stats['nije_nadjeno']}",
        f"Odbijeno zbog nepoklapanja naziva: {stats['odbijeno']}",
        f"Provera položaja u odluci (red nije između susednih mesta): {stats['popravljen_polozaj']} "
        f"slučajeva, od toga ostavljeno prazno: {stats['polozaj_prazno']}",
        f"Naselje prema spisku RZS (Popis 2022): potvrđeno {stats['naselje_potvrdjeno']}, od toga OCR ispravki "
        f"{stats['naselje_ispravljeno']}; gradsko naselje opštine {stats['naselje_gradsko']}; "
        f"nepotvrđeno {stats['naselje_nepotvrdjeno']}; bez spiska (Kosovo, inostranstvo, zavodi) "
        f"{stats['naselje_bez_spiska']}",
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
    (HERE / "spajanje_detalji.json").write_text(json.dumps(detalji, ensure_ascii=False, indent=0), encoding="utf-8")
    print("\n".join(head[:7]))

    if "--html" in sys.argv:
        html = HTML.read_bytes().decode("utf-8")
        line = "const NASELJA=" + json.dumps(naselja, ensure_ascii=False, separators=(",", ":")) + ";"
        html, n = re.subn(r"^const NASELJA=.*;(?=\r?$)", lambda _: line, html, count=1, flags=re.M)
        if n != 1:
            raise SystemExit("Nema linije `const NASELJA=...;` u HTML-u")
        line2 = "const STANOVNICI=" + json.dumps(stanovnici, ensure_ascii=False, separators=(",", ":")) + ";"
        html, n = re.subn(r"^const STANOVNICI=.*;(?=\r?$)", lambda _: line2, html, count=1, flags=re.M)
        if n != 1:  # prvi put: nova linija odmah posle NASELJA
            html = re.sub(r"^(const NASELJA=.*;)(\r?\n)", lambda m: m.group(1) + m.group(2) + line2 + m.group(2),
                          html, count=1, flags=re.M)
        HTML.write_bytes(html.encode("utf-8"))
        print("NASELJA upisana u", HTML.name)


if __name__ == "__main__":
    main()
