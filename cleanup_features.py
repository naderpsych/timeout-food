# -*- coding: utf-8 -*-
"""
ניקוי חד-פעמי: כתבות פיצ'ר שהפרסר הישן פירק לפי כותרות-נושא
("תשאירו מקום לקינוח") מזוהות לפי ריבוי כרטיסים בלי "אות רשימה" בכותרת,
ומפורקות מחדש עם הפרסר המתוקן.
"""
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime

from scraper import (fetch, parse_article, has_content, geocode_cards,
                     DATA_PATH, TZ)

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def list_signal(title):
    return bool(re.search(r"(?<!\d)([2-9]|1\d|2\d)(?!\d)", title)) or "מקומות" in title


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    counts = Counter(c["article_url"] for c in data["cards"])
    titles = {c["article_url"]: c["article_title"] for c in data["cards"]}

    suspects = [u for u, n in counts.items() if n > 1 and not list_signal(titles[u])]
    print(f"suspect feature-articles: {len(suspects)}")

    replaced, dropped = 0, 0
    for url in suspects:
        try:
            time.sleep(3)
            new_cards = parse_article(url, fetch(url))
            if len(new_cards) > 1:
                new_cards = [c for c in new_cards if has_content(c)]
            old_n = counts[url]
            data["cards"] = [c for c in data["cards"] if c["article_url"] != url]
            data["cards"].extend(new_cards)
            dropped += old_n - len(new_cards)
            replaced += 1
            print(f"OK {titles[url][:55]} : {old_n} -> {len(new_cards)}")
        except Exception as exc:
            print(f"FAIL {url[:60]}: {exc}", file=sys.stderr)

    geocode_cards(data["cards"], data.setdefault("geocache", {}))
    data["cards"].sort(key=lambda c: datetime.fromisoformat(c["published"]), reverse=True)
    data["last_run"] = datetime.now(TZ).isoformat()
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDONE: reparsed {replaced} articles, net card change {-dropped}, total {len(data['cards'])}")


if __name__ == "__main__":
    main()
