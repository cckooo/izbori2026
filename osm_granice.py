#!/usr/bin/env python3
"""
Administrativne granice (nivoi 6–9: okruzi, opštine, gradske opštine, naselja) iz OpenStreetMap izvoda Geofabrik-a
za Srbiju i Kosovo -> _osm_cache/granice.json; koriste ih mapa_opstina.py i mapa_naselja.py (bez Overpass-a).

    python osm_granice.py      # skine izvode ako ih nema (~270 MB), pa ih pročita (nekoliko minuta)

Treba paket osmium (pip install osmium). Podaci © OpenStreetMap contributors, ODbL.
"""
import json
import urllib.request
from pathlib import Path

import osmium

HERE = Path(__file__).resolve().parent
CACHE = HERE / "_osm_cache"
PBF = {c: CACHE / "pbf" / f"{c}.osm.pbf" for c in ("serbia", "kosovo")}
OUT = CACHE / "granice.json"
LEVELS = {"6", "7", "8", "9"}
KEEP = ("name", "name:sr", "name:sr-Latn", "admin_level", "boundary")


class Granice(osmium.SimpleHandler):
    def __init__(self, out):
        super().__init__()
        self.out = out

    def area(self, a):
        t = a.tags
        if a.from_way() or t.get("boundary") != "administrative" or t.get("admin_level") not in LEVELS:
            return
        rings = [[[round(n.lon, 6), round(n.lat, 6)] for n in ring] for ring in a.outer_rings()]
        if rings:
            self.out[a.orig_id()] = {"id": a.orig_id(), "tags": {k: t[k] for k in KEEP if k in t}, "rings": rings}


def main():
    for c, f in PBF.items():
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            print("Skidam", c)
            urllib.request.urlretrieve(f"https://download.geofabrik.de/europe/{c}-latest.osm.pbf", f)
    out = {}
    for c, f in PBF.items():
        Granice(out).apply_file(str(f), locations=True)
        print(c, "->", len(out), "granica ukupno")
    OUT.write_text(json.dumps({"elements": list(out.values())}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    lv = {}
    for e in out.values():
        lv[e["tags"].get("admin_level")] = lv.get(e["tags"].get("admin_level"), 0) + 1
    print("Upisano", OUT.name, f"{OUT.stat().st_size / 1e6:.0f} MB, po nivou:", dict(sorted(lv.items())))


if __name__ == "__main__":
    main()
