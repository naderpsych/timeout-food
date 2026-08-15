# -*- coding: utf-8 -*-
"""
סריקה מחדש של כל הכתבות עם הפרסר הנוכחי, תוך שמירת ההעשרות מגוגל.
נועד לתקן כרטיסים שנוצרו בגרסאות ישנות של הפרסר (מקומות חסרים, שמות שגויים).
"""
import json
import sys
import time
from datetime import datetime

from scraper import fetch, parse_article, has_content, DATA_PATH, TZ

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

KEEP_FIELDS = ("enrichment", "closed_permanently", "lat", "lon", "geo_precision")


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    by_url = {}
    for card in data["cards"]:
        by_url.setdefault(card["article_url"], []).append(card)

    # שמירת העשרות לפי שם+עיר, כדי שיחולו גם על כרטיסים חדשים שייווצרו
    saved = {}
    for card in data["cards"]:
        if card.get("enrichment"):
            saved[(card["name"].strip().lower(), card["city"])] = {
                k: card.get(k) for k in KEEP_FIELDS}

    urls = sorted(by_url)
    print(f"articles: {len(urls)}, cards before: {len(data['cards'])}")
    new_all, gained, lost = [], 0, 0

    for i, url in enumerate(urls, 1):
        old = by_url[url]
        try:
            time.sleep(2.5)
            fresh = parse_article(url, fetch(url))
            if len(fresh) > 1:
                fresh = [c for c in fresh if has_content(c)]
            if not fresh:
                # הפרסר החליט שזו לא כתבת המלצה — מכבדים את ההחלטה
                lost += len(old)
                print(f"{i}/{len(urls)} {len(old)}->0 (סונן)")
                continue
            for card in fresh:
                keep = saved.get((card["name"].strip().lower(), card["city"]))
                if keep:
                    for k, v in keep.items():
                        if v is not None:
                            card[k] = v
            new_all.extend(fresh)
            diff = len(fresh) - len(old)
            gained += max(diff, 0)
            lost += max(-diff, 0)
            if diff:
                print(f"{i}/{len(urls)} {len(old)}->{len(fresh)} ({diff:+d})")
        except Exception as exc:
            print(f"{i}/{len(urls)} FAIL {exc}", file=sys.stderr)
            new_all.extend(old)  # נכשל — משאירים את מה שהיה

    new_all.sort(key=lambda c: datetime.fromisoformat(c["published"]), reverse=True)
    data["cards"] = new_all
    data["last_run"] = datetime.now(TZ).isoformat()
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    enriched = sum(1 for c in new_all if c.get("enrichment"))
    print(f"\nDONE: {len(new_all)} cards (+{gained}/-{lost}), enrichment kept on {enriched}")


if __name__ == "__main__":
    main()
