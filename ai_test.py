# -*- coding: utf-8 -*-
"""בדיקה: האם GitHub Models יכול להכריע אם שני שמות הם אותו מקום."""
import json, os, sys, urllib.request
for s in (sys.stdout, sys.stderr):
    if hasattr(s,"reconfigure"): s.reconfigure(encoding="utf-8", errors="replace")

TOKEN = os.environ["GITHUB_TOKEN"]
ENDPOINT = os.environ.get("AI_ENDPOINT", "https://models.inference.ai.azure.com/chat/completions")
MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")
PAIRS = [
    ("ויטרינה", "Vitrina", "אבן גבירול 36, תל אביב", "כן"),
    ("קאסה מאיה", "CASMAYA", "שדרות רוטשילד 24, תל אביב", "כן"),
    ("קסטה", "Cassata", "יהודה הלוי 12, תל אביב", "כן"),
    ("קורנדוג", "פרנק - נקניקיה עם כבוד", "אבן גבירול 23, תל אביב", "לא"),
    ("סמוסה", "מסעדת דלהי", "תל אביב", "לא"),
    ("במבה יבשה", "מרכז מבקרים במבה אסם", "קרית גת", "לא"),
]

def ask(ours, theirs, addr):
    prompt = (f'בכתבת אוכל הוזכר מקום בשם "{ours}". בגוגל מפות נמצא עסק בשם '
              f'"{theirs}" בכתובת {addr}. האם זה אותו מקום? '
              f'שים לב שהשם עשוי להיות בתעתיק לועזי. ענה מילה אחת: כן או לא.')
    body = json.dumps({"model": MODEL,
                       "messages": [{"role":"user","content":prompt}],
                       "temperature": 0}).encode()
    req = urllib.request.Request(ENDPOINT,
        data=body, headers={"Authorization": f"Bearer {TOKEN}",
                            "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()

ok = 0
for ours, theirs, addr, expect in PAIRS:
    try:
        a = ask(ours, theirs, addr)
        good = a.startswith(expect)
        ok += good
        print(f"{'✓' if good else '✗'} '{ours}' ~ '{theirs[:24]}' -> {a[:12]} (צפוי {expect})")
    except Exception as e:
        print(f"! שגיאה: {type(e).__name__} {str(e)[:90]}")
        break
print(f"\nדיוק: {ok}/{len(PAIRS)}")
