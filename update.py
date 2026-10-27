#!/usr/bin/env python3
"""
Osvežava podatke u izbori2026.html iz najnovijeg CSV-a sa sajta RIK-a.

Dugme „Преузми резултате у CSV формату“ na https://www.rik.parlament.gov.rs/542645/rezultati/
vodi na stalan URL  /export-results/<id izbora>/2  (id 680072 = Parlamentarni 2026).
Ime preuzetog fajla se menja (npr. 12:09:47_26.10.2026.csv), URL ne.

Pokretanje:
    python update.py                 # skine CSV i ažurira izbori2026.html
    python update.py --csv fajl.csv  # koristi lokalni CSV
    python update.py --dry-run       # samo proveri, ne upisuj

Izlazni kod: 0 = ažurirano ili nema promena, 1 = greška (HTML ostaje netaknut).
Koristi samo standardnu biblioteku Pythona.
"""
import argparse
import csv
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

URL = "https://www.rik.parlament.gov.rs/export-results/680072/2"
# Linkovi zapisnika u CSV-u nemaju dva broja iz prave putanje (…/election_results/815/417/<hash>/…pdf),
# pa vraćaju 404. Pravu putanju daje get_results za svako biračko mesto; čuvamo je u kešu.
API = "https://www.rik.parlament.gov.rs/get_results/"
HERE = Path(__file__).resolve().parent
HTML = HERE / "izbori2026.html"
CACHE = HERE / "zapisnici_putanje.json"
MAX_LOOKUPS = 600  # najviše upita po pokretanju (ostatak u sledećem)
RIK_BASE = "election_results/"
NLISTS = 18
NUM_COLS = ["upisani_biraci", "glasali_biraci", "vazeci_glasovi", "nevazeci_listici"]


def fetch(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (izbori2026 update.py)"})
            with urllib.request.urlopen(req, timeout=120) as r:
                ctype = r.headers.get("Content-Type", "")
                body = r.read()
            if "csv" not in ctype and not body.lstrip(b"\xef\xbb\xbf").startswith(b"bm_uid"):
                raise ValueError(f"nije CSV (Content-Type: {ctype}): {body[:200]!r}")
            return body
        except Exception as e:  # noqa
            print(f"Pokušaj {i + 1}: {e}", file=sys.stderr)
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def station_paths(uid: str) -> list:
    """Sve putanje PDF-ova (relativno na election_results/) koje RIK prikazuje za biračko mesto."""
    body = urllib.parse.urlencode({"should_update_pies": 1, "type": 2, "election_round": 680072,
                                   "region": 0, "municipality": 0, "election_station": uid}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "User-Agent": "Mozilla/5.0 (izbori2026 update.py)", "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        t = r.read().decode("utf-8")
    try:
        t = json.dumps(json.loads(t), ensure_ascii=False)  # П, \/ -> obični znakovi
    except ValueError:
        pass
    t = t.replace("\\/", "/")
    return re.findall(r"election_results/(\d+/\d+/[^\"'<>\n]+?\.pdf)", t)


def fix_links(rows: list, uids: list):
    """Dopuni putanje zapisnika (r[9]) pravim prefiksom iz keša ili sa RIK-a."""
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = [(r, u) for r, u in zip(rows, uids) if r[9] and not r[9].startswith("!") and r[9] not in cache]
    done = 0

    def look(item):
        r, u = item
        try:
            return item, station_paths(u)
        except Exception as e:  # noqa
            print(f"Upozorenje: putanja zapisnika za BM {u}: {e}", file=sys.stderr)
            return item, None
    with ThreadPoolExecutor(4) as ex:
        for (r, u), paths in ex.map(look, todo[:MAX_LOOKUPS]):
            if paths:
                for p in paths:
                    cache[p.split("/", 2)[2]] = p
                done += 1
    for r in rows:
        if r[9] in cache:
            r[9] = cache[r[9]]
    if done:
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8")
    left = sum(1 for r in rows if r[9] and not r[9].startswith("!") and not re.match(r"\d+/\d+/", r[9]))
    print(f"Putanje zapisnika: {done} novih sa RIK-a, bez prave putanje još {left}")


def build_data(raw: bytes) -> dict:
    text = raw.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    need = ["bm_broj", "bm_naziv", "opstina", "okrug_region", "vreme_unosa_rezultata", "zapisnik_link"] \
        + NUM_COLS + [f"lista_{i}" for i in range(1, NLISTS + 1)]
    if not rows or any(c not in rows[0] for c in need):
        raise ValueError("CSV nema očekivane kolone")
    okruzi, opstine, ok_idx, op_idx, out = [], [], {}, {}, []
    for r in rows:
        ok = r["okrug_region"]
        if ok not in ok_idx:
            ok_idx[ok] = len(okruzi)
            okruzi.append(ok)
        op = r["opstina"]
        if op not in op_idx:
            op_idx[op] = len(opstine)
            opstine.append([op, ok_idx[ok]])
        uneto = r["vreme_unosa_rezultata"].strip() not in ("-", "")
        # polje može imati više zapisnika ("naziv|url" po redu, npr. ponovljeno glasanje): uzimamo poslednji
        urls = re.findall(r"\|\s*(https?://\S[^\r\n|]*?)\s*(?=\r?\n|$)", r["zapisnik_link"])
        link = urls[-1].strip() if urls else ""
        if RIK_BASE in link:
            link = link.split(RIK_BASE, 1)[1]
        elif link:
            link = "!" + link  # pun URL van RIK_BASE
        nums = [int(r[c] or 0) for c in NUM_COLS]
        votes = [int(r[f"lista_{i}"] or 0) for i in range(1, NLISTS + 1)]
        out.append([ok_idx[ok], op_idx[op], int(r["bm_broj"]), r["bm_naziv"], *nums,
                    1 if uneto else 0, link, *votes])
    fix_links(out, [r["bm_uid"] for r in rows])
    times = [r["vreme_unosa_rezultata"] for r in rows if r["vreme_unosa_rezultata"].strip() not in ("-", "")]
    return {"okruzi": okruzi, "opstine": opstine, "rows": out, "snapshot": max(times) if times else ""}


def check(new: dict, old: dict):
    """Zaštita od pokvarenog ili nepotpunog CSV-a."""
    if len(new["rows"]) < 0.98 * len(old["rows"]):
        raise ValueError(f"premalo redova: {len(new['rows'])} (bilo {len(old['rows'])})")
    if new["snapshot"] and old["snapshot"] and new["snapshot"] < old["snapshot"]:
        raise ValueError(f"stariji presek ({new['snapshot']}) od postojećeg ({old['snapshot']})")
    for r in new["rows"]:
        if r[8] and sum(r[10:]) != r[6]:
            print(f"Upozorenje: zbir glasova ≠ važeći ({new['opstine'][r[1]][0]}, BM {r[2]})", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="lokalni CSV umesto skidanja")
    ap.add_argument("--html", default=str(HTML))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    raw = Path(a.csv).read_bytes() if a.csv else fetch(URL)
    html_path = Path(a.html)
    html = html_path.read_bytes().decode("utf-8")  # bez konverzije krajeva redova
    if re.search(r"^(<<<<<<<|>>>>>>>)", html, re.M) or len(re.findall(r"^const (DATA|NASELJA)=", html, re.M)) != 2:
        raise SystemExit("HTML je pokvaren (git konflikt ili dupli podaci) - prvo ga popravi")
    m = re.search(r"^const DATA=(.*);(?=\r?$)", html, re.M)
    if not m:
        raise SystemExit("Nema linije `const DATA=...;` u HTML-u")
    old = json.loads(m.group(1))
    new = build_data(raw)
    check(new, old)
    line = "const DATA=" + json.dumps(new, ensure_ascii=False, separators=(",", ":")) + ";"
    if line == m.group(0):
        print(f"Nema promena (presek {new['snapshot']}).")
        return
    nd_old = sum(r[8] for r in old["rows"])
    nd_new = sum(r[8] for r in new["rows"])
    print(f"Presek {old['snapshot']} -> {new['snapshot']}; uneto mesta {nd_old} -> {nd_new} od {len(new['rows'])}")
    if a.dry_run:
        return
    html = html[:m.start()] + line + html[m.end():]
    tmp = html_path.with_suffix(".tmp")
    tmp.write_bytes(html.encode("utf-8"))
    tmp.replace(html_path)
    print("Upisano:", html_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa
        print("GREŠKA:", e, file=sys.stderr)
        sys.exit(1)
