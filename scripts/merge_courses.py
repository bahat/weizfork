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

Courses are de-duplicated by (course_id, group_id) — if the same course
appears in two files, the later file in the argument list wins.
"""
import json
import sys


def merge(paths):
    merged = {}
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            courses = json.load(f)
        for c in courses:
            key = (c.get("course_id"), c.get("group_id"))
            merged[key] = c
    return list(merged.values())


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
    fields = sorted(set(c.get("field") for c in combined if c.get("field")))
    print(f"Merged {len(input_paths)} file(s) -> {len(combined)} unique courses -> {out_path}")
    print(f"Years: {', '.join(years)}")
    print(f"Fields: {', '.join(fields)}")
