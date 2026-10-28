#!/usr/bin/env python3
"""
Rešenja opštinskih izbornih komisija o poništenju glasanja, zahtevima za poništenje i prigovorima, sa RIK-a
(dokumenti izbornih komisija, vrsta 1, Parlamentarni 2026). CSV rezultata ne označava poništena mesta.

Čuva sve nađeno u odluke_rik.json ({"do": vreme najnovijeg pregledanog dokumenta, "odluke": [...]}) i upisuje
`const ODLUKE=[{o, n, t, naziv, link, vreme}];` u izbori2026.html:
  o: indeks opštine u DATA.opstine, n: broj biračkog mesta (0 ako nije naveden),
  t: "pon" (glasanje poništeno), "odb" (zahtev za poništenje odbijen/odbačen), "pri" (prigovor).

RIK vraća dokumente od najnovijih, pa se podrazumevano pregledaju samo strane do već viđenog vremena
(pri osvežavanju na 10 minuta to je jedna strana); --sve pregleda sve (~270 strana).

    python odluke_rik.py [--sve]
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / "izbori2026.html"
STATE = HERE / "odluke_rik.json"
BASE = "https://www.rik.parlament.gov.rs"
API = BASE + "/get-additional-documents"
UA = {"User-Agent": "Mozilla/5.0 (izbori2026)", "X-Requested-With": "XMLHttpRequest"}

# šta je odluka o glasanju na biračkom mestu; imenovanja u biračkim odborima i pre-izborni prigovori nisu
ODB = re.compile(r"ЗАХТЕВ\w* ЗА ПОНИШТ")
PON = re.compile(r"ПОНИШТ\w* ГЛАСАЊ")
PRI = re.compile(r"ПРИГОВОР")
NE = re.compile(r"ИМЕНОВАЊ|РЕШЕЊА ОИК|ОДРЕЂИВАЊ|ИЗБОРНИХ МЕСТА|БИРАЧКИХ МЕСТА|ЧЛАН")
BM = re.compile(r"(?:\bБМ|БИРАЧКО\w* МЕСТ\w*)\s*(?:БР(?:ОЈ)?\.?\s*)?(\d+)")


def page(p):
    q = {"page": p, "filters[document-type]": "1", "filters[election-round]": "680072", "filters[municipality-id]": "",
         "filters[election_station]": "0", "filters[additional-document]": "0", "order": "2", "sort": "2", "election_type": "2"}
    for i in range(4):
        try:
            req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8")).get("records") or []
        except Exception:
            if i == 3:
                raise
            time.sleep(2 * (i + 1))


def vrsta(naziv):
    u = naziv.upper()
    if NE.search(u):
        return None
    if ODB.search(u):
        return "odb"
    if PON.search(u):
        return "pon"
    if PRI.search(u):
        return "pri"
    return None


def norm(s):
    return re.sub(r"^(градска општина|град|општина)\s+", "", s.strip().lower())


def main():
    sve = "--sve" in sys.argv
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() and not sve else {"do": 0, "odluke": []}
    html = HTML.read_text(encoding="utf-8")
    ops = json.loads(re.search(r"^const DATA=(.*);\r?$", html, re.M).group(1))["opstine"]
    opi = {norm(n): i for i, (n, _) in enumerate(ops)}
    known = {o["link"] for o in st["odluke"]}
    novo, top, p = [], st["do"], 1
    while True:
        rs = page(p)
        if not rs:
            break
        stop = False
        for r in rs:
            v = int(r.get("datetime") or 0)
            if v <= st["do"]:
                stop = True
                break
            top = max(top, v)
            naziv = " ".join((r.get("document_name") or "").split())
            t = vrsta(naziv)
            links = re.findall(r'href="([^"]+)"', " ".join(r.get("extfiles_link") or []))
            if not t or not links:
                continue
            link = urllib.parse.urljoin(BASE, urllib.parse.quote(urllib.parse.unquote(links[0]), safe="/:?=&%"))
            o = opi.get(norm(r.get("municipality_display_name") or ""))
            if o is None or link in known:
                continue
            m = BM.search(naziv.upper())
            novo.append({"o": o, "n": int(m.group(1)) if m else 0, "t": t, "naziv": naziv, "link": link, "vreme": v})
        if stop:
            break
        p += 1
        time.sleep(0.25)
    st["do"] = top
    st["odluke"] = sorted(st["odluke"] + novo, key=lambda x: -x["vreme"])
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    keep = [{k: x[k] for k in ("o", "n", "t", "naziv", "link", "vreme")} for x in st["odluke"]]
    line = "const ODLUKE=" + json.dumps(keep, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"
    if re.search(r"^const ODLUKE=.*;\r?$", html, re.M):
        html = re.sub(r"^const ODLUKE=.*;(?=\r?$)", lambda _: line, html, count=1, flags=re.M)
    else:
        i = html.index("const STAN=")
        html = html[:i] + "// rešenja OIK o poništenju glasanja, zahtevima za poništenje i prigovorima (odluke_rik.py)\n" + line + "\n" + html[i:]
    HTML.write_text(html, encoding="utf-8", newline="")
    print(f"Odluke OIK: pregledano strana {p}, novih {len(novo)}, ukupno {len(keep)} "
          f"(poništeno {sum(x['t'] == 'pon' for x in keep)}, odbijeni zahtevi {sum(x['t'] == 'odb' for x in keep)}, prigovori {sum(x['t'] == 'pri' for x in keep)})")


if __name__ == "__main__":
    main()
