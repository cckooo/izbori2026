#!/usr/bin/env python3
"""
Provera sajta u headless pregledaču: sve kartice, greške u konzoli, mobilni prikaz bez
bočnog skrolovanja (390 px), kolona Naselja i pretraga po naseljima.

    python test_sajt.py [izbori2026.html] [folder_za_snimke]
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

HTML = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("izbori2026.html")).resolve()
SHOTS = Path(sys.argv[2]) if len(sys.argv) > 2 else None
TABS = ["pregled", "okruzi", "opstine", "mesta", "statistika"]


def run(p, width, height, mobile):
    errors = []
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": width, "height": height}, is_mobile=mobile, has_touch=mobile)
    pg.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.goto(HTML.as_uri())
    pg.wait_for_timeout(800)
    overflow = {}
    for t in TABS:
        pg.click(f'nav button[data-tab="{t}"]')
        pg.wait_for_timeout(400)
        overflow[t] = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    # Opštine: izaberi opštinu koja ima naselja
    pg.click('nav button[data-tab="opstine"]')
    op = pg.evaluate("""() => { const k = Object.keys(NASELJA)[0]; return k ? OP.findIndex(o => o.full === k) : -1 }""")
    info = {"overflow": overflow}
    if op >= 0:
        pg.select_option("#fOp", str(op))
        pg.wait_for_timeout(500)
        info["nas_cells"] = pg.locator("#opSt2 td.nas").count()
        info["nas_filled"] = pg.evaluate("[...document.querySelectorAll('#opSt2 td.nas')].filter(td => !td.querySelector('.muted')).length")
        info["overflow_op"] = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        if SHOTS:
            pg.locator("#opSt2").screenshot(path=str(SHOTS / f"opst2_{width}.png"))
        # Lat/Ćir prekidač
        pg.click("#sCyr")
        pg.wait_for_timeout(300)
        info["cyr_has_cyr"] = pg.evaluate("/[а-шА-Ш]/.test(document.querySelector('#opSt2 td.nas').textContent)")
        pg.click("#sLat")
        # pretraga po naselju: uzmi reč iz prvog spiska naselja
        word = pg.evaluate("""() => { const v = Object.values(Object.values(NASELJA)[0])[0] || "";
                              const w = lat(v).split(/[ ,]+/).filter(x => x.length > 5)[0]; return w || "" }""")
        pg.click('nav button[data-tab="mesta"]')
        pg.fill("#mQ", word)
        pg.wait_for_timeout(500)
        info["search_word"] = word
        info["search_hits"] = pg.evaluate("filteredStations().length")
        info["overflow_mesta"] = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    if SHOTS:
        pg.screenshot(path=str(SHOTS / f"mesta_{width}.png"))
    b.close()
    return errors, info


with sync_playwright() as p:
    ok = True
    for w, h, mob in [(1280, 900, False), (390, 844, True)]:
        errs, info = run(p, w, h, mob)
        print(f"--- {w}px: {info}")
        for e in errs:
            print("   ", e)
        bad = [k for k, v in info.items() if k.startswith("overflow") and (max(v.values()) if isinstance(v, dict) else v) > 0]
        if errs or (w == 390 and bad):
            ok = False
    print("OK" if ok else "GREŠKE")
    sys.exit(0 if ok else 1)
