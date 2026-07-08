# -*- coding: utf-8 -*-
"""
כלי העשרה: משמש את הסוכן היומי כדי להשלים שעות/כתובת ממקורות רשת.
הסוכן (Claude) מבצע את החיפוש עצמו; הסקריפט רק מספק מועמדים וכותב תוצאות בבטחה.

  python enrich.py --list 25          # מדפיס JSON של מקומות שחסר להם מידע
  python enrich.py --apply results.json   # כותב את ההעשרות (עם שומר עיר)

מבנה results.json שהסוכן מייצר:
[
  {"id": "...", "hours": "א'-ה' 12:00-23:00", "address": "דיזנגוף 100",
   "city": "תל אביב", "source": "openinghours.co.il",
   "source_url": "https://...", "status": "open"},
  {"id": "...", "not_found": true}
]
"""
import argparse
import json
import sys
from datetime import datetime

from scraper import parse_schedule, DATA_PATH, TZ, NOT_SPECIFIED

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def needs_enrichment(c):
    if c.get("enrichment"):          # כבר טופל (נמצא או לא-נמצא) — לא חוזרים
        return False
    if not c["name"] or c["name"] == NOT_SPECIFIED or len(c["name"]) > 30:
        return False
    return c["hours"] == NOT_SPECIFIED or c["location"] == NOT_SPECIFIED


def cmd_list(n):
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    # עדיפות: מקומות "חדשים", ואז החדשים ביותר בתאריך פרסום
    cands = [c for c in data["cards"] if needs_enrichment(c)]
    cands.sort(key=lambda c: (not c["is_new"], c["published"]), reverse=False)
    cands.sort(key=lambda c: (0 if c["is_new"] else 1, ))
    out = [{"id": c["id"], "name": c["name"],
            "city": c["city"] if c["city"] != NOT_SPECIFIED else "",
            "article_title": c["article_title"]}
           for c in cands[:n]]
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_apply(path):
    results = json.loads(open(path, encoding="utf-8").read())
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in data["cards"]}
    today = datetime.now(TZ).date().isoformat()
    applied = skipped = 0

    for r in results:
        card = by_id.get(r["id"])
        if not card:
            continue
        if r.get("not_found"):
            # מסמנים "טופל, לא נמצא" כדי לא לחפש שוב מחר
            card["enrichment"] = {"not_found": True, "date": today}
            skipped += 1
            continue
        # שומר עיר: לא כותבים אם העיר שגוגל החזירה סותרת את העיר בכתבה
        card_city = card["city"]
        res_city = (r.get("city") or "").strip()
        if card_city != NOT_SPECIFIED and res_city and card_city not in res_city and res_city not in card_city:
            print(f"SKIP city mismatch: {card['name']} (כתבה={card_city}, מקור={res_city})", file=sys.stderr)
            skipped += 1
            continue
        enr = {"date": today, "source": r.get("source", "חיפוש רשת"),
               "source_url": r.get("source_url", "")}
        if r.get("hours"):
            enr["hours"] = r["hours"]
            enr["schedule"] = parse_schedule(r["hours"])
        if r.get("address"):
            enr["address"] = r["address"]
        if r.get("status") == "closed":
            enr["status"] = "closed"
        card["enrichment"] = enr
        applied += 1

    data["last_run"] = datetime.now(TZ).isoformat()
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"applied {applied}, skipped {skipped}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", type=int, metavar="N")
    ap.add_argument("--apply", metavar="results.json")
    args = ap.parse_args()
    if args.list:
        cmd_list(args.list)
    elif args.apply:
        cmd_apply(args.apply)
    else:
        ap.print_help()
