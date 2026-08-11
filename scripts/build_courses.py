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
     from fetch-points.js) and attaches `points`/`end_date`/`course_code`
     directly onto the matching course.
  4. Writes the result to a single output file.

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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs4 import BeautifulSoup
from parse_courses import parse_courses, detect_year_and_field
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
    merged = merge_course_lists(course_lists)

    print("\nLoading points/end-date data...")
    points_map = load_points_map(json_paths)

    attached = 0
    for c in merged:
        key = f"{c.get('course_id')}-{c.get('group_id')}"
        info = points_map.get(key)
        if not info:
            continue
        c["points"] = info.get("points")
        # scrape-pages.js/fetch-points.js grab end_date/course_code straight from
        # innerHTML, so "/" comes through HTML-escaped ("&#x2F;") — decode it.
        end_date = info.get("end_date")
        c["end_date"] = html.unescape(end_date) if end_date else None
        course_code = info.get("course_code")
        if course_code:
            c["course_code"] = html.unescape(course_code)
        attached += 1

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    years = sorted(set(str(c.get("year")) for c in merged if c.get("year")))
    all_fields = sorted(set(f for c in merged for f in c.get("fields", [])))
    cross_listed = sum(1 for c in merged if len(c.get("fields", [])) > 1)

    print(f"\nMerged {len(html_paths)} page(s) -> {len(merged)} unique courses -> {out_path}")
    print(f"Years: {', '.join(years)}")
    print(f"Fields: {', '.join(all_fields)}")
    if cross_listed:
        print(f"{cross_listed} course(s) are cross-listed under more than one field.")
    print(f"Attached points/end-date to {attached}/{len(merged)} courses from {len(json_paths)} JSON file(s).")
    missing = len(merged) - attached
    if missing:
        print(f"  {missing} course(s) have no points data yet — scrape that field/year's points, or run fetch-points.js.")


if __name__ == "__main__":
    main()
