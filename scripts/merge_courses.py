"""
merge_courses.py — combine multiple parse_courses.py outputs into one file.

Usage:
    python3 merge_courses.py output.json input1.json input2.json ...

Example workflow for collecting the whole catalog:
    python3 parse_courses.py math_2027.html tmp1.json
    python3 parse_courses.py physics_2027.html tmp2.json
    python3 parse_courses.py math_2026.html tmp3.json
    ...
    python3 merge_courses.py data/courses.json tmp1.json tmp2.json tmp3.json

Courses are de-duplicated by (course_id, group_id). The same physical course
often gets listed under more than one Field of study on the site (e.g. a
seminar cross-listed between Math & CS and Chemical Sciences) — rather than
picking one and discarding the rest, each course ends up with a `fields`
array containing every field it was seen under, so filtering by any one of
them in the app still surfaces it. All other properties (title, sessions,
lecturers, etc.) come from whichever input file listed that course last,
same as before — only the field(s) are accumulated rather than overwritten.

This also transparently upgrades older data that still used a singular
`field` string instead of a `fields` array — just include the old file as
one of the inputs and it'll be converted automatically.
"""
import json
import sys


def _fields_of(course):
    """Return a course's field(s) as a list, regardless of whether it uses
    the current `fields` array or an older singular `field` string."""
    if isinstance(course.get("fields"), list):
        return [f for f in course["fields"] if f]
    if course.get("field"):
        return [course["field"]]
    return []


def merge_course_lists(course_lists):
    """Same de-dupe/field-accumulation logic as merge(), but takes already-loaded
    lists of course dicts instead of file paths — lets other scripts (e.g.
    build_courses.py) reuse it without round-tripping through temp files."""
    merged = {}  # (course_id, group_id) -> course dict, with a running `fields` list
    for courses in course_lists:
        for c in courses:
            key = (c.get("course_id"), c.get("group_id"))
            incoming_fields = _fields_of(c)

            entry = dict(c)  # this file's data wins for every property...
            entry.pop("field", None)  # ...except we always store `fields` as a list

            if key in merged:
                prior_fields = merged[key].get("fields", [])
                combined = prior_fields + [f for f in incoming_fields if f not in prior_fields]
                entry["fields"] = combined
            else:
                # de-dupe while preserving order, in case a single file ever lists the same field twice
                entry["fields"] = list(dict.fromkeys(incoming_fields))

            merged[key] = entry
    return list(merged.values())


def merge(paths):
    course_lists = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            course_lists.append(json.load(f))
    return merge_course_lists(course_lists)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 merge_courses.py output.json input1.json [input2.json ...]")
        sys.exit(1)

    out_path = sys.argv[1]
    input_paths = sys.argv[2:]

    combined = merge(input_paths)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    years = sorted(set(str(c.get("year")) for c in combined if c.get("year")))
    all_fields = sorted(set(f for c in combined for f in c.get("fields", [])))
    cross_listed = sum(1 for c in combined if len(c.get("fields", [])) > 1)

    print(f"Merged {len(input_paths)} file(s) -> {len(combined)} unique courses -> {out_path}")
    print(f"Years: {', '.join(years)}")
    print(f"Fields: {', '.join(all_fields)}")
    if cross_listed:
        print(f"{cross_listed} course(s) are cross-listed under more than one field.")
