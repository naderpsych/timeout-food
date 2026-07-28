# -*- coding: utf-8 -*-
"""
מחיל את תוצאות סוכן גוגל (enrich_patch.json) על הגרסה העדכנית של data.json.
כך אפשר לשמור גם אם מישהו אחר עדכן את הקובץ בזמן שהסוכן רץ — בלי התנגשויות.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from scraper import DATA_PATH, TZ

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

PATCH_PATH = Path(__file__).parent / "enrich_patch.json"


def main():
    if not PATCH_PATH.exists():
        print("אין טלאי להחיל")
        return
    patch = json.loads(PATCH_PATH.read_text(encoding="utf-8"))
    places = patch.get("places", {})
    if not places:
        print("הטלאי ריק")
        return

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    applied = 0
    for card in data["cards"]:
        key = f"{card['name'].strip().lower()}|{card['city']}"
        entry = places.get(key)
        if not entry:
            continue
        card["enrichment"] = entry["enrichment"]
        card["closed_permanently"] = entry["closed_permanently"]
        coords = entry.get("coords")
        if coords and card.get("lat") is None:
            card["lat"], card["lon"] = coords
            card["geo_precision"] = "address"
        applied += 1

    cache = data.setdefault("geocache", {})
    cache.update(patch.get("geocache", {}))
    data["last_google_run"] = datetime.now(TZ).isoformat()
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"הוחל על {applied} כרטיסים ({len(places)} מקומות)")


if __name__ == "__main__":
    main()
