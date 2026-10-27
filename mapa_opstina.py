#!/usr/bin/env python3
"""
Granice opština za mapu na sajtu: OpenStreetMap (© OpenStreetMap contributors, ODbL) -> uprošćene SVG putanje.

1. Granice iz izvoda OpenStreetMap-a (osm_granice.py -> _osm_cache/granice.json), nivoi 6–8.
2. Za svaku opštinu iz DATA.opstine bira relaciju po zvaničnom imenu („Град X“, „Општина X“, „Градска општина X“);
   opštine na Kosovu su „Komuna e … / Opština …“ (nivo 6). Posebno: Косовска Каменица = Општина Каменица,
   Гора = Општина Драгаш (Gora je danas deo Dragaša). Ostale opštine na Kosovu idu u pozadinu (sivo).
3. Spoljne prstenove projektuje (ekvidistantno, cos 44°) i uprošćava (Douglas–Peucker).
4. Upisuje `const MAPA={w,h,o:{"opština":"path"},bg:[path],ins:{bg|ni:{w,h,o}}};` u izbori2026.html (posle PRETHODNI);
   ins su uvećani isečci gradskih opština Beograda (bg) i Niša (ni).

    python osm_granice.py             # jednom: izvod Srbije i Kosova sa Geofabrik-a
    python mapa_opstina.py
"""
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / "izbori2026.html"
GRANICE = HERE / "_osm_cache" / "granice.json"  # osm_granice.py (nije u repozitorijumu)
POSEBNO = {"Косовска Каменица": "Општина Каменица", "Гора": "Општина Драгаш"}
BEOGRAD = "Град Београд"
W = 600  # širina glavne mape u pikselima (viewBox)
TOL = 0.6  # tolerancija uprošćavanja u pikselima


def granice():
    """Administrativne granice iz Geofabrik izvoda (osm_granice.py): {id: {"id","tags","rings"}}; prstenovi su (lon, lat)."""
    if not GRANICE.exists():
        raise SystemExit("Nema _osm_cache/granice.json; prvo pokreni: python osm_granice.py")
    return {e["id"]: e for e in json.loads(GRANICE.read_text(encoding="utf-8"))["elements"]}


def dp(pts, tol):
    """Douglas–Peucker (iterativno)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1e-12
        best, bi = -1, -1
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / L
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


def opstine(data):
    """Relacija i geometrija za svaku opštinu iz DATA: (pick {opština: [id]}, G {id: prstenovi}, kosovo, missing)."""
    GR = granice()
    tags = [e for e in GR.values() if e["tags"].get("admin_level") in ("6", "7", "8")]
    by_name = {}
    for e in tags:
        t = e["tags"]
        for k in ("name:sr", "name"):
            if t.get(k):
                by_name.setdefault(t[k].strip().lower(), []).append(e)  # npr. „Црвени Крст“ / „Црвени крст“
    kosovo = [e for e in tags if e["tags"].get("admin_level") == "6" and str(e["tags"].get("name", "")).startswith("Komuna e")]

    pick = {}
    for name, _ in data["opstine"]:
        base = re.sub(r"^(Градска општина|Општина|Град)\s+", "", re.sub(r"\s*\(.*\)$", "", name)).strip()
        # prvo zvanični naziv; samo ime („Трстеник“) može biti i selo istog imena
        wanted = [POSEBNO[name]] if name in POSEBNO else [name, "Град " + base, "Општина " + base, "Градска општина " + base] if re.match(r"(Град|Општина|Градска општина) ", name) else ["Општина " + base, "Град " + base, "Градска општина " + base, name]
        c = []
        for w in wanted:
            c += [e for e in by_name.get(w.lower(), []) if e not in c]
        if c:
            pick[name] = [e["id"] for e in c]
    ids = sorted({i for v in pick.values() for i in v} | {e["id"] for e in kosovo} |
                 set())
    G = {i: [[tuple(p) for p in r] for r in GR[i]["rings"]] for i in ids if i in GR}

    def centroid(i):
        pts = [p for r in G.get(i, []) for p in r]
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else (0, 0)
    # Palilula (Beograd/Niš) i slični duplikati: po položaju
    for name, c in pick.items():
        c = [i for i in c if G.get(i)]
        if len(c) > 1 and "Палилула" in name:
            c.sort(key=lambda i: -centroid(i)[1] if "Београд" in name else centroid(i)[1])
        pick[name] = c[:1]
    missing = [n for n, c in pick.items() if not c] + [n for n, _ in data["opstine"] if n not in pick]
    return pick, G, kosovo, missing, centroid


def main():
    html = HTML.read_text(encoding="utf-8")
    data = json.loads(re.search(r"^const DATA=(.*);\r?$", html, re.M).group(1))
    pick, G, kosovo, missing, centroid = opstine(data)

    # projekcija: x = lon·cos 44°, y = −lat; glavna mapa W px
    k = math.cos(math.radians(44))
    shown = {c[0] for c in pick.values() if c} | {e["id"] for e in kosovo}
    allp = [p for i in shown for r in G.get(i, []) for p in r]
    minx, maxx = min(p[0] for p in allp) * k, max(p[0] for p in allp) * k
    miny, maxy = min(-p[1] for p in allp), max(-p[1] for p in allp)
    s = W / (maxx - minx)
    H = round((maxy - miny) * s)

    def path(rs, sc, ox, oy, tol):
        out = []
        for r in rs:
            q = [((p[0] * k - ox) * sc, (-p[1] - oy) * sc) for p in r]
            h = len(q) // 2  # zatvoren prsten: prva = poslednja tačka, pa se uprošćava po polovinama
            pts = dp(q[:h + 1], tol) + dp(q[h:], tol)[1:]
            if len(pts) >= 3:
                out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
        return "".join(out)

    used = {i for c in pick.values() for i in c}
    res = {"w": W, "h": H, "o": {}, "bg": [], "ins": {}}
    for name, c in pick.items():
        if c:
            res["o"][name] = path(G[c[0]], s, minx, miny, TOL)
    res["bg"] = [path(G[e["id"]], s, minx, miny, TOL) for e in kosovo if e["id"] not in used and G.get(e["id"])]
    # uvećani isečci za Beograd i Niš (gradske opštine su premale na glavnoj mapi)
    okrug = {n: data["okruzi"][o] for n, o in data["opstine"]}
    for key, word in (("bg", "Београд"), ("ni", "Нишав")):
        ins_ops = [n for n in pick if n.startswith("Градска општина") and pick[n] and word in okrug[n]]
        pts = [p for n in ins_ops for r in G[pick[n][0]] for p in r]
        if pts:
            ox, oy = min(p[0] for p in pts) * k, min(-p[1] for p in pts)
            sw = 300 / ((max(p[0] for p in pts) * k) - ox)
            res["ins"][key] = {"w": 300, "h": round((max(-p[1] for p in pts) - oy) * sw),
                               "o": {n: path(G[pick[n][0]], sw, ox, oy, TOL) for n in ins_ops}}
    line = "const MAPA=" + json.dumps(res, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"  # `<` u podacima ne sme da zatvori <script>
    html, n = re.subn(r"^const MAPA=.*;(?=\r?$)", lambda _: line, html, count=1, flags=re.M)
    if n != 1:
        html, n = re.subn(r"^(const PRETHODNI=.*;)(\r?\n)", lambda m: m.group(1) + m.group(2) + line + m.group(2), html, count=1, flags=re.M)
        if n != 1:
            raise SystemExit("Nema linije `const PRETHODNI=...;` u HTML-u")
    HTML.write_text(html, encoding="utf-8", newline="")
    print(f"Mapa: {len(res['o'])} opština, {len(res['bg'])} u pozadini, isečci {({k: len(v['o']) for k, v in res['ins'].items()})}; "
          f"{len(line) / 1e3:.0f} kB; bez granice: {missing}")


if __name__ == "__main__":
    main()
