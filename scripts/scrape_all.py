"""
scrape_all.py — fully automated scrape: every Year x Field combination.

Runs locally, under a real browser you control (via Playwright) — the same
thing you'd do by hand (open the catalog, set Year + Field, click Search,
paste scripts/scrape-pages.js into DevTools, repeat for every combination)
except this drives all of that for you instead of you clicking through
dozens of combinations one at a time. It doesn't touch scrape-pages.js's
logic at all: it injects that file's exact, unmodified source into the page
per combination and just catches the two files it already downloads, the
same way your browser would.

Because it's a real local browser under your own session/network, it isn't
subject to the site's robots.txt the way a remote/automated fetch would be
— same as you pasting the script into DevTools yourself, just automated.

SETUP (once):
    raw/my_env/bin/pip install playwright
    raw/my_env/bin/playwright install chromium

USAGE:
    raw/my_env/bin/python3 scripts/scrape_all.py                          # everything: every year x every field
    raw/my_env/bin/python3 scripts/scrape_all.py --latest-year             # just the newest year (for periodic re-checks)
    raw/my_env/bin/python3 scripts/scrape_all.py --list                    # see available years/fields, scrape nothing
    raw/my_env/bin/python3 scripts/scrape_all.py --years 2026,2027         # only these years (by dropdown value)
    raw/my_env/bin/python3 scripts/scrape_all.py --fields 30,40            # only these fields (by dropdown value)
    raw/my_env/bin/python3 scripts/scrape_all.py --force                   # re-scrape combos already in raw/
    raw/my_env/bin/python3 scripts/scrape_all.py --headless                # no visible browser window
    raw/my_env/bin/python3 scripts/scrape_all.py --skip-build              # scrape only, don't run build_courses.py after

WHAT IT DOES:
  1. Opens the live course catalog and reads every option currently in the
     Year and Field dropdowns — nothing hardcoded, so it stays correct as
     the site adds/removes years or fields. --latest-year narrows this to
     just the single highest year value found (the common case once you've
     already done a full historical scrape once and just want to catch
     changes to the current year).
  2. For each Year x Field combination not already sitting in raw/ (unless
     --force): selects both dropdowns, clicks Search, waits for a results
     table, then injects scrape-pages.js verbatim and saves the two files
     it downloads (the combined HTML + the points/end-dates JSON) into raw/.
  3. Once every combination is done, runs build_courses.py to merge
     everything into data/courses.json (skip with --skip-build), then
     compares the file's contents before and after and prints what
     changed — courses added, removed, or with different fields (new
     session times, updated points, etc.) — so a routine re-check tells
     you plainly whether anything on the site actually moved.

TROUBLESHOOTING:
  - If the Year dropdown never appears, you may be hitting a login page or
    a network/VPN wall the automated browser doesn't have access to — try
    without --headless and watch what actually loads.
  - If "Search" can't be found/clicked, the page may use a different label
    or control than expected — open an issue with what you see, or adjust
    click_search() below once you know the right selector.
  - Safe to re-run/interrupt: combinations already saved in raw/ are
    skipped by default, so a killed run just picks up where it left off.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
except ImportError:
    print("Playwright isn't installed in this Python environment. Run:")
    print("  raw/my_env/bin/pip install playwright")
    print("  raw/my_env/bin/playwright install chromium")
    print("...then re-run this script with that same interpreter.")
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "raw"
CATALOG_URL = "https://erez.weizmann.ac.il/apx/r/ws1/f1862681863611861860186/courses"
SCRAPE_SCRIPT_PATH = REPO_ROOT / "scripts" / "scrape-pages.js"


def safe_name(label):
    return re.sub(r"[^a-z0-9]+", "_", label or "unknown", flags=re.IGNORECASE)


def already_scraped(field_label, year_value):
    safe_field = safe_name(field_label)
    html_path = RAW_DIR / f"wsos_{safe_field}_{year_value}.html"
    points_path = RAW_DIR / f"wsos_{safe_field}_{year_value}_points.json"
    return html_path.exists() and points_path.exists()


def get_options(page, select_id):
    """Every non-empty <option> currently in a <select>, as [{value, label}]."""
    return page.eval_on_selector_all(
        f"{select_id} option",
        "opts => opts.map(o => ({value: o.value, label: o.textContent.trim()})).filter(o => o.value)",
    )


def click_search(page):
    for get_locator in (
        lambda: page.get_by_role("button", name="Search", exact=False),
        lambda: page.get_by_role("link", name="Search", exact=False),
        lambda: page.locator("text=Search").first,
    ):
        try:
            loc = get_locator()
            if loc.count() == 0:
                continue
        except Exception:
            continue
        # Found the control — click it and wait for the real navigation it
        # triggers (apex.submit() is a genuine full-page form submit, not an
        # AJAX update). Without this, a stale results table left over from a
        # previous combination's search (Oracle APEX re-renders your last
        # search on a bare page load) can satisfy a plain wait_for_selector
        # instantly, so the next step starts before the new search has
        # actually landed — confirmed by testing: caused "Execution context
        # was destroyed" once a second real navigation arrived mid-script.
        try:
            with page.expect_navigation(timeout=15000):
                loc.first.click(timeout=3000)
        except PWTimeoutError:
            print("  Warning: clicking Search didn't trigger a page navigation within 15s.")
        return True
    return False


def goto_search_page(page):
    page.goto(CATALOG_URL, wait_until="load")
    page.wait_for_selector("#P20_YEAR", timeout=20000)


def scrape_combo(page, scrape_script_source, year, field):
    print(f"\n=== {field['label']} / {year['label']} ===")
    # Clicking Search does a real full-page submit/reload (confirmed against
    # the site's actual markup: the button's onclick is apex.submit(...), a
    # genuine form POST, not an in-place AJAX update) — so the page from the
    # previous combination's search results is not the search form anymore.
    # Start every combination from a fresh load of the canonical search page.
    goto_search_page(page)
    page.select_option("#P20_YEAR", value=year["value"])
    page.select_option("#P20_FIELD", value=field["value"])

    if not click_search(page):
        print("  Could not find/click a Search control — trying anyway in case the dropdown auto-submits.")

    try:
        page.wait_for_selector("table.uReport.uReportAlternative", timeout=15000)
    except PWTimeoutError:
        print("  No results table appeared — likely 0 courses for this combination. Skipping.")
        return False

    RAW_DIR.mkdir(exist_ok=True)
    downloads = []

    def on_download(d):
        downloads.append(d)

    page.on("download", on_download)
    try:
        # evaluate() isn't reliably awaited for a multi-statement script string
        # (confirmed by testing), and large course lists take a while (the
        # script itself waits ~250ms per course while fetching points) — so
        # poll for both downloads instead of trusting evaluate() to block.
        page.evaluate(scrape_script_source)
        deadline = time.time() + 600  # up to 10 minutes for a big field/year
        while len(downloads) < 2 and time.time() < deadline:
            page.wait_for_timeout(500)
    except Exception as e:
        print(f"  scrape-pages.js failed to run: {e}")
        return False
    finally:
        page.remove_listener("download", on_download)

    if len(downloads) < 2:
        print(f"  Expected 2 downloads (html + points json), got {len(downloads)} after waiting — skipping save for this combo.")
        return False

    for d in downloads[:2]:
        dest = RAW_DIR / d.suggested_filename
        d.save_as(str(dest))
        print(f"  saved {dest.name}")
    return True


def load_courses_by_key(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {(c.get("course_id"), c.get("group_id")): c for c in data}


def diff_courses(before, after):
    """(added_keys, removed_keys, [(key, changed_field_names), ...]), all sorted."""
    before_keys, after_keys = set(before), set(after)
    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    changed = []
    for key in sorted(before_keys & after_keys):
        b, a = before[key], after[key]
        diff_fields = sorted(f for f in set(b) | set(a) if b.get(f) != a.get(f))
        if diff_fields:
            changed.append((key, diff_fields))
    return added, removed, changed


def print_diff_report(before, after, added, removed, changed, limit=20):
    if not (added or removed or changed):
        print("\ndata/courses.json is unchanged — nothing moved on the site since last time.")
        return

    def describe(key, from_map):
        c = from_map[key]
        return f"{c.get('title', '?')} ({c.get('year', '?')})"

    print(f"\ndata/courses.json changed: {len(added)} added, {len(removed)} removed, {len(changed)} modified.")
    if added:
        print(f"\n  Added ({len(added)}):")
        for key in added[:limit]:
            print(f"    + {describe(key, after)}")
        if len(added) > limit:
            print(f"    ... and {len(added) - limit} more")
    if removed:
        print(f"\n  Removed ({len(removed)}):")
        for key in removed[:limit]:
            print(f"    - {describe(key, before)}")
        if len(removed) > limit:
            print(f"    ... and {len(removed) - limit} more")
    if changed:
        print(f"\n  Modified ({len(changed)}):")
        for key, fields in changed[:limit]:
            print(f"    ~ {describe(key, after)} — changed: {', '.join(fields)}")
        if len(changed) > limit:
            print(f"    ... and {len(changed) - limit} more")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", help="Comma-separated Year dropdown VALUES to scrape (default: all)")
    parser.add_argument("--latest-year", action="store_true",
                         help="Only scrape the single highest-numbered year in the dropdown (overrides --years)")
    parser.add_argument("--fields", help="Comma-separated Field dropdown VALUES to scrape (default: all)")
    parser.add_argument("--force", action="store_true", help="Re-scrape combinations already present in raw/")
    parser.add_argument("--headless", action="store_true", help="Run without a visible browser window")
    parser.add_argument("--skip-build", action="store_true", help="Don't run build_courses.py automatically at the end")
    parser.add_argument("--list", action="store_true", help="Print available years/fields and exit, scraping nothing")
    args = parser.parse_args()

    scrape_script_source = SCRAPE_SCRIPT_PATH.read_text(encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        page = browser.new_page()
        print(f"Opening {CATALOG_URL} ...")
        try:
            goto_search_page(page)
        except PWTimeoutError:
            print("\nCould not find the Year dropdown (#P20_YEAR) on the page.")
            print("If you're being asked to log in, or this needs VPN/campus network access,")
            print("re-run without --headless so you can see what actually loaded and intervene.")
            browser.close()
            sys.exit(1)

        years = get_options(page, "#P20_YEAR")
        fields = get_options(page, "#P20_FIELD")

        if args.latest_year and years:
            def year_num(y):
                try:
                    return int(y["value"])
                except ValueError:
                    return float("-inf")
            latest = max(years, key=year_num)
            years = [latest]
            print(f"--latest-year: only checking {latest['label']!r}")
        elif args.years:
            wanted = set(args.years.split(","))
            years = [y for y in years if y["value"] in wanted]

        if args.fields:
            wanted = set(args.fields.split(","))
            fields = [f for f in fields if f["value"] in wanted]

        if args.list:
            print(f"\n{len(years)} year(s):")
            for y in years:
                print(f"  value={y['value']!r}  label={y['label']!r}")
            print(f"\n{len(fields)} field(s):")
            for f in fields:
                print(f"  value={f['value']!r}  label={f['label']!r}")
            browser.close()
            return

        print(f"Found {len(years)} year(s) x {len(fields)} field(s) = {len(years)*len(fields)} combination(s) to check.")
        scraped = skipped = failed = 0

        for field in fields:
            for year in years:
                if not args.force and already_scraped(field["label"], year["value"]):
                    print(f"  [skip] {field['label']} / {year['label']} — already in raw/")
                    skipped += 1
                    continue
                ok = scrape_combo(page, scrape_script_source, year, field)
                if ok:
                    scraped += 1
                else:
                    failed += 1
                time.sleep(1)  # be polite between searches

        browser.close()

    print(f"\nDone scraping: {scraped} combination(s) scraped, {skipped} already had data, {failed} empty/failed.")

    if args.skip_build:
        return
    if scraped == 0:
        print("Nothing new was scraped — skipping build_courses.py.")
        return

    courses_path = REPO_ROOT / "data" / "courses.json"
    before = load_courses_by_key(courses_path)

    print("\nRunning build_courses.py ...")
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_courses.py"),
         str(RAW_DIR), str(courses_path)],
        check=True,
    )

    after = load_courses_by_key(courses_path)
    added, removed, changed = diff_courses(before, after)
    print_diff_report(before, after, added, removed, changed)


if __name__ == "__main__":
    main()
