# -*- coding: utf-8 -*-
"""
סורק המלצות אוכל מ-TimeOut ישראל.
מושך כתבות מעמוד הנושא "אוכלים-שותים", מפצל כל כתבה לכרטיס-לכל-מקום,
ומחלץ פרטים (סוג, מה לאכול, שעות, מיקום) בעזרת חוקים ולקסיקונים — בלי AI.
כותב docs/data.json. שימוש אישי בלבד; קישור חזרה לכתבה המקורית בכל כרטיס.
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# קונסולת Windows לא תמיד תומכת בעברית — נכריח UTF-8 בפלט
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

TOPIC_URL = "https://timeout.co.il/topic/%D7%90%D7%95%D7%9B%D7%9C%D7%99%D7%9D-%D7%A9%D7%95%D7%AA%D7%99%D7%9D/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "he-IL,he;q=0.9",
}
TZ = ZoneInfo("Asia/Jerusalem")
DATA_PATH = Path(__file__).parent / "docs" / "data.json"
REQUEST_DELAY_SEC = 3  # נימוס: השהיה בין בקשות
MAX_NEW_ARTICLES_PER_RUN = 25

# ---------- לקסיקונים ----------

# מילת מפתח -> סוג מקום (הסדר קובע עדיפות: הראשון שנמצא מנצח).
# ההתאמה על גבול-מילה (לא בתוך מילה אחרת, למשל "בר" לא ייתפס בתוך "כבר").
TYPE_KEYWORDS = [
    ("בית קפה", "בית קפה"), ("בית הקפה", "בית קפה"), ("קפה ומאפה", "בית קפה"),
    ("מאפייה", "מאפייה"), ("מאפיה", "מאפייה"), ("בייקרי", "מאפייה"),
    ("קונדיטוריה", "קונדיטוריה"),
    ("גלידריה", "גלידריה"), ("גלידרייה", "גלידריה"),
    ("בר יין", "בר יין"), ("ברי יין", "בר יין"), ("חנות יין", "חנות יין"),
    ("בר קוקטיילים", "בר"), ("בר שכונתי", "בר"), ("פאב", "בר"),
    ("פיצרייה", "פיצרייה"), ("פיצריה", "פיצרייה"), ("פיצה", "פיצרייה"),
    ("המבורגרייה", "המבורגרייה"), ("המבורגריית", "המבורגרייה"),
    ("המבורגרים", "המבורגרייה"), ("המבורגר", "המבורגרייה"), ("בורגר", "המבורגרייה"),
    ("שווארמה", "שווארמה"), ("שווארמיה", "שווארמה"),
    ("חומוסייה", "חומוסייה"), ("חומוסיה", "חומוסייה"), ("חומוס", "חומוסייה"),
    ("סטקייה", "סטקייה"), ("שיפודים", "מסעדת שיפודים"), ("גריל", "מסעדת גריל"),
    ("סושייה", "מסעדה יפנית"), ("סושי", "מסעדה יפנית"), ("ראמן", "מסעדה יפנית"),
    ("טרטוריה", "מסעדה איטלקית"), ("אוסטריה", "מסעדה איטלקית"),
    ("ביסטרו", "ביסטרו"), ("בראסרי", "ביסטרו"),
    ("דוכן", "דוכן / אוכל רחוב"), ("אוכל רחוב", "דוכן / אוכל רחוב"),
    ("פלאפל", "פלאפלייה"), ("סביח", "סביחייה"),
    ("קבב", "מסעדת קבב"), ("שניצל", "שניצלייה"),
    ("מסעדת שף", "מסעדת שף"), ("מסעדה", "מסעדה"),
    ("בר", "בר"),
]


def word_match(keyword, text):
    """התאמה על גבול מילה, כולל תחיליות נפוצות: "המסעדה", "בבר", "לפיצרייה".
    (כ' לא נכללת בתחיליות בכוונה — אחרת "כבר" היה נתפס כ"בר".)"""
    return re.search(r"(?<![א-ת])[ובל]?ה?" + re.escape(keyword) + r"(?![א-ת])", text) is not None

# שכונה/אזור -> עיר
NEIGHBORHOOD_TO_CITY = {
    "רמת אביב": "תל אביב", "נחלת בנימין": "תל אביב", "פלורנטין": "תל אביב",
    "נווה צדק": "תל אביב", "כרם התימנים": "תל אביב", "שוק הכרמל": "תל אביב",
    "שוק לוינסקי": "תל אביב", "לוינסקי": "תל אביב", "רוטשילד": "תל אביב",
    "דיזנגוף": "תל אביב", "אבן גבירול": "תל אביב", "בן יהודה": "תל אביב",
    "שדרות ירושלים": "תל אביב", "יפו": "תל אביב", "עג'מי": "תל אביב",
    "שוק הפשפשים": "תל אביב", "בלומפילד": "תל אביב", "טיילת": "תל אביב",
    "הצפון הישן": "תל אביב", "קריית המלאכה": "תל אביב", "שרונה": "תל אביב",
    "גני התערוכה": "תל אביב", "רמת החייל": "תל אביב", "התחנה המרכזית": "תל אביב",
    "כיכר המדינה": "תל אביב", "בזל": "תל אביב", "מנדרין אוריינטל": "תל אביב",
    "הדר": "חיפה", "מושבה גרמנית": "חיפה", "ואדי ניסנאס": "חיפה",
    "שוק תלפיות": "חיפה", "כרמל": "חיפה",
    "מחנה יהודה": "ירושלים", "נחלאות": "ירושלים", "ממילא": "ירושלים",
}

CITY_NAMES = [
    "תל אביב", "ת\"א", "תל-אביב", "יפו", "רמת גן", "גבעתיים", "חולון", "בת ים",
    "הרצליה", "רמת השרון", "בני ברק", "פתח תקווה", "ראשון לציון", "קריית אונו",
    "ירושלים", "חיפה", "קריות", "קריית ביאליק", "קריית מוצקין", "עכו", "נהריה",
    "באר שבע", "אשדוד", "אשקלון", "נתניה", "רעננה", "כפר סבא", "הוד השרון",
    "מודיעין", "רחובות", "נס ציונה", "זכרון יעקב", "קיסריה", "חדרה", "עפולה",
    "טבריה", "צפת", "אילת", "מצפה רמון",
]
CITY_CANON = {"ת\"א": "תל אביב", "תל-אביב": "תל אביב", "יפו": "תל אביב"}

TLV_AREA = {"תל אביב", "רמת גן", "גבעתיים", "חולון", "בת ים", "הרצליה",
            "רמת השרון", "בני ברק", "פתח תקווה", "קריית אונו", "ראשון לציון"}
HAIFA_AREA = {"חיפה", "קריות", "קריית ביאליק", "קריית מוצקין", "עכו", "נהריה"}

FOOD_WORDS = [
    "פסטה", "ניוקי", "ריזוטו", "לזניה", "פוקצ'ה", "פיצה", "קאצ'ו א פפה",
    "המבורגר", "צ'יזבורגר", "שווארמה", "פלאפל", "סביח", "חומוס", "משאווה",
    "מסבחה", "פול", "שקשוקה", "בורקס", "מלוואח", "ג'חנון", "קובה", "קבב",
    "שניצל", "שיפודים", "פרגית", "אנטריקוט", "סטייק", "צלעות", "אסאדו",
    "סושי", "ראמן", "גיוזה", "פאד תאי", "דים סאם", "פוקה", "סשימי",
    "טאקו", "בוריטו", "קסדייה", "נאצ'וס", "צ'ורוס",
    "קרואסון", "מאפה", "בריוש", "קינמון רול", "באבקה", "עוגת גבינה", "טירמיסו",
    "גלידה", "סורבה", "קנולי", "פחזנייה", "מקרון", "דונאט", "סופגנייה",
    "קפה", "אספרסו", "קורטדו", "מאצ'ה", "קקאו",
    "קוקטייל", "מרגריטה", "נגרוני", "ספריץ", "יין", "בירה", "סאקה",
    "דג", "דגים", "פירות ים", "שרימפס", "קלמרי", "טרטר", "סביצ'ה", "קרפצ'יו",
    "סלט", "צ'יפס", "טוסט", "כריך", "סנדוויץ'", "פיתה", "לאפה", "ג'בטה",
    "מעורב ירושלמי", "טחינה", "כנאפה", "בקלאווה", "מלבי", "קורנפלקס",
]

HE_MONTHS = {
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "אפריל": 4, "מאי": 5, "יוני": 6,
    "יולי": 7, "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
}

NOT_SPECIFIED = "לא צוין"


def fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


# ---------- גיאוקודינג (OpenStreetMap Nominatim, חינמי, מקס' בקשה לשנייה) ----------

GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
GEOCODE_UA = {"User-Agent": "timeout-food personal project (github.com/naderpsych/timeout-food)"}


def geo_query(card):
    """בונה שאילתת כתובת לכרטיס + רמת דיוק. None אם אין שום מיקום."""
    if card["location"] != NOT_SPECIFIED:
        city = card["city"] if card["city"] != NOT_SPECIFIED else ""
        query = ", ".join(p for p in (card["location"], city) if p)
        precision = "address" if re.search(r"\d", card["location"]) else "area"
    elif card["city"] != NOT_SPECIFIED:
        query, precision = card["city"], "city"
    else:
        return None, None
    return query + ", ישראל", precision


def geocode(query, cache):
    """מחזיר [lat, lon] או None; תוצאות נשמרות ב-cache כדי לא לחזור על בקשות."""
    if query in cache:
        return cache[query]
    time.sleep(1.1)  # מדיניות Nominatim: בקשה אחת לשנייה לכל היותר
    try:
        resp = requests.get(GEOCODE_URL, headers=GEOCODE_UA, timeout=30, params={
            "format": "json", "q": query, "countrycodes": "il",
            "limit": 1, "accept-language": "he"})
        resp.raise_for_status()
        results = resp.json()
        cache[query] = [float(results[0]["lat"]), float(results[0]["lon"])] if results else None
        return cache[query]
    except Exception as exc:
        print(f"geocode failed for {query}: {exc}", file=sys.stderr)
        return None  # שגיאה זמנית — לא שומרים ב-cache כדי לנסות שוב מחר


def geocode_cards(cards, cache):
    for card in cards:
        if card.get("lat") is not None:
            continue
        query, precision = geo_query(card)
        if not query:
            continue
        coords = geocode(query, cache)
        if coords:
            card["lat"], card["lon"] = coords
            card["geo_precision"] = precision


# ---------- חילוץ שדות מטקסט חופשי ----------

def extract_type(text, title=""):
    combined = title + " " + text
    for kw, place_type in TYPE_KEYWORDS:
        if word_match(kw, combined):
            return place_type
    return NOT_SPECIFIED


def extract_city_and_address(text, article_title=""):
    city = None
    combined = text + " " + article_title
    for name in CITY_NAMES:
        if name in combined:
            city = CITY_CANON.get(name, name)
            break
    if not city:
        for hood, hood_city in NEIGHBORHOOD_TO_CITY.items():
            if hood in combined:
                city = hood_city
                break

    # שכונה שמוזכרת — נוסיף כחלק מהמיקום גם אם יש עיר
    neighborhood = None
    for hood in NEIGHBORHOOD_TO_CITY:
        if hood in text:
            neighborhood = hood
            break

    # כתובת: "רחוב X 12" / "אבן גבירול 100" וכדומה
    address = None
    m = re.search(
        r"(?:רח'|רחוב|שד'|שדרות|דרך|כיכר|סמטת)\s+[א-ת'\"\s]{2,25}?\s\d{1,3}", text)
    if not m:
        m = re.search(r"\b([א-ת'\"]{2,15}(?:\s[א-ת'\"]{2,15}){0,2}\s\d{1,3})\s*,?\s*(?:" +
                      "|".join(CITY_NAMES[:8]) + r")", text)
    if m:
        address = m.group(0).strip().rstrip(",")

    parts = [p for p in (address, neighborhood if (neighborhood and (not address or neighborhood not in address)) else None) if p]
    location = ", ".join(parts) if parts else None
    return city or NOT_SPECIFIED, location or NOT_SPECIFIED


def extract_hours(text):
    # משפט שמכיל "שעות פתיחה" / "פתוח" + שעות או ימים
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"שעות (?:ה)?פתיחה|פתוח(?:ה|ים)?\s", sentence) or \
           re.search(r"[א-ת]['׳]\s*[-–]\s*[א-ת]['׳]", sentence):
            if re.search(r"\d{1,2}[:.]\d{2}|בבוקר|בערב|בצהריים|עד הלילה|מהצהריים|[א-ת]['׳]\s*[-–]", sentence):
                cleaned = sentence.strip()
                if 8 < len(cleaned) < 160:
                    return cleaned
    m = re.search(r"\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}", text)
    if m:
        return m.group(0)
    return NOT_SPECIFIED


# ---------- תרגום טקסט שעות למבנה ימים+שעות (לחישוב "פתוח עכשיו" באתר) ----------

DAY_TOKENS = {"א": 0, "ראשון": 0, "ב": 1, "שני": 1, "ג": 2, "שלישי": 2,
              "ד": 3, "רביעי": 3, "ה": 4, "חמישי": 4, "ו": 5, "שישי": 5,
              "ש": 6, "שבת": 6}
DAY_PAT = r"(?:יום\s+|ימי\s+)?(ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת|[אבגדהוש]['׳’])"
TIME_RANGE_PAT = r"(\d{1,2})[:.](\d{2})\s*[-–]\s*(?:(\d{1,2})[:.](\d{2})|חצות)"


def _day_num(token):
    return DAY_TOKENS.get(token.strip("'׳’"))


def _parse_days(fragment):
    days = set()
    range_pat = DAY_PAT + r"\s*[-–]\s*" + DAY_PAT
    for m in re.finditer(range_pat, fragment):
        a, b = _day_num(m.group(1)), _day_num(m.group(2))
        if a is None or b is None:
            continue
        d = a
        while True:
            days.add(d)
            if d == b:
                break
            d = (d + 1) % 7
    for m in re.finditer(DAY_PAT, re.sub(range_pat, " ", fragment)):
        d = _day_num(m.group(1))
        if d is not None:
            days.add(d)
    return days


def parse_schedule(hours_text):
    """ 'א'-ה' 11:00-23:00, ו' 12:00-17:00' -> [{days:[0..4], from, to}, ...] """
    if not hours_text or hours_text == NOT_SPECIFIED:
        return None
    segments = []
    pending_days = None
    for fragment in re.split(r"[,;]", hours_text):
        days = _parse_days(fragment)
        time_matches = list(re.finditer(TIME_RANGE_PAT, fragment))
        if time_matches:
            use_days = days or pending_days or set(range(7))
            for tm in time_matches:
                start = f"{int(tm.group(1)):02d}:{tm.group(2)}"
                end = "24:00" if tm.group(3) is None else f"{int(tm.group(3)):02d}:{tm.group(4)}"
                if int(start[:2]) > 24 or int(end[:2]) > 24:
                    continue
                # טווח בלי ימים בכלל שנראה הפוך/מוזר (מעל 18 שעות) — כנראה לא שעות פתיחה
                s_min = int(start[:2]) * 60 + int(start[3:])
                e_min = int(end[:2]) * 60 + int(end[3:])
                duration = e_min - s_min if e_min > s_min else e_min + 1440 - s_min
                if not days and not pending_days and duration > 18 * 60:
                    continue
                segments.append({"days": sorted(use_days), "from": start, "to": end})
            pending_days = None
        elif days:
            pending_days = days
    return segments or None


def extract_what_to_eat(text, dish_hint=None):
    found = [dish_hint] if dish_hint else []
    for word in FOOD_WORDS:
        if word_match(word, text) and word not in found:
            found.append(word)
        if len(found) >= 6:
            break
    return ", ".join(found) if found else NOT_SPECIFIED


# "השף יוסי שטרית", "המסעדן טל רשבסקי", "הבעלים דוד טור" -> שם פרטי + משפחה
OWNER_TRIGGER_RE = re.compile(
    r"(?:השף(?:ית)?|המסעדן(?:ית)?|הבעלים(?:\s+של[א-ת]*)?|הקונדיטור(?:ית)?|האופה|הבריסטה)"
    r"\s+([א-ת][א-ת'׳]+\s[א-ת][א-ת'׳\"״]+)")
# מילים שמעידות שלא נתפס שם אדם אלא המשך המשפט
NOT_A_NAME = {"המקום", "המסעדה", "הבר", "הקפה", "בית", "החדש", "החדשה", "הזה",
              "הוותיק", "שלה", "שלו", "כבר", "עוד", "לא", "הוא", "היא", "אשר",
              "צעיר", "מוכר", "ידוע", "לשעבר",
              # פעלים ומילים כלליות שנתפסות בטעות כשם
              "הביא", "הביאה", "ייבא", "ייבאה", "הגיע", "הגיעה", "פתח", "פתחה",
              "מגיש", "מגישה", "החליט", "החליטה", "בחר", "בחרה", "הפך", "הפכה",
              "עזב", "עזבה", "מכר", "מכרה", "כמה", "אשת", "איש", "חנות", "בעל",
              "רוצה", "רצה", "חושב", "חושבת", "מספר", "מספרת"}


def extract_owner(text):
    for m in OWNER_TRIGGER_RE.finditer(text):
        name = m.group(1)
        words = name.split()
        if any(w in NOT_A_NAME for w in words):
            continue
        return name
    return None


MONTHS_PATTERN = "|".join("ב" + m for m in HE_MONTHS)


def extract_opening_info(text):
    m = re.search(
        r"(?:נפתח(?:ה|ו)?|ייפתח|תיפתח|יפתח)\s+"
        r"(?:(?:" + MONTHS_PATTERN + r")(?:\s\d{4})?|לאחרונה|ממש לאחרונה|החודש|השבוע|בקרוב)",
        text)
    if m:
        return m.group(0)
    return None


def detect_is_new(section_text, article_title):
    signals = ["חדש", "חדשה", "חדשים", "נפתח", "נפתחה", "ייפתח", "בקרוב",
               "הגיע ל", "צצה", "צץ", "עלה לאוויר", "השיקו", "הרימו"]
    combined = article_title + " " + section_text
    return any(s in combined for s in signals)


# ---------- פירוק כתבה לכרטיסים ----------

NUMBERED_HEADING = re.compile(r"^\s*(\d{1,2})\s*[.\)]\s*(.+)$")

# כתבות "משאלות לב" על מקומות בחו"ל — לא מקומות אמיתיים בארץ, מדלגים
SKIP_TITLE_RE = re.compile(
    r"רשתות.{0,40}(ארה[\"״]ב|אמריק)|(ארה[\"״]ב|אמריק).{0,40}רשתות"
    # כתבות שמדרגות אנשים (שפים/מסעדנים) ולא מקומות
    r"|\d+\s+(שפים|שפיות|מסעדנים|מסעדניות|קונדיטורים|קונדיטוריות|אופים|אופות|בריסטות|בריסטים)")

# שורת פרטים בסוף כתבה: "שם המקום, רחוב ומספר, ימים ושעות"
DETAILS_LINE_RE = re.compile(r"^([^,.\d–\-]{2,30}),\s*[^,]{2,40}\d{1,3}")
TIME_HINT_RE = re.compile(r"\d{1,2}:\d{2}|[א-ת]['׳]\s*[-–]")


# מילים שמסמנות שנגמר שם המקום והתחיל תיאור (לחיתוך שמות שנגזרו מכותרת)
NAME_STOPWORDS = {"היא", "הוא", "הם", "מציע", "מציעה", "מציעים", "הגיע", "הגיעה",
                  "לובשת", "לובש", "ראתה", "ראה", "עכשיו", "חוזר", "חוזרת",
                  "נפתח", "נפתחה", "משיק", "משיקה", "מאיר", "מאירה", "עושה"}


def clean_name(raw):
    name = raw.strip()
    name = re.sub(r"\s*[-–|].{20,}$", "", name)  # חיתוך תת-כותרת ארוכה
    words = name.split()
    for i, w in enumerate(words):
        if w in NAME_STOPWORDS and i >= 1:
            words = words[:i]
            break
    name = " ".join(words)
    return name.strip(" ,.\"'״")


def parse_article(url, html):
    soup = BeautifulSoup(html, "html.parser")

    title_meta = soup.find("meta", attrs={"property": "og:title"})
    article_title = title_meta["content"].strip() if title_meta and title_meta.get("content") else \
        (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else url)

    if SKIP_TITLE_RE.search(article_title):
        print(f"SKIP (לא מקומות בארץ): {article_title[:60]}")
        return []

    pub_meta = soup.find("meta", attrs={"property": "article:published_time"})
    if pub_meta and pub_meta.get("content"):
        published = datetime.fromisoformat(pub_meta["content"].replace("Z", "+00:00")).astimezone(TZ)
    else:
        published = datetime.now(TZ)
    published_iso = published.isoformat()

    img_meta = soup.find("meta", attrs={"property": "og:image"})
    article_image = img_meta["content"].strip() if img_meta and img_meta.get("content") else None

    body = soup.find("article") or soup

    # כותרת חשופה (בלי מספור/קו מפריד) נחשבת שם-מקום רק בכתבת רשימה מוצהרת
    # ("3 מקומות", "41 הברים", "חדשות אוכל") — אחרת אלו כותרות נושא של כתבת פיצ'ר.
    _nums = [int(n) for n in re.findall(r"\d+", article_title)]
    is_list_article = (
        any(2 <= n <= 99 for n in _nums)
        or any(w in article_title for w in ("מקומות", "חדשות אוכל", "חדשות האוכל"))
        or bool(re.search(r"ה(מסעדות|ברים|בתי|מזללות|מעדניות|קפה)\b", article_title)))

    # איסוף מקטעים: כל כותרת h2/h3 "של מקום" פותחת מקטע; הטקסט עד הכותרת הבאה שייך אליו.
    # פורמטים נתמכים: "1. שם המקום" | "מנה מומלצת | שם המקום" | שם המקום לבדו.
    # כותרת המשנה של הכתבה מסומנת class="underline" ולכן מוחרגת.
    sections = []
    current = None
    for el in body.find_all(["h2", "h3", "p"]):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if el.name in ("h2", "h3"):
            if "underline" in (el.get("class") or []):
                current = None
                continue
            name, dish = None, None
            m = NUMBERED_HEADING.match(text)
            if m:
                name = m.group(2)
            elif "|" in text and len(text) <= 70:
                dish_part, name_part = text.split("|", 1)
                name, dish = name_part.strip(), dish_part.strip()
            elif (is_list_article and len(text) <= 45
                  and not re.search(r"[?!:,]", text) and len(text.split()) <= 4):
                name = text
            if name:
                current = {"name": clean_name(name), "dish": dish, "texts": [], "link": None}
                sections.append(current)
            else:
                current = None
        elif current is not None:
            current["texts"].append(text)
            for a in el.find_all("a", href=True):
                if "timeout.co.il" in a["href"] and current["link"] is None:
                    current["link"] = a["href"]

    # מקטע בלי טקסט בכלל = כנראה כותרת שאינה מקום
    sections = [s for s in sections if s["texts"]]

    cards = []
    if sections:
        for sec in sections:
            sec_text = " ".join(sec["texts"])
            cards.append(build_card(sec["name"], sec_text, article_title,
                                    url, published_iso, sec["link"],
                                    dish_hint=sec.get("dish"),
                                    article_image=article_image))
    else:
        # כתבה על מקום בודד. נחשבת המלצה רק אם יש "שורת פרטים" מודגשת
        # ("לבונטין 13, ראשון-חמישי, 08:00-17:00") — בלעדיה זו כתבת דעה/חדשות, מדלגים.
        paragraphs = [p.get_text(" ", strip=True) for p in body.find_all("p")]
        full_text = " ".join(paragraphs)
        if not TIME_HINT_RE.search(full_text):
            print(f"SKIP (אין שורת פרטים - לא המלצה): {article_title[:60]}")
            return []
        name = None
        # הכי אמין: שורת הפרטים בסוף הכתבה — "שם, רחוב 5, ימים ושעות"
        for ptext in reversed(paragraphs):
            if not TIME_HINT_RE.search(ptext):
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", ptext):
                if TIME_HINT_RE.search(sentence):
                    m = DETAILS_LINE_RE.match(sentence.strip())
                    if m:
                        name = m.group(1)
                        break
            if name:
                break
        if not name:
            mq = re.search(r"[\"״']([^\"״']{2,30})[\"״']", article_title)
            if mq:
                name = mq.group(1)
            elif ":" in article_title:
                after = article_title.split(":", 1)[1].strip()
                name = " ".join(after.split()[:3])
            else:
                name = article_title
        cards.append(build_card(clean_name(name), full_text, article_title,
                                url, published_iso, None,
                                article_image=article_image))
    return cards


def build_card(name, text, article_title, article_url, published_iso, details_link,
               dish_hint=None, article_image=None):
    city, location = extract_city_and_address(text, article_title)
    hours = extract_hours(text)
    opening = extract_opening_info(text)
    if city in TLV_AREA:
        region = "tlv"
    elif city in HAIFA_AREA:
        region = "haifa"
    elif city == NOT_SPECIFIED:
        region = "tlv"  # TimeOut תל אביב — ברירת מחדל כשאין אזכור עיר
    else:
        region = "rest"
    return {
        "id": f"{article_url}#{name}",
        "name": name,
        "type": extract_type(text, name),
        "what_to_eat": extract_what_to_eat(text, dish_hint=dish_hint),
        "owner": extract_owner(text),
        "hours": hours,
        "schedule": parse_schedule(hours),
        "city": city,
        "location": location,
        "region": region,
        "is_new": detect_is_new(text, article_title),
        "opening_info": opening,
        "article_title": article_title,
        "article_url": article_url,
        "article_image": article_image,
        "published": published_iso,
        "details_url": details_link,
        "lat": None,
        "lon": None,
        "geo_precision": None,
    }


# ---------- ריצה ראשית ----------

def has_content(card):
    """כרטיס בלי שום שדה אמיתי (הכל 'לא צוין') לא שווה הצגה."""
    return (any(card[k] != NOT_SPECIFIED for k in ("type", "what_to_eat", "hours", "city", "location"))
            or card["owner"] or card["opening_info"])


def collect_article_urls(topic_html):
    soup = BeautifulSoup(topic_html, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0].split("?")[0]
        if not href.startswith("https://timeout.co.il/"):
            continue
        if "/topic/" in href or "/author/" in href or href.rstrip("/") == "https://timeout.co.il":
            continue
        text = a.get_text(" ", strip=True)
        if len(text) > 20 and href not in urls:
            urls.append(href)
    return urls


def main():
    if DATA_PATH.exists():
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    else:
        data = {"cards": [], "seen_articles": [], "last_run": None}

    seen = set(data["seen_articles"])
    topic_html = fetch(TOPIC_URL)
    urls = collect_article_urls(topic_html)
    new_urls = [u for u in urls if unquote(u) not in seen][:MAX_NEW_ARTICLES_PER_RUN]
    print(f"articles on topic page: {len(urls)}, new: {len(new_urls)}")

    added = 0
    for url in new_urls:
        try:
            time.sleep(REQUEST_DELAY_SEC)
            html = fetch(url)
            cards = parse_article(url, html)
            # בכתבת רשימה: מסננים כרטיסים ריקים לגמרי (רחובות, מסלולים וכד')
            if len(cards) > 1:
                cards = [c for c in cards if has_content(c)]
            existing_ids = {c["id"] for c in data["cards"]}
            for card in cards:
                if card["id"] not in existing_ids:
                    data["cards"].append(card)
                    added += 1
            seen.add(unquote(url))
            print(f"OK {unquote(url)[:80]} -> {len(cards)} cards")
        except Exception as exc:
            print(f"FAIL {unquote(url)[:80]}: {exc}", file=sys.stderr)

    # גיאוקודינג לכרטיסים חדשים (עם מטמון כדי לא לחזור על שאילתות)
    geocache = data.setdefault("geocache", {})
    geocode_cards(data["cards"], geocache)

    data["cards"].sort(key=lambda c: datetime.fromisoformat(c["published"]), reverse=True)
    data["seen_articles"] = sorted(seen)
    data["last_run"] = datetime.now(TZ).isoformat()

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"added {added} cards, total {len(data['cards'])}")


if __name__ == "__main__":
    main()
