#!/usr/bin/env python3
"""
Biračka mesta u inostranstvu: država, grad i koordinate grada (ručno, iz odluke RIK-a o određivanju biračkih
mesta u inostranstvu; odluka je skenirana, pa NASELJA za „Иностранство“ ima OCR šum) i mapa sveta za prikaz.

Piše:
- `const INOSTR={bm:[država, grad, napomena, x, y]};` u izbori2026.html (x, y: tačka na mapi)
- mapa_inostranstvo.json: granice država kao SVG putanje (podeli_sajt.py -> _site/inostranstvo.json, preuzima se
  tek kad se otvori Inostranstvo)

Granice: Natural Earth preko paketa world-atlas 2.0.2 (javno vlasništvo), skida se u _osm_cache/svet/.

    python inostranstvo.py
"""
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
HTML = HERE / "izbori2026.html"
CACHE = HERE / "_osm_cache" / "svet"
URL = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-{}.json"
S = 50          # tačaka po stepenu geografske širine
KX = 0.7        # sabijanje geografske dužine (≈ cos 45°)
# oblasti za prikaz [lon0, lat0, lon1, lat1]
VIEWS = {"evropa": (-11, 34, 42, 62.5), "balkan": (15.3, 41.6, 23.2, 46.1), "svet": (-128, -47, 180, 66)}
EU = (-25, 30, 50, 72)  # ovde detaljnije granice (50m), ostalo 110m

# bm: (država, grad, napomena iz odluke, širina, dužina)
A, BIH, CG, DE, US = "Аустрија", "Босна и Херцеговина", "Црна Гора", "Немачка", "САД"
M = {
    1: ("Аустралија", "Мелбурн", "", -37.81, 144.96), 2: ("Аустралија", "Сиднеј", "", -33.87, 151.21),
    3: (A, "Беч", "презимена А–Е", 48.21, 16.37), 4: (A, "Беч", "презимена Ж–М", 48.21, 16.37),
    5: (A, "Беч", "презимена Н–С", 48.21, 16.37), 6: (A, "Беч", "презимена Т–Ш", 48.21, 16.37),
    7: (A, "Салцбург", "", 47.81, 13.04), 8: (A, "Линц", "", 48.31, 14.29),
    9: ("Белгија", "Брисел", "", 50.85, 4.35),
    10: (BIH, "Сарајево", "", 43.86, 18.41), 11: (BIH, "Бања Лука", "", 44.77, 17.19), 12: (BIH, "Бања Лука", "", 44.77, 17.19),
    13: (BIH, "Бања Лука", "", 44.77, 17.19), 14: (BIH, "Мостар", "", 43.34, 17.81), 15: (BIH, "Дрвар", "", 44.37, 16.38),
    16: (BIH, "Требиње", "", 42.71, 18.34), 17: (BIH, "Брањево", "", 44.42, 19.07), 18: (BIH, "Бијељина", "", 44.76, 19.21),
    19: (BIH, "Бијељина", "", 44.76, 19.21), 20: (BIH, "Братунац", "", 44.19, 19.33), 21: (BIH, "Вишеград", "", 43.78, 19.29),
    22: (BIH, "Добој", "", 44.73, 18.09), 23: (BIH, "Зворник", "", 44.39, 19.10), 24: (BIH, "Лопаре", "", 44.64, 18.85),
    25: (BIH, "Приједор", "", 44.98, 16.71), 26: (BIH, "Рудо", "", 43.62, 19.37), 27: (BIH, "Мркоњић Град", "", 44.42, 17.08),
    28: (BIH, "Пале", "", 43.82, 18.57), 29: (BIH, "Власеница", "", 44.18, 18.94), 30: (BIH, "Соколац", "", 43.94, 18.80),
    31: (BIH, "Фоча", "", 43.51, 18.78), 32: (BIH, "Рогатица", "", 43.80, 19.00), 33: (BIH, "Модрича", "", 44.96, 18.30),
    34: (BIH, "Градишка", "", 45.15, 17.25), 35: (BIH, "Угљевик", "", 44.69, 18.99), 36: (BIH, "Брчко", "", 44.87, 18.81),
    37: (BIH, "Ново Горажде", "", 43.67, 18.95),
    38: ("Бразил", "Бразилија", "", -15.79, -47.88), 39: ("Грчка", "Атина", "", 37.98, 23.73),
    40: ("Данска", "Копенхаген", "", 55.68, 12.57),
    41: ("Индонезија", "Џакарта", "и Брунеј, Филипини, Источни Тимор, Камбоџа, Малезија, Сингапур, Тајланд, Вијетнам", -6.21, 106.85),
    42: ("Ирска", "Даблин", "", 53.39, -6.39),
    43: ("Италија", "Рим", "", 41.90, 12.50), 44: ("Италија", "Милано", "", 45.46, 9.19), 45: ("Италија", "Трст", "", 45.65, 13.78),
    46: ("Јапан", "Токио", "", 35.68, 139.69), 47: ("Јужна Африка", "Преторија", "", -25.75, 28.19),
    48: ("Канада", "Отава", "и Монтреал", 45.42, -75.70), 49: ("Канада", "Торонто", "", 43.65, -79.38),
    50: ("Кина", "Пекинг", "", 39.90, 116.41), 51: ("Кипар", "Никозија", "", 35.17, 33.36),
    52: ("Луксембург", "Луксембург", "", 49.61, 6.13), 53: ("Малта", "Малта", "", 35.90, 14.48),
    54: ("Мађарска", "Будимпешта", "", 47.50, 19.04),
    55: (DE, "Берлин", "", 52.52, 13.40), 56: (DE, "Диселдорф", "", 51.23, 6.78), 57: (DE, "Минхен", "", 48.14, 11.58),
    58: (DE, "Минхен", "", 48.14, 11.58), 59: (DE, "Штутгарт", "", 48.78, 9.18), 60: (DE, "Франкфурт", "", 50.11, 8.68),
    61: (DE, "Франкфурт", "", 50.11, 8.68), 62: (DE, "Хамбург", "", 53.55, 9.99),
    63: ("Нови Зеланд", "Окланд", "", -36.85, 174.76), 64: ("Норвешка", "Осло", "и Исланд", 59.91, 10.75),
    65: ("Пољска", "Варшава", "", 52.23, 21.01), 66: ("Португалија", "Лисабон", "", 38.72, -9.14),
    67: ("Русија", "Москва", "", 55.76, 37.62), 68: ("Русија", "Сочи", "", 43.59, 39.73),
    69: ("Северна Македонија", "Скопље", "", 42.00, 21.43), 70: ("Северна Македонија", "Куманово", "", 42.13, 21.71),
    71: (US, "Вашингтон", "и Мајами", 38.91, -77.04), 72: (US, "Чикаго", "", 41.88, -87.63),
    73: (US, "Њујорк", "и Бостон, Филаделфија", 40.76, -73.98), 74: (US, "Лос Анђелес", "и Сан Франциско, Сан Дијего, Хјустон", 34.02, -118.49),
    75: ("Словенија", "Љубљана", "презимена А–К", 46.05, 14.51), 76: ("Словенија", "Љубљана", "презимена Л–Ш", 46.05, 14.51),
    77: ("Уједињено Краљевство", "Лондон", "", 51.50, -0.13), 78: ("Финска", "Хелсинки", "", 60.17, 24.94),
    79: ("Француска", "Париз", "", 48.86, 2.35), 80: ("Француска", "Стразбур", "", 48.57, 7.75),
    81: ("Холандија", "Хаг", "", 52.08, 4.30), 82: ("Хрватска", "Загреб", "и Ријека", 45.81, 15.98),
    83: ("Хрватска", "Вуковар", "", 45.35, 19.00), 84: (CG, "Подгорица", "и Даниловград, Никшић, Плужине", 42.44, 19.26),
    85: (CG, "Сутоморе", "и Бар, Улцињ", 42.14, 19.05), 86: (CG, "Беране", "и Бијело Поље, Колашин, Андријевица", 42.84, 19.87),
    87: ("Чешка", "Праг", "", 50.08, 14.44), 88: ("Швајцарска", "Берн", "", 46.95, 7.45), 89: ("Швајцарска", "Цирих", "", 47.37, 8.54),
    90: ("Шведска", "Стокхолм", "", 59.33, 18.07), 91: ("Шведска", "Малме", "и Гетеборг", 55.60, 13.00),
    92: ("Шпанија", "Мадрид", "", 40.42, -3.70), 93: ("Шпанија", "Мадрид", "", 40.42, -3.70),
}


def xy(lon, lat):
    return round(lon * S * KX), round(-lat * S)


def topo(name):
    f = CACHE / f"countries-{name}.json"
    if not f.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_bytes(urllib.request.urlopen(URL.format(name), timeout=60).read())
    t = json.loads(f.read_text(encoding="utf-8"))
    (sx, sy), (tx, ty) = t["transform"]["scale"], t["transform"]["translate"]
    arcs = []
    for arc in t["arcs"]:  # delta kodiranje
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(ix):
        out = []
        for a in ix:
            pts = arcs[a] if a >= 0 else arcs[~a][::-1]
            out.extend(pts if not out else pts[1:])
        return out
    res = []
    for g in t["objects"]["countries"]["geometries"]:
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"] if g["type"] == "MultiPolygon" else []
        res.append((g.get("properties", {}).get("name", ""), [[ring(r) for r in p] for p in polys]))
    return res


def dp(pts, tol):
    # Douglas-Peucker; zatvoren prsten se deli na dve polovine (inače se svede na tačku)
    if len(pts) < 4:
        return pts
    def rec(a, b):
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1e-9
        best, bi = 0, -1
        for i in range(a + 1, b):
            d = abs(dy * (pts[i][0] - x1) - dx * (pts[i][1] - y1)) / n
            if d > best:
                best, bi = d, i
        return rec(a, bi)[:-1] + rec(bi, b) if best > tol else [pts[a], pts[b]]
    h = len(pts) // 2
    return rec(0, h)[:-1] + rec(h, len(pts) - 1)


def path(rings):
    out = []
    for r in rings:
        p = [xy(lon, lat) for lon, lat in r]
        q = [p[0]]
        for a in p[1:]:
            if a != q[-1]:
                q.append(a)
        if len(q) < 4:
            continue
        s = f"M{q[0][0]},{q[0][1]}"
        for (x0, y0), (x1, y1) in zip(q, q[1:]):
            s += f"l{x1 - x0},{y1 - y0}"
        out.append(s + "z")
    return "".join(out)


def in_box(rings, box):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return xs and min(xs) < box[2] and max(xs) > box[0] and min(ys) < box[3] and max(ys) > box[1]


def area(r):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1]))) / 2


def main():
    sys.setrecursionlimit(20000)
    det ={n: p for n, p in topo("50m")}
    land, home = [], []
    for name, polys in topo("110m"):
        eu = in_box([r for p in polys for r in p], EU) and name in det
        src = det[name] if eu else polys
        tol = 1.2 if eu else 8
        if name == "Antarctica":
            continue
        # prstenovi preko 180. meridijana bi na mapi bili crta preko celog sveta
        rings = [dp(r, tol / S) for p in src for r in p if area(r) > (0.004 if eu else 0.3)
                 and max(x for x, _ in r) - min(x for x, _ in r) < 180]
        (home if name in ("Serbia", "Kosovo") else land).append(path(rings))
    pts = {}
    for bm, (dr, gr, nap, lat, lon) in M.items():
        pts[str(bm)] = [dr, gr, nap, *xy(lon, lat)]
    vb = {}
    for k, (lo0, la0, lo1, la1) in VIEWS.items():
        x0, y0 = xy(lo0, la1)
        x1, y1 = xy(lo1, la0)
        vb[k] = [x0, y0, x1 - x0, y1 - y0]
    m = {"vb": vb, "s": S, "land": "".join(land), "home": "".join(home)}
    out = HERE / "mapa_inostranstvo.json"
    out.write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    line = "const INOSTR=" + json.dumps(pts, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c") + ";"
    if re.search(r"^const INOSTR=.*;$", html, re.M):
        html = re.sub(r"^const INOSTR=.*;$", lambda _: line, html, count=1, flags=re.M)
    else:
        i = html.index("const STAN=")
        html = html[:i] + "// biračka mesta u inostranstvu: država, grad, napomena, tačka na mapi (inostranstvo.py)\n" + line + "\n" + html[i:]
    HTML.write_text(html, encoding="utf-8", newline="")
    print(f"mapa_inostranstvo.json {out.stat().st_size / 1e3:.0f} kB, INOSTR {len(pts)} mesta, {len(set(v[0] for v in M.values()))} država")


if __name__ == "__main__":
    main()
