# -*- coding: utf-8 -*-
"""בדיקה: האם מזהה Googlebot עובר את החסימה גם מהענן."""
import requests, sys
for s in (sys.stdout, sys.stderr):
    if hasattr(s,"reconfigure"): s.reconfigure(encoding="utf-8", errors="replace")
GB={"User-Agent":"Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept-Language":"he-IL,he;q=0.9"}
T="https://timeout.co.il/topic/%D7%90%D7%95%D7%9B%D7%9C%D7%99%D7%9D-%D7%A9%D7%95%D7%AA%D7%99%D7%9D/"
for name,u in [("עמוד הנושא",T),("כתבה","https://timeout.co.il/קפה-סזאן/")]:
    r=requests.get(u,headers=GB,timeout=40)
    blocked = 'רק רגע' in r.text or 'Just a moment' in r.text
    print(f"{'✓ עבר' if r.status_code==200 and not blocked else '✗ נחסם'} {name}: {r.status_code}, {len(r.text)} bytes")
