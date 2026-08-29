# -*- coding: utf-8 -*-
"""
סוכן גוגל מפות: פותח דפדפן אמיתי (כרום), מחפש כל מקום שחסר לו מידע,
וקורא מהמסך את הכתובת, שעות הפתיחה לכל השבוע, והאם המקום נסגר לצמיתות.
מתנהג כמו אדם שגולש — בלי API, בלי מפתח, בלי כרטיס אשראי.
רץ ב-GitHub Actions (בענן), כך שהמחשב לא צריך להיות פתוח.

הרצה:  python google_agent.py [כמה מקומות בריצה]
"""
import json
import random
import re
import sys
import urllib.parse
from datetime import datetime

from playwright.sync_api import sync_playwright

from scraper import DATA_PATH, TZ, NOT_SPECIFIED, geocode

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

BATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 60
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

HE_DAYS = {"יום ראשון": 0, "יום שני": 1, "יום שלישי": 2, "יום רביעי": 3,
           "יום חמישי": 4, "יום שישי": 5, "יום שבת": 6}
DAY_SHORT = {0: "א'", 1: "ב'", 2: "ג'", 3: "ד'", 4: "ה'", 5: "ו'", 6: "ש'"}
TIME_RANGE = re.compile(r"(\d{1,2}:\d{2})\s*[–\-−]\s*(\d{1,2}:\d{2})")
# סימני חסימה אמיתיים בלבד (המילה "אימות" לבדה מופיעה גם בעמודים תקינים)
BLOCK_SIGNS = ("לפני שתמשיכו אל Google", "unusual traffic", "תעבורה חריגה",
               "אני לא רובוט", "I'm not a robot")


def norm_time(t):
    h, m = t.split(":")
    h = int(h)
    if h == 0:
        h = 24  # "0:00" בסוף טווח = חצות
    return f"{h:02d}:{m}"


def parse_google_hours(rows):
    """שורות כמו 'יום שישי 9:00–18:00' -> מבנה ימים+שעות + טקסט קריא."""
    segments, human = [], []
    for row in rows:
        text = row.replace("‎", " ").replace("\t", " ")
        text = re.sub(r"\s+", " ", text).strip()
        day = next((d for d in HE_DAYS if text.startswith(d)), None)
        if day is None:
            continue
        idx = HE_DAYS[day]
        if "סגור" in text:
            human.append(f"{DAY_SHORT[idx]} סגור")
            continue
        found = TIME_RANGE.findall(text)
        if not found:
            continue
        for start, end in found:
            s, e = norm_time(start), norm_time(end)
            segments.append({"days": [idx], "from": s, "to": e})
        human.append(f"{DAY_SHORT[idx]} " +
                     ", ".join(f"{norm_time(a)}-{norm_time(b)}" for a, b in found))
    return (segments or None), (", ".join(human) if human else None)


def scrape_place(page, query):
    """מחזיר dict עם מה שנמצא, או None אם גוגל חסמה."""
    url = "https://www.google.com/maps/search/" + urllib.parse.quote(query) + "?hl=he"
    page.goto(url, timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(random.randint(3000, 4500))  # כמו אדם שקורא

    body = page.inner_text("body")[:4000]
    if "/sorry/" in page.url or any(sign in body for sign in BLOCK_SIGNS):
        return None

    result = {}
    el = page.query_selector('button[data-item-id="address"]')
    if el:
        addr = el.inner_text().strip().split("\n")[-1].strip()
        if addr:
            result["address"] = addr

    # השם הרשמי של העסק בגוגל — משמש לתיקון שמות שבורים
    h1 = page.query_selector("h1")
    if h1:
        gname = h1.inner_text().strip()
        if gname and len(gname) < 60:
            result["google_name"] = gname

    # תמונת המקום — בוחרים את הגדולה ביותר, ומעלים את הרזולוציה בכתובת עצמה
    # (גוגל מקודדת את הגודל בסוף ה-URL, למשל "=w32-h32" -> "=w800-h500")
    best, best_w = None, -1
    for img in page.query_selector_all('img[src*="googleusercontent"]')[:15]:
        src = img.get_attribute("src") or ""
        if not src.startswith("http"):
            continue
        # דילוג על תמונות פרופיל של מבקרים (נתיב /a-/ או /a/) ועל אייקונים
        if "/a-/" in src or "/a/AC" in src or "/gps-proxy/" in src:
            continue
        m = re.search(r"=w(\d+)-h(\d+)", src)
        if not m:
            continue  # בלי מידות בכתובת אי אפשר לדעת אם זו תמונה אמיתית
        width, height = int(m.group(1)), int(m.group(2))
        if width < 60 or height < 60:
            continue  # אייקון זעיר
        if width > best_w:
            best, best_w = src, width
    if best:
        result["photo"] = re.sub(r"=w\d+-h\d+", "=w800-h500", best)

    # טבלת השעות מוצגת מקופלת (יום אחד) — צריך להרחיב אותה כדי לקבל שבוע מלא
    rows = []
    for selector in ('[aria-label*="שעות פעילות"]', '[jsaction*="openhours"]',
                     '[aria-label*="שעות"]'):
        try:
            for el in page.query_selector_all(selector)[:3]:
                try:
                    el.click(timeout=2500)
                    page.wait_for_timeout(900)
                except Exception:
                    continue
                rows = [r.inner_text() for r in page.query_selector_all("table tr")[:9]]
                if len(rows) >= 5:
                    break
            if len(rows) >= 5:
                break
        except Exception:
            continue
    if not rows:
        rows = [r.inner_text() for r in page.query_selector_all("table tr")[:9]]
    segments, human = parse_google_hours(rows)
    if human:
        result["hours"] = human
        result["schedule"] = segments

    result["closed_permanently"] = "סגור לצמיתות" in body
    return result


# גרסת ההעשרה: מקומות שהועשרו בגרסה ישנה יבוקרו שוב פעם אחת,
# כדי להוסיף תמונה ושם רשמי מגוגל.
ENRICH_VERSION = 3


# מרווחי ניסיון חוזר למקום שלא נמצא בגוגל: מסעדה חדשה נרשמת תוך ימים,
# דוכן זמני לא יירשם לעולם — לכן המרווח גדל בהדרגה במקום לנסות כל 6 שעות.
RETRY_DAYS = [3, 14, 30]


def _retry_due(card):
    miss = card.get("google_miss")
    if not miss:
        return True
    tries = miss.get("tries", 1)
    wait = RETRY_DAYS[min(tries, len(RETRY_DAYS)) - 1]
    try:
        last = datetime.fromisoformat(miss["last"])
    except Exception:
        return True
    return (datetime.now(TZ) - last).days >= wait


def needs_enrichment(card):
    enr = card.get("enrichment") or {}
    if enr.get("source") == "גוגל":
        return enr.get("v", 1) < ENRICH_VERSION
    if card.get("hours") != NOT_SPECIFIED and card.get("location") != NOT_SPECIFIED:
        return False
    return _retry_due(card)


def build_query(card):
    city = card["city"] if card["city"] != NOT_SPECIFIED else "תל אביב"
    return f"{card['name']} {city}"


SENTENCE_WORDS = {"של", "את", "עם", "אצל", "כדי", "היא", "הוא", "הם", "שגדלו", "חוזרים",
                  "מקווה", "מתארח", "ממשיך", "פוגש", "חוגגת", "תשנה", "מגיש", "מגישה",
                  "פותח", "פותחת", "נפתח", "מביא", "מביאה", "עושה", "הגיע", "חוזר"}


def looks_like_sentence(name):
    """שם שהוא בעצם שבר משפט מכותרת הכתבה, ולא שם מקום."""
    words = name.split()
    return len(words) >= 3 and any(w in SENTENCE_WORDS for w in words)


def addresses_match(ours, theirs):
    """האם הרחוב שחילצנו מהכתבה מופיע בכתובת של גוגל."""
    if not ours or not theirs:
        return False
    street = re.split(r"[,\d]", ours.strip())[0].strip()
    return len(street) >= 4 and street in theirs


def place_key(card):
    """אותה מסעדה מופיעה בכמה כתבות — מזהים אותה לפי שם+עיר."""
    return (card["name"].strip().lower(), card["city"])


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    # קיבוץ לפי מקום: חיפוש אחד בגוגל ממלא את כל הכרטיסים של אותה מסעדה
    groups = {}
    for card in data["cards"]:
        if needs_enrichment(card):
            groups.setdefault(place_key(card), []).append(card)
    # עדיפות: מקומות חדשים קודם, ואז מהחדש לישן
    ordered = sorted(groups.values(),
                     key=lambda g: (not any(c.get("is_new") for c in g),
                                    -max(c["published"] for c in g).__hash__()))
    ordered = sorted(ordered, key=lambda g: not any(c.get("is_new") for c in g))
    todo = ordered[:BATCH]
    print(f"unique places: {len(groups)} | this batch: {len(todo)} "
          f"(covering {sum(len(g) for g in todo)} cards)")

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    geocache = data.setdefault("geocache", {})
    filled = blocked = 0
    # "טלאי" נפרד: מאפשר להחיל את התוצאות על גרסה עדכנית של data.json
    # גם אם מישהו אחר עדכן אותה בינתיים (מונע התנגשויות git)
    patch = {}
    misses = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(locale="he-IL", timezone_id="Asia/Jerusalem",
                                  user_agent=UA, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        for group in todo:
            lead = group[0]
            query = build_query(lead)
            try:
                found = scrape_place(page, query)
            except Exception as exc:
                print(f"  ERR {lead['name'][:22]}: {type(exc).__name__}")
                continue
            if found is None:
                blocked += 1
                print(f"  BLOCKED at {lead['name'][:22]} — עוצר, ננסה בריצה הבאה")
                break
            if not found.get("address") and not found.get("hours"):
                # רישום הניסיון הכושל, כדי לא לחזור עליו כל ריצה
                for card in group:
                    miss = card.get("google_miss") or {"tries": 0}
                    miss["tries"] = miss.get("tries", 0) + 1
                    miss["last"] = datetime.now(TZ).isoformat()
                    card["google_miss"] = miss
                    misses["|".join(place_key(card))] = miss
                print(f"  -   {lead['name'][:22]} (לא נמצא, ניסיון {group[0]['google_miss']['tries']})")
                continue
            enr = {k: v for k, v in found.items() if k != "closed_permanently"}
            enr["source"] = "גוגל"
            enr["date"] = today
            enr["v"] = ENRICH_VERSION

            # תיקון שם שבור: אם השם שלנו נראה כמו שבר משפט מהכותרת,
            # ורחוב הכתובת שלנו מופיע בכתובת שגוגל החזירה — זה בוודאות אותו מקום,
            # ולכן אפשר לאמץ את השם הרשמי.
            gname = found.get("google_name")
            if gname and looks_like_sentence(lead["name"]):
                if addresses_match(lead.get("location", ""), found.get("address", "")):
                    enr["fixed_name"] = gname
            coords = None
            if found.get("address"):
                coords = geocode(found["address"] + ", ישראל", geocache)
            # אותו מידע חל על כל הכרטיסים של אותה מסעדה
            for card in group:
                card.pop("google_miss", None)
                card["enrichment"] = enr
                card["closed_permanently"] = found["closed_permanently"]
                if coords and card.get("lat") is None:
                    card["lat"], card["lon"] = coords
                    card["geo_precision"] = "address"
            key = f"{lead['name'].strip().lower()}|{lead['city']}"
            patch[key] = {"enrichment": enr,
                          "closed_permanently": found["closed_permanently"],
                          "coords": coords}
            filled += 1
            print(f"  ✓   {lead['name'][:20]} (×{len(group)}) | {found.get('address','-')[:30]} | "
                  f"{(found.get('hours') or '-')[:34]}")
        browser.close()

    data["last_google_run"] = datetime.now(TZ).isoformat()
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA_PATH.parent.parent / "enrich_patch.json").write_text(
        json.dumps({"geocache": geocache, "places": patch, "misses": misses},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")
    remaining = sum(1 for c in data["cards"] if needs_enrichment(c))
    print(f"\nfilled {filled}, blocked {blocked}, remaining {remaining}")


if __name__ == "__main__":
    main()
