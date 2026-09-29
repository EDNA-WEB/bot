"""
Víkendový Top Box Office (USA) pre PunisherEDNA reviews.

Zdroj 1: IMDb rebríček https://www.imdb.com/chart/boxoffice/ (presne ten
         "Top box office (US)" z hlavnej stránky IMDb) — dáta z vloženého JSON.
Zdroj 2 (záloha): Box Office Mojo https://www.boxofficemojo.com/weekend/chart/
         (patrí IMDb, rovnaké čísla, obyčajná HTML tabuľka).

Výstup data.json:
{
  "source": "imdb" | "boxofficemojo",
  "updatedAt": "2026-09-29T00:00:00Z",
  "weekend": {"start": "2026-09-25", "end": "2026-09-27"},
  "items": [
    {"rank": 1, "title": "Avengers: Endgame", "year": 2019, "imdbId": "tt4154796",
     "weekendGross": 26100000, "totalGross": 884500000, "weeks": 1}
  ]
}

Pravidlá:
- Nikdy žiadny natvrdo zadaný "záložný" zoznam — ak oba zdroje zlyhajú,
  starý data.json ostane nezmenený a beh skončí chybou (GitHub pošle e-mail).
- Názvy sa sťahujú v angličtine (originálne názvy), web ich páruje
  s poľom "originálny názov" + rokom filmu vo svojej databáze.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

DATA_FILE = "data.json"
LIMIT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def fetch(url):
    """Stiahne stránku, pri chybe to skúsi ešte 2x."""
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200 and len(r.text) > 5000:
                return r.text
            last = f"HTTP {r.status_code}, {len(r.text)} znakov"
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def money(v):
    """'$26,105,000' / 26105000 / {'amount': 26105000} → 26105000 (int) alebo None."""
    if isinstance(v, dict):
        v = v.get("amount", v.get("total"))
        if isinstance(v, dict):
            v = v.get("amount")
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        digits = re.sub(r"[^\d]", "", v)
        return int(digits) if digits else None
    return None


def parse_weekend_text(text):
    """Nájde v texte napr. 'Sep 25-27, 2026' alebo 'Sep 30 - Oct 2, 2026'."""
    m = re.search(r"([A-Z][a-z]{2})[a-z]*\.? (\d{1,2})\s*[-–]\s*(?:([A-Z][a-z]{2})[a-z]*\.? )?(\d{1,2}),? (\d{4})", text)
    if not m:
        return None
    m1, d1, m2, d2, y = m.groups()
    mo1 = MONTHS.get(m1.lower()[:3])
    mo2 = MONTHS.get((m2 or m1).lower()[:3])
    if not mo1 or not mo2:
        return None
    y1 = int(y) - 1 if mo1 == 12 and mo2 == 1 else int(y)
    return {"start": f"{y1:04d}-{mo1:02d}-{int(d1):02d}", "end": f"{int(y):04d}-{mo2:02d}-{int(d2):02d}"}


# --------------------------------------------------------------------------
# Zdroj 1: IMDb chart — stránka obsahuje JSON (__NEXT_DATA__) so všetkými údajmi.
# Štruktúru prehľadávame všeobecne, aby drobné zmeny na IMDb bota nerozbili.
# --------------------------------------------------------------------------
def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def first_text(obj, keys):
    for d in walk(obj):
        for k in keys:
            v = d.get(k)
            if isinstance(v, dict) and isinstance(v.get("text"), str):
                return v["text"]
            if isinstance(v, str) and v.strip():
                return v
    return None


def from_imdb():
    html = fetch("https://www.imdb.com/chart/boxoffice/")
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        raise RuntimeError("IMDb: chýba __NEXT_DATA__")
    data = json.loads(script.string)

    items = []
    for node in walk(data):
        if "weekendGross" not in node:
            continue
        title_obj = None
        for k in ("title", "release", "titles"):
            if k in node:
                title_obj = node[k]
                break
        title_obj = title_obj if title_obj is not None else node
        title = first_text(title_obj, ["titleText", "originalTitleText"])
        original = first_text(title_obj, ["originalTitleText"])
        year = None
        for d in walk(title_obj):
            ry = d.get("releaseYear")
            if isinstance(ry, dict) and isinstance(ry.get("year"), int):
                year = ry["year"]
                break
        imdb_id = None
        for d in walk(title_obj):
            if isinstance(d.get("id"), str) and d["id"].startswith("tt"):
                imdb_id = d["id"]
                break
        if not title:
            continue
        items.append({
            "title": original or title,
            "year": year,
            "imdbId": imdb_id,
            "weekendGross": money(node.get("weekendGross")),
            "totalGross": money(node.get("lifetimeGross") or node.get("totalGross")),
            "weeks": node.get("weeksReleased") if isinstance(node.get("weeksReleased"), int) else None,
        })

    # Odstránenie duplicít a poradie podľa víkendových tržieb
    seen, unique = set(), []
    for it in items:
        key = it["imdbId"] or it["title"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    unique.sort(key=lambda x: x["weekendGross"] or 0, reverse=True)
    if len(unique) < 3:
        raise RuntimeError(f"IMDb: našlo sa len {len(unique)} filmov")

    weekend = None
    for d in walk(data):
        s, e = d.get("weekendStartDate"), d.get("weekendEndDate")
        if isinstance(s, str) and isinstance(e, str):
            weekend = {"start": s[:10], "end": e[:10]}
            break
    if not weekend:
        weekend = parse_weekend_text(soup.get_text(" "))
    return "imdb", weekend, unique[:LIMIT]


# --------------------------------------------------------------------------
# Zdroj 2: Box Office Mojo — tabuľka posledného víkendu.
# --------------------------------------------------------------------------
def from_boxofficemojo():
    html = fetch("https://www.boxofficemojo.com/weekend/chart/")
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise RuntimeError("BOM: chýba tabuľka")
    rows = table.find_all("tr")
    headers = [th.get_text(" ", strip=True).lower() for th in rows[0].find_all(["th", "td"])]

    def col(*names):
        for n in names:
            for i, h in enumerate(headers):
                if h == n or h.startswith(n):
                    return i
        return None

    i_rank, i_title, i_gross, i_total, i_weeks = col("rank"), col("release"), col("gross"), col("total gross"), col("weeks")
    if i_title is None or i_gross is None:
        raise RuntimeError(f"BOM: neznáme stĺpce {headers}")

    items = []
    for tr in rows[1:]:
        tds = tr.find_all("td")
        if len(tds) <= max(i_title, i_gross):
            continue
        title = tds[i_title].get_text(" ", strip=True)
        if not title:
            continue
        items.append({
            "rank": int(re.sub(r"\D", "", tds[i_rank].get_text()) or 0) if i_rank is not None else None,
            "title": title,
            "year": None,
            "imdbId": None,
            "weekendGross": money(tds[i_gross].get_text()),
            "totalGross": money(tds[i_total].get_text()) if i_total is not None and i_total < len(tds) else None,
            "weeks": int(re.sub(r"\D", "", tds[i_weeks].get_text()) or 0) if i_weeks is not None and i_weeks < len(tds) else None,
        })
        if len(items) >= LIMIT:
            break
    if len(items) < 3:
        raise RuntimeError(f"BOM: našlo sa len {len(items)} filmov")

    heading = " ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h4", "title"]))
    weekend = parse_weekend_text(heading) or parse_weekend_text(soup.get_text(" "))
    return "boxofficemojo", weekend, items


def main():
    result, errors = None, []
    for source in (from_imdb, from_boxofficemojo):
        try:
            result = source()
            break
        except Exception as e:  # noqa: BLE001
            errors.append(f"{source.__name__}: {e}")
            print(f"Zdroj zlyhal — {errors[-1]}")

    if not result:
        # Žiadne vymyslené dáta — starý súbor ostáva, beh sa označí ako chybný.
        print("Nepodarilo sa získať box office zo žiadneho zdroja. data.json ostáva bez zmeny.")
        sys.exit(1)

    source, weekend, items = result
    for i, it in enumerate(items, start=1):
        it["rank"] = i
    payload = {
        "source": source,
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "weekend": weekend,
        "items": items,
    }

    old = None
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
        except Exception:  # noqa: BLE001
            old = None

    # Porovnávame len samotný rebríček a víkend (nie čas stiahnutia), nech
    # nevznikajú zbytočné commity každý deň.
    if isinstance(old, dict) and old.get("items") == payload["items"] and old.get("weekend") == payload["weekend"]:
        print("Žiadna zmena v box office.")
        return

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Aktualizované ({source}), víkend {weekend}:")
    for it in items:
        print(f"  {it['rank']}. {it['title']} ({it.get('year') or '?'}) — ${it['weekendGross'] or 0:,}")


if __name__ == "__main__":
    main()
