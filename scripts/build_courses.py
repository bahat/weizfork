"""
build_courses.py — one-shot pipeline: raw/*.html + raw/*.json -> a single courses.json

Point this at the folder you've been dropping scrape-pages.js's downloads into
(default: raw/) and it:
  1. Parses every *.html page in there with parse_courses.py's logic.
  2. Merges them with merge_courses.py's logic (de-dupes by course_id/group_id,
     accumulating a `fields` list for courses cross-listed under more than one
     Field of study).
  3. Reads every *.json file in there as a points/end-date map (the
     "*_points.json" files scrape-pages.js downloads, or a wsos-points.json
     from fetch-points.js) and attaches `points`/`end_date`/`course_code`/
     `prerequisites` directly onto the matching course. `syllabus`/
     `learning_outcomes` are deliberately NOT attached from here — confirmed
     against the real site, scrape-pages.js/fetch-points.js's plain fetch()
     of a detail page can render those two fields differently (placeholder/
     incomplete) than a real page navigation does. Only refresh_details.py
     (Playwright, real navigation) is trusted for them; whatever it already
     wrote to the existing output file always carries forward untouched.
  4. Merges all of that ONTO whatever is already at the output path (if it
     exists), rather than replacing it outright — so running this with only
     e.g. 2026's raw files doesn't wipe out 2027 courses from a previous run
     just because their raw/*.html isn't sitting in the folder this time.
     A course re-scraped this run has its catalog fields (title, sessions,
     lecturers, ...) refreshed and its `fields` list unioned with what was
     already there; its points/end-date carry forward from the existing file
     unless this run's *.json data refreshes them. A course not touched by
     this run's raw/ files at all is left exactly as it was.
  5. Writes the result to a single output file.
  6. Appends one entry to update_log.json (next to the output file) describing
     what this run actually added/removed/changed — skipped if nothing did.
     Read by admin.html's "Update log" dashboard.

Only looks directly inside the given folder (not subfolders), so scratch
files you keep in e.g. raw/tmp/ are left alone.

Usage:
    python3 scripts/build_courses.py [raw_dir] [output.json]

Defaults: raw_dir="raw", output.json="data/courses.json"

Note: the live app currently reads points/end-dates from Firestore
(courseMeta), not from courses.json — attaching them here gives you one
complete offline file, but to make them visible to every visitor you still
need to import the *_points.json file(s) in the app ("Import parsed JSON"),
or run fetch-points.js and import that.
"""
import glob
import html
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs4 import BeautifulSoup
from parse_courses import parse_courses, detect_year_and_field, fill_computable_days
from merge_courses import merge_course_lists


def parse_html_files(html_paths):
    course_lists = []
    for hp in html_paths:
        with open(hp, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "lxml")
        year, field = detect_year_and_field(soup)
        courses = parse_courses(hp, field_label=field, year=year)
        print(f"  {hp}: {len(courses)} course(s) (field={field}, year={year})")
        course_lists.append(courses)
    return course_lists


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clean_detail_text(text):
    """Normalize a scraped detail-page text field (syllabus/learning_outcomes/
    prerequisites). syllabus/learning_outcomes come through as raw HTML (an
    Oracle APEX "display as HTML" item rendering a <ul><li> list or a <p>) —
    convert list items to bullet lines, <br>/</p> to line breaks, and strip
    any remaining tags; prerequisites is already plain text and passes
    through unaffected by the tag-stripping. Decodes HTML entities and
    de-indents/collapses whitespace either way. Kept raw otherwise (including
    values like "No"/"N/A") — display-level formatting belongs in the UI."""
    if not text:
        return None
    cleaned = re.sub(r"</li\s*>", "\n", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"<li[^>]*>", "• ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</p\s*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = html.unescape(cleaned).strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return "\n".join(lines) or None


def load_points_map(json_paths):
    """Merge every points/end-date JSON file into one {"pid-pprev": {...}} map.
    Later files win, except a later entry that's entirely empty/errored never
    clobbers a good one from an earlier file."""
    points = {}
    for p in json_paths:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print(f"  skipping {p} — not a points/end-date map (looks like a course-list JSON)")
            continue
        added = 0
        for key, info in data.items():
            if not isinstance(info, dict):
                continue
            has_data = info.get("points") is not None or info.get("end_date")
            if key in points and not has_data:
                continue
            points[key] = info
            added += 1
        print(f"  {p}: {added} course(s)")
    return points


def load_existing(out_path):
    if not os.path.exists(out_path):
        return []
    with open(out_path, "r", encoding="utf-8") as f:
        return json.load(f)


def key_of(c):
    return (c.get("course_id"), c.get("group_id"))


def _describe(key, c):
    return {"key": f"{key[0]}-{key[1]}", "course_code": c.get("course_code"), "title": c.get("title")}


def write_update_log(before_by_key, merged, out_path):
    """Append one entry to update_log.json (next to out_path) describing what
    this run actually changed vs. before_by_key — skipped entirely if nothing
    did. Read by admin.html's "Update log" dashboard."""
    after_by_key = {key_of(c): c for c in merged}
    added = [_describe(k, after_by_key[k]) for k in sorted(after_by_key.keys() - before_by_key.keys())]
    removed = [_describe(k, before_by_key[k]) for k in sorted(before_by_key.keys() - after_by_key.keys())]
    changed = []
    for k in sorted(before_by_key.keys() & after_by_key.keys()):
        b, a = before_by_key[k], after_by_key[k]
        diff_fields = sorted(f for f in set(b) | set(a) if b.get(f) != a.get(f))
        if diff_fields:
            entry = _describe(k, a)
            entry["fields"] = diff_fields
            changed.append(entry)

    if not (added or removed or changed):
        return

    log_path = os.path.join(os.path.dirname(out_path) or ".", "update_log.json")
    log = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            try:
                log = json.load(f)
            except json.JSONDecodeError:
                log = []
    log.append({
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "added": added,
        "removed": removed,
        "changed": changed,
    })
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"Logged {len(added)} added / {len(removed)} removed / {len(changed)} changed -> {log_path}")


def main():
    raw_dir = sys.argv[1] if len(sys.argv) > 1 else "raw"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "data/courses.json"

    html_paths = sorted(glob.glob(os.path.join(raw_dir, "*.html")))
    json_paths = sorted(glob.glob(os.path.join(raw_dir, "*.json")))

    if not html_paths:
        print(f"No .html files found in {raw_dir}/ — nothing to parse.")
        sys.exit(1)

    print(f"Found {len(html_paths)} HTML page(s) and {len(json_paths)} JSON file(s) in {raw_dir}/\n")

    print("Parsing course lists...")
    course_lists = parse_html_files(html_paths)
    fresh = merge_course_lists(course_lists)  # only what THIS run's raw/*.html covers

    existing = load_existing(out_path)
    existing_by_key = {key_of(c): c for c in existing}
    print(f"\n{len(existing)} course(s) already in {out_path}" if existing else f"\nNo existing {out_path} — starting fresh.")

    print("\nLoading points/end-date data...")
    points_map = load_points_map(json_paths)

    # Start from the existing file so courses this run's raw/ doesn't cover
    # (e.g. a different year/field scraped previously) are left untouched.
    combined_by_key = dict(existing_by_key)
    refreshed = 0
    for c in fresh:
        key = key_of(c)
        old = existing_by_key.get(key)
        entry = dict(c)  # freshly-scraped catalog fields (title, sessions, ...) win
        if old:
            refreshed += 1
            old_fields = old.get("fields", [])
            entry["fields"] = old_fields + [f for f in entry.get("fields", []) if f not in old_fields]
            # carry forward points/end-date/course_code unless this run's *.json refreshes them below
            for field in ("points", "end_date", "course_code"):
                if entry.get(field) is None and field in old:
                    entry[field] = old[field]
            # syllabus/learning_outcomes always carry forward as-is (never
            # attached from raw/*.json below) — see the attach loop for why.
            for field in ("syllabus", "learning_outcomes"):
                if field in old:
                    entry[field] = old[field]
        combined_by_key[key] = entry

    merged = list(combined_by_key.values())

    # Applied to the whole merged set (not just this run's fresh parses) so it
    # also retroactively fixes courses carried forward from a previous run.
    days_fixed = fill_computable_days(merged)

    attached = 0
    for c in merged:
        key = f"{c.get('course_id')}-{c.get('group_id')}"
        info = points_map.get(key)
        if not info:
            continue
        c["points"] = info.get("points")
        # scrape-pages.js/fetch-points.js grab these straight from innerHTML,
        # so "/" comes through HTML-escaped ("&#x2F;") — decode it.
        end_date = info.get("end_date")
        c["end_date"] = html.unescape(end_date) if end_date else None
        course_code = info.get("course_code")
        if course_code:
            c["course_code"] = html.unescape(course_code)
        # syllabus/learning_outcomes are deliberately NOT attached from here.
        # scrape-pages.js/fetch-points.js fetch the detail page with a plain
        # fetch(), which — confirmed against the real site — can render these
        # two fields differently (placeholder/incomplete content) than a real
        # page navigation does. Only refresh_details.py (Playwright, real
        # navigation) is trusted for them; see its module docstring.
        val = _clean_detail_text(info.get("prerequisites"))
        if val:
            c["prerequisites"] = val
        attached += 1

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    write_update_log(existing_by_key, merged, out_path)

    years = sorted(set(str(c.get("year")) for c in merged if c.get("year")))
    all_fields = sorted(set(f for c in merged for f in c.get("fields", [])))
    cross_listed = sum(1 for c in merged if len(c.get("fields", [])) > 1)
    untouched = len(existing_by_key) - refreshed

    print(f"\n{len(fresh)} course(s) parsed from this run's raw/*.html ({refreshed} already existed and were refreshed).")
    if untouched > 0:
        print(f"{untouched} previously-known course(s) not covered by this run's raw/ were left as-is.")
    print(f"Merged -> {len(merged)} unique courses total -> {out_path}")
    print(f"Years: {', '.join(years)}")
    print(f"Fields: {', '.join(all_fields)}")
    if cross_listed:
        print(f"{cross_listed} course(s) are cross-listed under more than one field.")
    if days_fixed:
        print(f"Computed the weekday from first_lecture for {days_fixed} session(s) that only listed a time.")
    print(f"Attached fresh points/end-date to {attached} course(s) from {len(json_paths)} JSON file(s) this run.")
    missing = sum(1 for c in merged if c.get("points") is None)
    if missing:
        print(f"  {missing} course(s) have no points data at all yet — scrape that field/year's points, or run fetch-points.js.")


if __name__ == "__main__":
    main()
