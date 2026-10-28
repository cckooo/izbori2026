#!/usr/bin/env python3
"""
Provera sajta u headless pregledaču: sve kartice u sva tri jezika (Ћир, Lat, EN), greške u konzoli,
mobilni prikaz bez bočnog skrolovanja (390 px), tabela po naseljima i pretraga po naseljima/ulicama.

    python test_sajt.py [izbori2026.html] [folder_za_snimke]
"""
import re
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

HTML = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("izbori2026.html")).resolve()
SHOTS = Path(sys.argv[2]) if len(sys.argv) > 2 else None
TABS = ["pregled", "mapa", "liste", "okruzi", "opstine", "mesta", "statistika"]
# latinične reči koje smeju da ostanu u ćiriličnom prikazu (nesrpska imena, oznake)
LAT_OK = re.compile(r"^(PDF|CSV|Lat|EN|Vajdasági|Magyar|Szövetség|Pásztor|Bálint|Shqiptar|[A-Za-z]{1,2})$")
FOREIGN = re.compile(r"[qwxyäáàâéèëíïóöőôúüűç]", re.I)


def latin_leftovers(pg):
    # elementi sa klasom keep (npr. e-mail adresa) se namerno ne preslovljavaju
    # duži tekstovi prvo (npr. e-mail pre samog naziva sajta, koji je njegov deo)
    txt = pg.evaluate("(()=>{let t=document.body.innerText;for(const e of [...document.querySelectorAll('.keep')].sort((a,b)=>b.innerText.length-a.innerText.length))"
                      "t=t.split(e.innerText).join(' ');return t})()")
    words = re.findall(r"[A-Za-zČčĆćĐđŠšŽž][A-Za-zČčĆćĐđŠšŽžÀ-ÿŐőŰű]*", txt)
    # reči sa slovima kojih nema u srpskom (npr. BLANCHARDSTOWN) sajt namerno ne preslovljava (FOREIGN u HTML-u)
    return sorted({w for w in words if not LAT_OK.match(w) and not FOREIGN.search(w)})


def run(p, width, height, mobile):
    errors, info = [], {}
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": width, "height": height}, is_mobile=mobile, has_touch=mobile)
    pg = ctx.new_page()
    pg.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.goto(HTML.as_uri())
    pg.wait_for_timeout(800)
    info["lang_default"] = pg.evaluate("document.documentElement.lang")
    for lang in ("cyr", "lat", "en"):
        pg.click(f'#lang button[data-s="{lang}"]')
        pg.wait_for_timeout(300)
        over = {}
        for t in TABS:
            pg.click(f'nav button[data-tab="{t}"]')
            pg.wait_for_timeout(350)
            over[t] = pg.evaluate(f"document.documentElement.scrollWidth - {width}")  # ne innerWidth: na telefonu se prikaz proširi
            if lang == "cyr":
                left = latin_leftovers(pg)
                if left:
                    info.setdefault("latinica_u_cyr", {})[t] = left[:15]
        # podmeniji: delovi Statistike, profila liste i izabrane opštine
        subs = [f"statistika-{s}" for s in pg.evaluate("STAT_SUB.map(x => x[0])")] + \
               [f"lista-3-{s}" for s in pg.evaluate("LSUB.map(x => x[0])")] + ["metodologija"]
        for h in subs:
            pg.evaluate(f"go('{h}')")
            pg.wait_for_timeout(350)
            over[h] = pg.evaluate(f"document.documentElement.scrollWidth - {width}")  # ne innerWidth: na telefonu se prikaz proširi
            if lang == "cyr":
                left = latin_leftovers(pg)
                if left:
                    info.setdefault("latinica_u_cyr", {})[h] = left[:15]
        for s in pg.evaluate("OSUB.map(x => x[0])"):
            pg.evaluate(f"state.okF='';state.opSearch='0';state.osub='{s}';go('opstine');viewOpstine()")
            pg.wait_for_timeout(350)
            over["opstina-" + s] = pg.evaluate(f"document.documentElement.scrollWidth - {width}")  # ne innerWidth: na telefonu se prikaz proširi
            if lang == "cyr":
                left = latin_leftovers(pg)
                if left:
                    info.setdefault("latinica_u_cyr", {})["opstina-" + s] = left[:15]
        pg.evaluate("state.opSearch='';state.osub='rezultati'")
        info[f"overflow_{lang}"] = max(over.values())
    info["tab_en"] = pg.evaluate("document.querySelector('nav button[data-tab=mesta]').textContent")
    pg.click('#lang button[data-s="cyr"]')
    pg.wait_for_timeout(300)
    # Opštine: izaberi opštinu sa naseljima -> tabela po naseljima -> klik vodi na biračka mesta
    pg.click('nav button[data-tab="opstine"]')
    op = pg.evaluate("""() => { const k = Object.keys(NASELJA).find(k => k.startsWith("Ковачица")) || Object.keys(NASELJA)[0];
                                return OP.findIndex(o => o.full === k) }""")
    pg.select_option("#fOp", str(op))
    pg.wait_for_timeout(500)
    pg.click("#opDetail .subnav button[data-sub=naselja]")  # tabela po naseljima je u delu „Po naseljima“
    pg.wait_for_timeout(400)
    info["naselja_redova"] = pg.locator("#opNas tbody tr").count()
    info["overflow_opstina"] = pg.evaluate(f"document.documentElement.scrollWidth - {width}")  # ne innerWidth: na telefonu se prikaz proširi
    if SHOTS:
        pg.locator("#opDetail").screenshot(path=str(SHOTS / f"opstina_{width}.png"))
    pg.locator("#opNas tbody tr").first.click()
    pg.wait_for_timeout(600)
    info["posle_klika"] = {"kartica": pg.evaluate("location.hash"), "mesta": pg.evaluate("filteredStations().length"),
                           "pretraga": pg.evaluate("state.m.q")}
    info["naselje_u_tabeli"] = pg.evaluate("[...document.querySelectorAll('#mTbl td.nas b')].length")
    if SHOTS:
        pg.screenshot(path=str(SHOTS / f"mesta_{width}.png"), full_page=False)
    # pretraga po ulici
    word = pg.evaluate("""() => { const v = Object.values(Object.values(NASELJA)[0]).map(x => x[1]).find(x => x) || "";
                          return lat(v).split(/[ ,]+/).filter(x => x.length > 5)[0] || "" }""")
    pg.click("#mReset")
    pg.wait_for_timeout(300)
    pg.fill("#mQ", word)
    pg.wait_for_timeout(400)
    info["pretraga"] = (word, pg.evaluate("filteredStations().length"))
    # izbor jezika se pamti
    pg.click('#lang button[data-s="en"]')
    pg.reload()
    pg.wait_for_timeout(600)
    info["zapamcen_jezik"] = pg.evaluate("document.documentElement.lang")
    b.close()
    return errors, info


src = HTML.read_text(encoding="utf-8")
if re.search(r"^(<<<<<<<|=======|>>>>>>>)", src, re.M) or src.count("\nconst DATA=") != 1:
    print("GREŠKE: git konflikt ili dupli podaci u HTML-u")
    sys.exit(1)

with sync_playwright() as p:
    ok = True
    for w, h, mob in [(1280, 900, False), (390, 844, True)]:
        errs, info = run(p, w, h, mob)
        print(f"--- {w}px: {info}")
        for e in errs:
            print("   ", e)
        over = [k for k, v in info.items() if k.startswith("overflow") and v > 0]
        if errs or (w == 390 and over) or info["lang_default"] != "sr-Cyrl" or info.get("latinica_u_cyr") \
                or not info["naselja_redova"] or info["zapamcen_jezik"] != "en":
            ok = False
    print("OK" if ok else "GREŠKE")
    sys.exit(0 if ok else 1)
