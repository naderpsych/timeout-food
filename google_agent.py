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
from difflib import SequenceMatcher
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


# ============================================================
#  כלל "שם חוזר" (NAME_ECHO)
#  ------------------------------------------------------------
#  כשגוגל מציגה רשימת תוצאות במקום מקום יחיד, בודקים אם השם
#  שחיפשנו חוזר בשמות התוצאות:
#    "רולדין"  -> רולדין / רולדין רוטשילד ...  => מקום אמיתי (רשת)
#    "עוואמה"  -> The Old Man and the Sea      => לא מקום, גוגל ניחשה
#  כדי לבטל את הכלל: NAME_ECHO_ENABLED = False
# ============================================================
NAME_ECHO_ENABLED = True        # זיהוי מקומות אמיתיים — פעיל
NAME_ECHO_NEGATIVE = False      # פסילת מקומות — כבוי (לא אמין)


# מיפוי עברית -> עיצורים לטיניים, לזיהוי תעתיק (ויטרינה <-> Vitrina).
# ו' עברית היא גם עיצור (v) וגם תנועה (o/u), ולכן נבנים שני שלדים.
_HEB2LAT = {'א':'', 'ע':'', 'ה':'', 'י':'', 'ב':'b', 'ג':'g', 'ד':'d', 'ז':'s',
            'ח':'h', 'ט':'t', 'כ':'k', 'ך':'k', 'ל':'l', 'מ':'m', 'ם':'m',
            'נ':'n', 'ן':'n', 'ס':'s', 'פ':'p', 'ף':'p', 'צ':'c', 'ץ':'c',
            'ק':'k', 'ר':'r', 'ש':'s', 'ת':'t'}
_LAT_EQUIV = {'v':'b', 'f':'p', 'k':'c', 'q':'c', 'z':'s', 'w':'b', 'g':'k'}
_NOT_NAME_STARTERS = {"האם", "איך", "למה", "מה", "כמה", "מתי", "איפה", "זה", "אלה"}


def _norm_name(s):
    return re.sub(r"[^a-zא-ת0-9]+", " ", (s or "").lower()).strip()


def _skeletons(s):
    """שני שלדי עיצורים: אחד שבו ו'=v ואחד שבו היא תנועה."""
    outs = [[], []]
    for ch in _norm_name(s):
        if ch == "ו":
            outs[0].append("v"); outs[1].append("")
        elif ch in _HEB2LAT:
            outs[0].append(_HEB2LAT[ch]); outs[1].append(_HEB2LAT[ch])
        elif ch.isalpha() and ch not in "aeiouy":
            outs[0].append(ch); outs[1].append(ch)
    res = set()
    for o in outs:
        t = "".join(_LAT_EQUIV.get(c, c) for c in "".join(o))
        res.add(re.sub(r"(.)+", r"", t))   # מכווץ אותיות כפולות
    return res


def looks_like_place_name(name):
    """שם שהוא משפט ('האם הנשנוש הישראלי') אינו שם מקום."""
    words = _norm_name(name).split()
    return bool(words) and words[0] not in _NOT_NAME_STARTERS and len(words) <= 5


def name_echoes(ours, candidates):
    """האם השם שחיפשנו חוזר באחת מתוצאות גוגל — כולל תעתיק לועזי."""
    a = _norm_name(ours)
    if len(a) < 2:
        return False
    sa = _skeletons(ours)
    aw = {w for w in a.split() if len(w) > 2}
    for cand in candidates:
        b = _norm_name(cand)
        if not b:
            continue
        if a in b or b in a:
            return True
        if aw & {w for w in b.split() if len(w) > 2}:
            return True
        for x in sa:
            for y in _skeletons(cand):
                if len(x) >= 3 and (x in y or y in x):
                    return True
                if len(x) >= 3 and len(y) >= 3 and                         SequenceMatcher(None, x, y).ratio() >= 0.72:
                    return True
    return False


def scrape_place(page, query, place_name=None):
    """מחזיר dict עם מה שנמצא, או None אם גוגל חסמה."""
    url = "https://www.google.com/maps/search/" + urllib.parse.quote(query) + "?hl=he"
    page.goto(url, timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(random.randint(3000, 4500))  # כמו אדם שקורא

    body = page.inner_text("body")[:4000]
    if "/sorry/" in page.url or any(sign in body for sign in BLOCK_SIGNS):
        return None

    result = {}

    # אם גוגל הציגה רשימת תוצאות (רשת עם סניפים) — מחילים את כלל "שם חוזר"
    # ונכנסים לתוצאה התואמת, כדי שהכתובת והשעות ייקראו ממנה ולא מהרשימה.
    h1 = page.query_selector("h1")
    title = h1.inner_text().strip() if h1 else ""
    if title == "תוצאות" or not title:
        links = page.query_selector_all('a[href*="/maps/place/"]')[:10]
        names = [(el.get_attribute("aria-label") or "").strip() for el in links]
        names = [n for n in names if n]
        result["result_names"] = names
        base = place_name or query
        if NAME_ECHO_ENABLED and names:
            result["name_echo"] = name_echoes(base, names)
            if result["name_echo"]:
                for el in links:
                    label = (el.get_attribute("aria-label") or "").strip()
                    if label and name_echoes(base, [label]):
                        try:
                            el.click(timeout=5000)
                            page.wait_for_timeout(3500)
                        except Exception:
                            pass
                        break

    # השם הרשמי של העסק (נקרא אחרי כניסה לתוצאה, אם הייתה רשימה)
    h1 = page.query_selector("h1")
    title = h1.inner_text().strip() if h1 else ""
    if title and title != "תוצאות" and len(title) < 60:
        result["google_name"] = title

    el = page.query_selector('button[data-item-id="address"]')
    if el:
        addr = el.inner_text().strip().split(chr(10))[-1].strip()
        if addr:
            result["address"] = addr

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


CITY_EN = {
    "תל אביב": "tel aviv", "חיפה": "haifa", "ירושלים": "jerusalem",
    "רמת גן": "ramat gan", "גבעתיים": "givatayim", "הרצליה": "herzliya",
    "רמת השרון": "ramat hasharon", "בת ים": "bat yam", "חולון": "holon",
    "באר שבע": "beer sheva", "נתניה": "netanya", "רעננה": "raanana",
    "פתח תקווה": "petah tikva", "ראשון לציון": "rishon", "בני ברק": "bnei brak",
}


def build_query(card):
    """שם + שכונה (אם יש) + עיר. בלי לשתול 'לא צוין' בתוך החיפוש."""
    parts = [card["name"]]
    loc = card.get("location")
    if loc and loc != NOT_SPECIFIED:
        parts.append(loc)
    city = card["city"] if card["city"] != NOT_SPECIFIED else "תל אביב"
    if city not in " ".join(parts):
        parts.append(city)
    return " ".join(parts)


def city_conflicts(card, address):
    """התשובה של גוגל בעיר אחרת מזו שבכתבה = עסק אחר, לא לקחת.
    רחוב שונה באותה עיר דווקא כן מתקבל — המקום כנראה עבר."""
    if not address or card["city"] == NOT_SPECIFIED:
        return False
    addr = address.lower()
    flat = address.replace(" ", "").replace("-", "")
    if card["city"].replace(" ", "") in flat:
        return False
    en = CITY_EN.get(card["city"])
    if en and en in addr:
        return False
    # כתובת בלי שום שם עיר (רק "ישראל") — אין ראיה, לא פוסלים
    body = address.replace("ישראל", "")
    if not re.search(r"[א-ת]{3,}", body) and not any(v in addr for v in CITY_EN.values()):
        return False
    # כתובת שאינה בישראל
    return True


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
                found = scrape_place(page, query, lead["name"])
            except Exception as exc:
                print(f"  ERR {lead['name'][:22]}: {type(exc).__name__}")
                continue
            if found is None:
                blocked += 1
                print(f"  BLOCKED at {lead['name'][:22]} — עוצר, ננסה בריצה הבאה")
                break
            # תשובה מעיר אחרת = עסק אחר. מוותרים עליה ומשאירים את מידע הכתבה.
            if found.get("address") and city_conflicts(lead, found["address"]):
                print(f"  ✗   {lead['name'][:20]} (גוגל החזירה {found['address'][:26]} — עיר אחרת)")
                found = {"closed_permanently": False}

            # כלל "שם חוזר": גוגל הראתה סניפים בשם שחיפשנו — המקום אמיתי,
            # גם אם לא הצלחנו לשלוף ממנו כתובת. לא מסמנים ככישלון.
            if found.get("name_echo") and not found.get("address") and not found.get("hours"):
                for card in group:
                    card.pop("google_miss", None)
                    card["place_verified"] = "name_echo"
                print(f"  ~   {lead['name'][:20]} (אומת לפי שם חוזר, בלי פרטים)")
                continue

            if not found.get("address") and not found.get("hours"):
                # רישום הניסיון הכושל, כדי לא לחזור עליו כל ריצה
                for card in group:
                    # הצד השלילי כבוי: בבדיקה על 150 מקומות הוא פסל בטעות
                    # ~44% מסעדות אמיתיות (מתאו/Matteo, קוט/CÔTE) בגלל תעתיק.
                    # להפעלה מחדש רק אחרי שיפור ההשוואה: NAME_ECHO_NEGATIVE = True
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
