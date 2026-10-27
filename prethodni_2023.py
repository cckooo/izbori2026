#!/usr/bin/env python3
"""
Skida rezultate parlamentarnih izbora 2023. (17. decembar) po biračkim mestima sa sajta RIK-a.

Za 2023. RIK ne nudi CSV (/export-results/341140/2 vraća grešku 500, „allowed_download“: false), pa se
rezultati čitaju preko istog API-ja koji koristi stranica /542645/rezultati/: regioni -> opštine ->
biračka mesta -> rezultat svakog mesta (oko 8.300 upita, nekoliko istovremeno).

Izlaz: rezultati_2023.csv sa kolonama
    region, opstina, bm_broj, bm_naziv, upisani_biraci, glasali_biraci, vazeci_glasovi, nevazeci_listici, lista_1 ... lista_N
Nazivi listi 2023. idu u liste_2023.txt.

    python prethodni_2023.py [--jobs 6]
"""
import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://www.rik.parlament.gov.rs"
ROUND = "341140"  # Parlamentarni 2023
HERE = Path(__file__).parent
num = lambda s: int(str(s).replace(".", "").replace(",", "") or 0)


def post(path, data, tries=5):
    body = urllib.parse.urlencode(data).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(BASE + path, data=body, headers={
                "X-Requested-With": "XMLHttpRequest", "User-Agent": "Mozilla/5.0 (izbori26.rs)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # mreža ili 5xx: kratka pauza pa ponovo
            if i == tries - 1:
                raise
            time.sleep(2 + 3 * i)


def regions():
    return json.loads(post("/get-regions/", {"election_type": 2, "election_round": ROUND}))["regions"]


def municipalities(reg):
    t = post("/get-municipalities/", {"election_type": 2, "election_round": ROUND, "election_region": reg})
    return [(v, html.unescape(n).strip()) for v, n in re.findall(r'<option[^>]*\bvalue="(\d+)"[^>]*>([^<]*)</option>', t) if v != "0"]


def stations(reg, mun):
    t = json.loads(post("/get-election-stations/", {"election_type": 2, "election_round": ROUND,
                                                    "election_region": reg, "election_municipality": mun}))
    return list((t.get("election_stations") or {}).items())


def result(reg, mun, st):
    j = json.loads(post("/get_results/", {"should_update_pies": 1, "type": 2, "election_round": ROUND,
                                          "region": reg, "municipality": mun, "election_station": st}))
    s = j["stat_sum_numbers"]
    valid, invalid = j["sum_config"]["data"]["datasets"][0]["data"]
    lists = {}
    for row in j["table_data"]:
        n = int(row["count_number"])
        lists[n] = (num(row["won_number"]), row["list_name"])
    return num(s["total_voters"]), num(s["available"]), num(valid), num(invalid), lists


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    jobs = []
    for reg, rname in regions().items():
        for mun, mname in municipalities(reg):
            for st, sname in stations(reg, mun):
                m = re.match(r"\s*(\d+)\s*-\s*(.*)", html.unescape(sname))
                jobs.append((reg, rname, mun, mname, st, m.group(1) if m else "", (m.group(2) if m else sname).strip()))
        print(f"{rname}: {len(jobs)} mesta do sada", flush=True)

    out, names, done = [None] * len(jobs), {}, [0]

    def one(i):
        reg, rname, mun, mname, st, broj, naziv = jobs[i]
        up, gl, va, nv, lists = result(reg, mun, st)
        for n, (_, nm) in lists.items():
            names.setdefault(n, nm)
        out[i] = [rname, mname, broj, naziv, up, gl, va, nv, {n: v for n, (v, _) in lists.items()}]
        done[0] += 1
        if done[0] % 500 == 0:
            print(f"  {done[0]}/{len(jobs)}", flush=True)

    with ThreadPoolExecutor(a.jobs) as ex:
        list(ex.map(one, range(len(jobs))))
    nl = max(names)
    with open(HERE / "rezultati_2023.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["region", "opstina", "bm_broj", "bm_naziv", "upisani_biraci", "glasali_biraci",
                    "vazeci_glasovi", "nevazeci_listici"] + [f"lista_{i}" for i in range(1, nl + 1)])
        for r in out:
            w.writerow(r[:8] + [r[8].get(i, 0) for i in range(1, nl + 1)])
    (HERE / "liste_2023.txt").write_text("\n".join(names[i] for i in sorted(names)) + "\n", encoding="utf-8")
    print(f"Upisano {len(out)} mesta, {nl} listi -> rezultati_2023.csv")


if __name__ == "__main__":
    sys.exit(main())
