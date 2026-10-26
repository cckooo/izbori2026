#!/usr/bin/env python3
"""
Skida odluke o određivanju biračkih mesta (Parlamentarni 2026) sa sajta RIK-a.

Stranica https://www.rik.parlament.gov.rs/dokumenta/41985 puni tabelu iz
JSON API-ja `get-additional-documents`, pa skripta ide direktno na njega
(Playwright nije potreban). Koristi samo standardnu biblioteku.

Pokretanje:
    python rik_biracka_mesta.py download   # spisak u rik_dokumenti.json + PDF-ovi u rik_fajlovi/

Dalje: ocr_odluke.py (tabele i tekst iz PDF-ova), pa parse_odluke.py (spajanje sa rezultatima).
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.rik.parlament.gov.rs"
API = BASE + "/get-additional-documents"
DOC_TYPE = "3"            # БИРАЧКА МЕСТА
ELECTION = "680072"       # Парламентарни 2026
ELECTION_TYPE = "2"
HERE = Path(__file__).resolve().parent
OUT = HERE / "rik_fajlovi"
UA = {"User-Agent": "Mozilla/5.0 (izbori2026)", "X-Requested-With": "XMLHttpRequest"}

# Dokumenti koji nisu odluke o biračkim mestima (zapisnici BO, rešenja o BO, planovi obuke)
SKIP = re.compile(r"ЗАПИСНИК|РЕШЕЊЕ О ИСПРАВЦИ ТЕХНИЧКЕ ГРЕШКЕ У РЕШЕЊУ|ПЛАН СПРОВОЂЕЊА")


def safe(name: str) -> str:
    """Bezbedno ime fajla; skraćuje se osnova, ekstenzija ostaje."""
    p = Path(name)
    stem = re.sub(r"[^\w\-. ()]+", "_", p.stem).strip()[:100] or "x"
    return stem + re.sub(r"[^\w.]+", "", p.suffix)


def http(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=90).read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def api_page(page: int) -> dict:
    q = {"page": page, "filters[document-type]": DOC_TYPE,
         "filters[election-round]": ELECTION, "filters[municipality-id]": "",
         "filters[election_station]": "0", "filters[additional-document]": "0",
         "order": "2", "sort": "2", "election_type": ELECTION_TYPE}
    return json.loads(http(API + "?" + urllib.parse.urlencode(q)).decode("utf-8"))


def list_documents() -> list:
    recs, page = [], 1
    while True:
        rs = api_page(page).get("records") or []
        if not rs:
            break
        for r in rs:
            links = re.findall(r'href="([^"]+)"', " ".join(r.get("extfiles_link") or []))
            recs.append({
                "opstina": r.get("municipality_display_name", "").strip(),
                "naziv": " ".join(r.get("document_name", "").split()),
                "vreme": int(r.get("datetime") or 0),
                "izdao": r.get("document_bearer", ""),
                "linkovi": [urllib.parse.urljoin(BASE, urllib.parse.quote(urllib.parse.unquote(h), safe="/:?=&%"))
                            for h in links],
            })
        page += 1
        time.sleep(0.3)
    return recs


def download():
    OUT.mkdir(exist_ok=True)
    recs = list_documents()
    saved = skipped = 0
    for r in recs:
        r["fajlovi"] = []
        if SKIP.search(r["naziv"]):
            r["preskoceno"] = True
            skipped += 1
            continue
        d = OUT / safe(r["opstina"] or "nepoznato")
        d.mkdir(exist_ok=True)
        for href in r["linkovi"]:
            f = d / safe(Path(urllib.parse.unquote(href.split("?")[0])).name)
            if not f.exists():
                f.write_bytes(http(href))
                saved += 1
                print("OK ", r["opstina"], "|", f.name)
            r["fajlovi"].append(f.relative_to(HERE).as_posix())
    (HERE / "rik_dokumenti.json").write_text(
        json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Dokumenata: {len(recs)}, preskočeno: {skipped}, novo skinuto: {saved}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"download": download}.get(cmd, lambda: print(__doc__))()
