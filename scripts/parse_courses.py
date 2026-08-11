import re
import json
import sys
from bs4 import BeautifulSoup

DAY_MAP = {
    "Sunday": 0, "Monday": 1, "Tuesday": 2, "Wednesday": 3,
    "Thursday": 4, "Friday": 5, "Saturday": 6,
}

def parse_place_cell(td):
    """
    The PLACE cell contains one or more lines separated by <br>.
    Regular sessions look like: "Tuesday, 15:15 - 18:00, Jacob Ziskind Building, Rm 155"
    Sometimes a location is missing: "Wednesday, 13:15 - 15:00"
    A "Tutorials" sub-header (in <b>) may appear, after which subsequent lines are tutorials.
    Empty cells contain just " - ".
    """
    sessions = []
    current_type = "lecture"

    # Walk through the cell's contents, splitting on <br> tags while preserving <b> markers
    parts = []
    buf = ""
    for el in td.contents:
        if getattr(el, "name", None) == "br":
            parts.append(buf)
            buf = ""
        elif getattr(el, "name", None) == "b":
            # A bold marker like "Tutorials" - flush current buffer as its own token
            parts.append(buf)
            parts.append("::BOLD::" + el.get_text(strip=True))
            buf = ""
        else:
            buf += str(el) if not hasattr(el, "get_text") else el.get_text()
    parts.append(buf)

    for raw in parts:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("::BOLD::"):
            label = line.replace("::BOLD::", "").strip().lower()
            if "tutorial" in label:
                current_type = "tutorial"
            continue
        if line == "-":
            continue

        # Expect: "Day, HH:MM - HH:MM, Location..." (location may be absent or contain commas)
        m = re.match(
            r"^(?P<day>[A-Za-z]+),\s*(?P<start>\d{1,2}:\d{2})\s*-\s*(?P<end>\d{1,2}:\d{2})\s*(?:,\s*(?P<loc>.*))?$",
            line,
        )
        if m:
            day_name = m.group("day").strip()
            sessions.append({
                "type": current_type,
                "day_name": day_name,
                "day_index": DAY_MAP.get(day_name),
                "start": m.group("start"),
                "end": m.group("end"),
                "location": (m.group("loc") or "").strip() or None,
            })
        else:
            # Couldn't parse (e.g. "TBA, 09:00 - 11:00, ") - try a looser match
            m2 = re.match(r"^(?P<day>\S+),\s*(?P<start>\d{1,2}:\d{2})\s*-\s*(?P<end>\d{1,2}:\d{2})", line)
            if m2:
                day_name = m2.group("day").strip()
                sessions.append({
                    "type": current_type,
                    "day_name": day_name,
                    "day_index": DAY_MAP.get(day_name),
                    "start": m2.group("start"),
                    "end": m2.group("end"),
                    "location": None,
                    "note": line,
                })
            else:
                sessions.append({
                    "type": current_type,
                    "day_name": None,
                    "day_index": None,
                    "start": None,
                    "end": None,
                    "location": None,
                    "note": line,
                })
    return sessions


def parse_lecturers(td):
    text = td.get_text(separator="|", strip=True)
    parts = [p.strip() for p in text.split("|") if p.strip() and p.strip() != "-"]
    return parts


def parse_courses(html_path, field_label=None, year=None):
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    courses = []
    table = soup.find("table", class_=re.compile("uReport"))
    if table is None:
        # fallback: any table with headers PLACE
        for t in soup.find_all("table"):
            if t.find("th", id="PLACE") or t.find("td", headers="PLACE"):
                table = t
                break

    rows = table.find("tbody").find_all("tr", recursive=False) if table else []

    for row in rows:
        def _header_key(td):
            h = td.get("headers")
            if isinstance(h, list):
                return " ".join(h)
            return h
        cells = {_header_key(td): td for td in row.find_all("td", recursive=False)}
        if not cells:
            continue

        offered_by = cells.get("OFFERED_BY").get_text(strip=True) if cells.get("OFFERED_BY") else None
        title_cell = cells.get("TITLE")
        title = title_cell.get_text(strip=True) if title_cell else None

        course_id, group_id = None, None
        link = title_cell.find("a") if title_cell else None
        if link and link.get("href"):
            m = re.search(r"det\('[^']*',\s*(\d+)\s*,\s*(\d+)\s*\)", link["href"])
            if m:
                course_id, group_id = m.group(1), m.group(2)

        lecturers = parse_lecturers(cells.get("LECTURERS")) if cells.get("LECTURERS") else []
        semester = cells.get("SEMESTER").get_text(strip=True) if cells.get("SEMESTER") else None
        sessions = parse_place_cell(cells.get("PLACE")) if cells.get("PLACE") else []
        first_lecture = cells.get("FIRST_LECTURE").get_text(strip=True) if cells.get("FIRST_LECTURE") else None

        courses.append({
            "course_id": course_id,
            "group_id": group_id,
            "title": title,
            "offered_by": offered_by if offered_by and offered_by != "-" else None,
            "lecturers": lecturers,
            "semester": semester,
            "sessions": sessions,
            "first_lecture": first_lecture,
            "field": field_label,
            "year": year,
            "detail_url": f"https://erez.weizmann.ac.il/apx/r/ws1/186/30?pid={course_id}&pprev={group_id}" if course_id else None,
        })

    return courses


def parse_course_detail(html_text):
    """
    Parse a single course DETAIL page (the popup opened via det(url, pid, pprev)),
    e.g. https://erez.weizmann.ac.il/apx/r/ws1/186/30?pid=16050&pprev=0
    Extracts credit points, end date, and a few bonus fields.
    """
    def grab(pattern):
        m = re.search(pattern, html_text)
        return m.group(1).strip() if m else None

    credit_raw = grab(r'id="P30_CREDIT"[^>]*value="([^"]*)"')
    credit = None
    if credit_raw:
        try:
            credit = float(credit_raw)
        except ValueError:
            credit = None

    return {
        "course_id": grab(r'id="PID"[^>]*value="([^"]*)"'),
        "group_id": grab(r'id="PPREV"[^>]*value="([^"]*)"'),
        "points": credit,
        "course_code": grab(r'id="P30_COURSE_CODE"[^>]*>([^<]*)<'),
        "end_date": grab(r'id="P30_END_DATE"[^>]*>([^<]*)<'),
        "language": grab(r'id="P30_LANGUAGE"[^>]*>([^<]*)<'),
        "grade_type": grab(r'id="P30_GRADE_TYPE"[^>]*>([^<]*)<'),
    }


def detect_year_and_field(soup):
    """Read the currently-selected <option> in the Year/Field dropdowns straight
    from the saved page HTML, so re-scraping a different year/field just works
    without having to remember to pass CLI flags."""
    year, field = None, None
    year_sel = soup.find("select", id="P20_YEAR")
    if year_sel:
        opt = year_sel.find("option", selected=True)
        if opt and opt.get("value"):
            try:
                year = int(opt["value"])
            except ValueError:
                year = opt["value"]
    field_sel = soup.find("select", id="P20_FIELD")
    if field_sel:
        opt = field_sel.find("option", selected=True)
        if opt:
            field = opt.get_text(strip=True)
    return year, field


def detect_pagination(soup):
    """Look for Oracle APEX's 'row(s) X - Y of Z' pagination footer. Returns
    (shown, total) or (None, None) if not found. If shown < total, the saved
    page is missing rows — the report paginates via AJAX, so View Page Source
    on a later page won't show them; see README for how to grab them."""
    span = soup.find("span", class_="fielddata")
    if not span:
        return None, None
    text = span.get_text(strip=True)
    m = re.search(r"row\(s\)\s*(\d+)\s*-\s*(\d+)\s*of\s*(\d+)", text)
    if not m:
        return None, None
    shown_end, total = int(m.group(2)), int(m.group(3))
    return shown_end, total


if __name__ == "__main__":
    html_path = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/source_page.html"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/home/claude/courses.json"
    # optional overrides: python parse_courses.py in.html out.json "Field Name" 2026
    override_field = sys.argv[3] if len(sys.argv) > 3 else None
    override_year = int(sys.argv[4]) if len(sys.argv) > 4 else None

    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")
    detected_year, detected_field = detect_year_and_field(soup)

    field_label = override_field or detected_field or "Mathematics and Computer Science"
    year = override_year or detected_year or 2027

    courses = parse_courses(html_path, field_label=field_label, year=year)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(courses, f, ensure_ascii=False, indent=2)

    print(f"Parsed {len(courses)} courses (field={field_label}, year={year}) -> {out_path}")

    shown_end, total = detect_pagination(soup)
    if total is not None and shown_end < total:
        missing = total - shown_end
        print(
            f"\n⚠  This page only shows {shown_end} of {total} courses — "
            f"{missing} more are on the next page(s).\n"
            f"   Oracle APEX loads extra pages via AJAX, so 'View Page Source' after\n"
            f"   clicking Next won't capture them. Instead: click Next in the browser,\n"
            f"   then right-click the results table -> Inspect -> right-click the\n"
            f"   <table class=\"uReport uReportAlternative\"> element in DevTools ->\n"
            f"   Copy -> Copy outerHTML, and send that fragment for parsing too.\n"
            f"   Then merge both files with merge_courses.py."
        )
