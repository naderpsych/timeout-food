# -*- coding: utf-8 -*-
"""
מילוי חד-פעמי של הארכיון אחורה בזמן, דרך עמודי /page/N/ של עמוד הנושא.
עוצר כשמגיעים לכתבות ישנות מתאריך היעד. שומר אחרי כל עמוד (עמיד לנפילות).
הרצה: python backfill.py 2025-07-07
"""
import json
import re
import sys
import time
from datetime import datetime
from urllib.parse import unquote

from scraper import (fetch, parse_article, has_content, geocode_cards,
                     collect_article_urls, DATA_PATH, TOPIC_URL, TZ, HE_MONTHS)

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

CUTOFF = datetime.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2025-07-07").replace(tzinfo=TZ)
START_PAGE = int(sys.argv[2]) if len(sys.argv) > 2 else 1
MAX_PAGES = 80


def fetch_retry(url, attempts=3):
    for i in range(attempts):
        try:
            return fetch(url)
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(15)
HE_DATE_RE = re.compile(r"(\d{1,2}) ב([א-ת]+) (\d{4})")


def page_dates(html):
    """כל התאריכים העבריים שמופיעים בעמוד הרשימה."""
    dates = []
    for m in HE_DATE_RE.finditer(html):
        month = HE_MONTHS.get(m.group(2))
        if month:
            dates.append(datetime(int(m.group(3)), month, int(m.group(1)), tzinfo=TZ))
    return dates


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    seen = set(data["seen_articles"])
    geocache = data.setdefault("geocache", {})
    existing_ids = {c["id"] for c in data["cards"]}
    total_added = 0

    for page in range(START_PAGE, MAX_PAGES + 1):
        page_url = TOPIC_URL if page == 1 else TOPIC_URL + f"page/{page}/"
        try:
            time.sleep(2)
            html = fetch_retry(page_url)
        except Exception as exc:
            print(f"page {page}: fetch failed ({exc}) — stopping")
            break

        dates = page_dates(html)
        if dates and max(dates) < CUTOFF:
            print(f"page {page}: newest item {max(dates).date()} < cutoff — done")
            break

        urls = [u for u in collect_article_urls(html) if unquote(u) not in seen]
        print(f"page {page}: {len(urls)} unseen articles")

        page_cards = []
        for url in urls:
            try:
                time.sleep(3)
                cards = parse_article(url, fetch_retry(url))
                if len(cards) > 1:
                    cards = [c for c in cards if has_content(c)]
                seen.add(unquote(url))
                if cards and datetime.fromisoformat(cards[0]["published"]) < CUTOFF:
                    print(f"  old ({cards[0]['published'][:10]}): {unquote(url)[:60]}")
                    continue
                for c in cards:
                    if c["id"] not in existing_ids:
                        page_cards.append(c)
                        existing_ids.add(c["id"])
                print(f"  OK {unquote(url)[:60]} -> {len(cards)}")
            except Exception as exc:
                print(f"  FAIL {unquote(url)[:60]}: {exc}", file=sys.stderr)

        if page_cards:
            geocode_cards(page_cards, geocache)
            data["cards"].extend(page_cards)
            total_added += len(page_cards)

        # שמירה אחרי כל עמוד — אם משהו נופל, לא מאבדים כלום
        data["cards"].sort(key=lambda c: datetime.fromisoformat(c["published"]), reverse=True)
        data["seen_articles"] = sorted(seen)
        data["last_run"] = datetime.now(TZ).isoformat()
        DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"page {page} saved. total cards: {len(data['cards'])} (+{total_added})")

    print(f"\nDONE. added {total_added} cards, total {len(data['cards'])}")


if __name__ == "__main__":
    main()
