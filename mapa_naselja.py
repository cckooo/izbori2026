#!/usr/bin/env python3
"""
Granice naselja za mapu izabrane opštine: OpenStreetMap (© OpenStreetMap contributors, ODbL) -> mapa_naselja.json.

1. Naselja (admin_level=9) iz izvoda OpenStreetMap-a (osm_granice.py -> _osm_cache/granice.json).
2. Za svako naselje iz NASELJA (u izbori2026.html) traži se relacija istog imena čije je težište unutar granice opštine
   (granice opština iz mapa_opstina.py); isto ime se često ponavlja u više opština.
   Opština sa jednim naseljem bez granice dobija granicu cele opštine (npr. gradske opštine).
3. Za svaku opštinu: sopstvena projekcija širine 400 px, uprošćavanje (Douglas–Peucker).
   Izlaz: {"opština": {"w","h","o": obris opštine, "n": {"naselje": path}}} u mapa_naselja.json.
   Sajt preuzima taj fajl tek kad se otvori opština (podeli_sajt.py ga kopira u _site).

    python osm_granice.py             # jednom: izvod Srbije i Kosova sa Geofabrik-a
    python mapa_naselja.py
"""
import json
import math
import re
from pathlib import Path

import mapa_opstina as MO

HERE = Path(__file__).resolve().parent
OUT = HERE / "mapa_naselja.json"
W = 400
TOL = 0.5


def inside(pt, rings):
    """Tačka u multipoligonu (parnost preseka)."""
    x, y = pt
    c = False
    for r in rings:
        for (x1, y1), (x2, y2) in zip(r, r[1:]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
    return c


def center(rings):
    """Težište najvećeg prstena (dovoljno za proveru pripadnosti opštini)."""
    r = max(rings, key=len)
    a = cx = cy = 0
    for (x1, y1), (x2, y2) in zip(r, r[1:]):
        f = x1 * y2 - x2 * y1
        a += f
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    if abs(a) < 1e-12:
        return (sum(p[0] for p in r) / len(r), sum(p[1] for p in r) / len(r))
    return (cx / (3 * a), cy / (3 * a))


def main():
    html = MO.HTML.read_text(encoding="utf-8")
    data = json.loads(re.search(r"^const DATA=(.*);\r?$", html, re.M).group(1))
    nas = json.loads(re.search(r"^const NASELJA=(.*);\r?$", html, re.M).group(1))
    pick, G, _, _, _ = MO.opstine(data)

    # naselja (nivo 9)
    rel = {i: e for i, e in MO.granice().items() if e["tags"].get("admin_level") == "9"}
    by_name = {}
    for e in rel.values():
        for k in ("name:sr", "name"):
            v = e["tags"].get(k)
            if v:
                by_name.setdefault(v.strip().lower(), set()).add(e["id"])
    def rings(i):
        return [[tuple(p) for p in r] for r in rel[i]["rings"]]

    res, nmiss, ntot = {}, [], 0
    for op, mesta in nas.items():
        if not pick.get(op):
            continue
        orings = G[pick[op][0]]
        names = sorted({x for v in mesta.values() for x in re.split(r", | и ", v[0] or "") if x})
        found = {}
        for n in names:
            ntot += 1
            for i in by_name.get(n.lower(), ()):
                rs = rings(i)
                if rs and inside(center(rs), orings):
                    found[n] = rs
                    break
            else:
                nmiss.append((op, n))
        if len(names) == 1 and not found:  # npr. gradska opština = jedno naselje
            found[names[0]] = orings
            nmiss.pop()
        if not found:
            continue
        # projekcija za opštinu
        lat0 = sum(p[1] for r in orings for p in r) / sum(len(r) for r in orings)
        k = math.cos(math.radians(lat0))
        pts = [p for r in orings for p in r]
        minx, maxx = min(p[0] for p in pts) * k, max(p[0] for p in pts) * k
        miny, maxy = min(-p[1] for p in pts), max(-p[1] for p in pts)
        s = W / (maxx - minx)

        def path(rs):
            out = []
            for r in rs:
                q = [((p[0] * k - minx) * s, (-p[1] - miny) * s) for p in r]
                h = len(q) // 2
                pp = MO.dp(q[:h + 1], TOL) + MO.dp(q[h:], TOL)[1:]
                if len(pp) >= 3:
                    out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pp) + "Z")
            return "".join(out)
        res[op] = {"w": W, "h": round((maxy - miny) * s), "o": path(orings), "n": {n: path(rs) for n, rs in found.items()}}

    OUT.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Opština sa mapom: {len(res)}; naselja: {ntot - len(nmiss)} od {ntot} ({(ntot - len(nmiss)) / ntot:.1%}); "
          f"{OUT.name} {OUT.stat().st_size / 1e6:.2f} MB")
    for op, n in nmiss[:25]:
        print("  bez granice:", op, "–", n)


if __name__ == "__main__":
    main()
