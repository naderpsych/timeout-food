# -*- coding: utf-8 -*-
"""בדיקה חד-פעמית: איזו תצורת דפדפן עוברת את Cloudflare מהענן."""
import sys
from playwright.sync_api import sync_playwright
for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"): s.reconfigure(encoding="utf-8", errors="replace")

URL = "https://timeout.co.il/topic/%D7%90%D7%95%D7%9B%D7%9C%D7%99%D7%9D-%D7%A9%D7%95%D7%AA%D7%99%D7%9D/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
STEALTH = """Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
window.chrome={runtime:{}};
Object.defineProperty(navigator,'languages',{get:()=>['he-IL','he','en-US']});
Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"""

def attempt(name, headless, stealth, wait_s):
    with sync_playwright() as pw:
        args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        b = pw.chromium.launch(headless=headless, args=args)
        ctx = b.new_context(locale="he-IL", user_agent=UA,
                            viewport={"width": 1366, "height": 900},
                            timezone_id="Asia/Jerusalem")
        if stealth:
            ctx.add_init_script(STEALTH)
        pg = ctx.new_page()
        try:
            pg.goto(URL, timeout=70000, wait_until="domcontentloaded")
            for _ in range(wait_s // 3):
                pg.wait_for_timeout(3000)
                n = pg.eval_on_selector_all(
                    'a[href*="timeout.co.il"]',
                    "els => els.filter(e => e.textContent.trim().length > 20).length")
                if n > 3:
                    print(f"✓ {name}: עבר! {n} קישורי כתבות")
                    return True
            title = pg.title()[:40]
            print(f"✗ {name}: נחסם (כותרת: {title})")
            return False
        except Exception as e:
            print(f"✗ {name}: שגיאה {type(e).__name__}")
            return False
        finally:
            b.close()

for name, headless, stealth, wait in [
    ("headless רגיל", True, False, 9),
    ("headless + הסוואה + המתנה 20ש'", True, True, 21),
    ("דפדפן גלוי (xvfb) + הסוואה", False, True, 21),
]:
    if attempt(name, headless, stealth, wait):
        print("SUCCESS_CONFIG=" + name)
        break
