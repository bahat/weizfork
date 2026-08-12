# Project context for AI assistants

This document exists so a fresh AI session (no memory of prior conversations)
can pick up this project effectively. It covers architecture, the data
pipeline's non-obvious gotchas, decisions made and why, and the current state
of things. Read this before making changes, especially to the scraping
scripts — several of the "obvious" approaches there were tried and found
broken; the notes below explain why so you don't repeat the mistakes.

`README.md` is the user-facing setup/usage guide (GitHub Pages, Firebase
setup, how to run the scripts). This document is the internal engineering
context that doesn't belong in a setup guide.

## What this is

**WeizFork** (repo `bahat/weizfork`) — a course browser and weekly-schedule
planner for the Weizmann School of Science, built from data scraped off the
institute's public course catalog (`erez.weizmann.ac.il`, an Oracle APEX
application). Static frontend (GitHub Pages, no build step), Firebase
(Auth + Firestore) for sign-in, saved schedules, shared course points, and
reviews.

- Live site: deployed via GitHub Pages from `main`.
- Owner/admin account: `bahat.omer@gmail.com` (hardcoded as `OWNER_EMAIL` in
  `index.html`) — the only account that can edit shared course points,
  delete reviews, or use the "Import parsed JSON" panel. This is a
  **UI-level** gate only; see "Security model" below for what is and isn't
  enforced server-side.

## Repo layout

```
.
├── index.html                 the entire frontend (HTML + CSS + JS, ~1500 lines)
├── README.md                  user-facing setup guide (GitHub Pages, Firebase, data collection)
├── PROJECT_CONTEXT.md          this file
├── data/
│   └── courses.json           the course dataset the live app fetches at runtime
└── scripts/
    ├── parse_courses.py        HTML page -> list of course dicts
    ├── merge_courses.py        combine multiple parse_courses.py outputs, de-dupe, accumulate `fields`
    ├── build_courses.py        one-shot: raw/*.html + raw/*.json -> data/courses.json (see below)
    ├── scrape_all.py           Playwright: drives the real site through every Year x Field combo
    ├── refresh_details.py      Playwright: re-fetches every known course's detail page (points/syllabus/etc.)
    ├── scrape-pages.js         browser-console script: paginate + fetch points for the CURRENT search
    └── fetch-points.js         browser-console script: bulk-refresh points for the whole known catalog

raw/            scratch: scraped HTML + points JSON files, gitignored except raw/my_env
raw/my_env/     a Python venv with bs4 + playwright installed — use this to run the Python scripts
```

`raw/` and `tmp/` are gitignored. `raw/my_env` is a real venv checked in by
the user with dependencies already installed; prefer
`raw/my_env/bin/python3` over bare `python3` for the scripts here, since the
system Python typically won't have `bs4`/`playwright`.

## Data model (`data/courses.json`)

A flat JSON array of course objects. Each course:

```jsonc
{
  "course_id": "15837",        // pid, from the site's own course ID
  "group_id": "15600",         // pprev, from the site's own group ID
  "title": "Midrasha on groups B",
  "offered_by": "Mathematics and Computer Science",  // single dept, from the list page
  "lecturers": ["Dr. Guy Salomon", "Prof. Alexander Lubotzky"],
  "semester": "1st" | "2nd" | "Full Year",
  "sessions": [
    {
      "type": "lecture" | "tutorial",
      "day_name": "Monday", "day_index": 1,   // Sunday=0..Saturday=6
      "start": "14:15", "end": "16:00",
      "location": "Goldsmith, room 108",
      // OR, if the day/time couldn't be parsed/computed:
      "day_name": null, "day_index": null, "start": null, "end": null,
      "note": "the raw unparsed text, shown in the UI instead of guessing"
    }
  ],
  "first_lecture": "08/03/2027",   // dd/mm/yyyy
  "year": 2027,
  "detail_url": "https://erez.weizmann.ac.il/apx/r/ws1/186/30?pid=15837&pprev=15600",
  "fields": ["Mathematics and Computer Science"],  // ALL fields this course is cross-listed under (see below)
  "points": 2.0,
  "end_date": "21/06/2027",
  "course_code": "20274042",
  "prerequisites": "No",           // or real text; "No"/"N/A"/"None"/"-" normalized to "None" in the UI only
  "syllabus": "• Linear Groups,\n• Ergodic Theory,\n...",   // bulleted, from an HTML <ul><li> on the site
  "learning_outcomes": "Upon successful completion..."       // from an HTML <p> on the site
}
```

`courseKey(c)` throughout the frontend = `${course_id}-${group_id}` — this is
the canonical ID used for Firestore doc IDs, `selected` Map keys, points-map
keys, etc.

**`fields` vs `offered_by`**: a course can appear under multiple Fields of
Study on the site (cross-listing). `offered_by` is the single department from
the course-LIST page's own column; `fields` is the accumulated array of every
Field of Study the course was seen under across every scraped page, built by
`merge_courses.py`. ~55% of courses are cross-listed under 2+ fields. Always
filter/display by `fields` (array membership), never by a singular `field`.

**Custom/personal events** created in the app (not real catalog courses) use
a synthetic `course_id` like `"custom-<random>"`, `group_id: "0"`, and a
`isCustom: true` flag. They're stored per-user in Firestore, never in
`data/courses.json`. See "Personal points / custom events" below.

## The data pipeline — how `data/courses.json` gets built

This evolved a lot over the project's life. The **current recommended path**:

```bash
raw/my_env/bin/python3 scripts/scrape_all.py --headless
```

This is a Playwright script that drives a real Chromium browser against the
live site, does everything below automatically, and reports what changed.
Full historical run (`--latest-year` omitted) takes ~15-20 min for ~65
Year×Field combinations; `--latest-year` (for routine re-checks) takes a
couple minutes.

If you need to backfill/refresh points, end dates, syllabus, learning
outcomes, or prerequisites for courses **already** in `data/courses.json`
without re-scraping the course lists:

```bash
raw/my_env/bin/python3 scripts/refresh_details.py --headless
```

This reads the pid/pprev pairs straight out of `data/courses.json` (no
manual list to maintain) and re-fetches each course's detail page.

### Why scraping is done via a real local browser, not a hosted fetch

`erez.weizmann.ac.il`'s `robots.txt` disallows automated scraping. A real
browser driven locally by the user (via Playwright, or manually via
copy-pasting a script into DevTools) is a fundamentally different thing from
a remote/hosted scraper — it's the user's own browser, their own session,
same as them clicking through the site by hand, just automated to save
labor. This distinction was discussed explicitly with the user and is why
`scrape_all.py`/`refresh_details.py` exist as **local-only** scripts the user
runs themselves, never as something an AI fetches directly (`WebFetch` and
similar tools correctly respect the site's `robots.txt` and will refuse it).

### The manual/legacy path (what scrape_all.py automates)

For one field/year at a time, by hand:
1. On the site, set Academic Year + Field of study, click Search.
2. DevTools console → paste `scripts/scrape-pages.js` → downloads two files:
   `wsos_<field>_<year>.html` (course rows) and `wsos_<field>_<year>_points.json`
   (points/end-dates/syllabus/etc. for those courses' detail pages).
3. Move both into `raw/`, repeat per field/year.
4. `python3 scripts/build_courses.py raw data/courses.json` — parses every
   `.html`, merges (de-duping, accumulating `fields`), attaches the `.json`
   points data, **merges onto the existing output file rather than
   overwriting it** (important — see bug #1 below).

`scripts/fetch-points.js` is the older sibling of `refresh_details.py`: same
idea (refresh points for every known course without re-scraping lists), but
needs a hand-maintained `COURSE_PAIRS` array pasted into the script — kept
around for whole-catalog refreshes without needing Python/Playwright set up,
but `refresh_details.py` is strictly better (no array to maintain) if you can
run Python locally.

### Real gotchas found running this against the live site (read before touching `scrape_all.py`)

These were each found by actually running against `erez.weizmann.ac.il`, not
guessed — don't revert these fixes without re-verifying against the real
site.

1. **`build_courses.py` must merge onto the existing output file, not
   overwrite it.** Early version treated `raw/` as the sole source of truth
   and replaced `data/courses.json` outright — so running it with only this
   week's raw files silently deleted every course from years/fields not
   currently sitting in `raw/`. Real data loss happened once before this was
   fixed. Current version loads the existing output first and only updates
   entries actually touched by this run's `raw/*.html`, leaving everything
   else untouched. `fill_computable_days()` (see #2) is applied to the whole
   merged set, not just freshly-parsed courses, so it also retroactively
   fixes old carried-forward entries.

2. **Sessions with no weekday but a known `first_lecture` date are
   computable, not unparseable.** A PLACE cell like `"09:00 - 13:00, WSoS,
   Rm A"` (time + location, no day name) can't be placed on the calendar as
   scraped — but a course's weekly sessions always recur on the same weekday
   as its `first_lecture`, so `parse_courses.fill_computable_days()`
   computes it instead of leaving `day_index: null`. Fixed 28/32 previously
   "broken" sessions in one real run; the remaining few are genuinely
   irregular block-format courses ("held between 24/6-6/7, more info in
   comments") that don't fit a weekly-recurring model at all — those keep
   `day_index: null` and their raw `note` text, which the UI shows directly
   (in red, with a warning) instead of a misleading "TBA".

3. **Clicking "Search" on the real site is a genuine full-page form submit,
   not an AJAX update.** The button's `onclick` calls `apex.submit(...)`,
   which does a real POST + navigation. Confirmed against the site's actual
   HTML source. This is exactly why `scrape-pages.js`'s own header comment
   says it can't drive the Year/Field selection itself (a live in-page
   DevTools script dies on navigation) — and exactly why doing it from
   Playwright (outside the page) works: Playwright survives real
   navigations fine.

4. **Oracle APEX re-renders your *previous* search's results on a fresh page
   load**, rather than a blank form. `scrape_all.py` originally did
   `goto(search_page) → select dropdowns → click search → wait for a
   results table → inject scrape-pages.js`. The "wait for results table"
   step could match the *stale* table left over from the previous
   combination instantly, before the real new search (triggered moments
   earlier by the click) had actually landed — then the genuinely-new
   navigation would interrupt the in-flight script injection:
   `Execution context was destroyed, most likely because of a navigation`.
   Confirmed live: 14 failures out of 15 real combinations before the fix.
   Fixed by having `click_search()` explicitly wait for the navigation it
   triggers (`page.expect_navigation()`) instead of relying on the results
   table alone. Re-verified clean across a full 65-combination live run
   after the fix (0 failures).

5. **`page.evaluate()` with a multi-statement script string is not reliably
   awaited** until the injected async IIFE actually resolves — checking a
   download count immediately after `evaluate()` returns is racy (verified:
   got 1 of 2 expected downloads once). Fixed by polling for both downloads
   with a generous timeout instead of trusting `evaluate()` to block.

6. **Syllabus/learning-outcomes extraction returned empty for ~98% of
   courses** for a long time before this was caught. Unlike `prerequisites`
   (plain text, e.g. `<span id="P30_PREREQ" ...>No</span>`), syllabus and
   learning-outcomes render as actual HTML inside their `<span>` — a
   `<ul><li>` bullet list and a `<p>` paragraph respectively (confirmed
   against a real detail page's source). The regex
   `id="P30_X"[^>]*>([^<]*)<` stops capturing at the very next `<`, which
   for these two fields is immediately the wrapping tag — so it always
   captured an empty string. Fixed by capturing everything up to the
   closing `</span>` instead (`[\s\S]*?<\/span>`), then converting the
   captured HTML to clean text in `build_courses._clean_detail_text()`
   (`<li>` → `"• "` bullet lines, `<br>`/`</p>` → newlines, remaining tags
   stripped, entities decoded). A full live re-fetch of all 1306 known
   courses afterward went from 16/1306 (syllabus) and 29/1306
   (learning_outcomes) populated to 1304/1306 for both.

### Real site structure notes (Oracle APEX specifics)

- Search page: `https://erez.weizmann.ac.il/apx/r/ws1/f1862681863611861860186/courses`
- Course detail page: `https://erez.weizmann.ac.il/apx/r/ws1/186/30?pid=<course_id>&pprev=<group_id>`
- Year dropdown `#P20_YEAR`, Field dropdown `#P20_FIELD` (both real `<select>`
  elements under the hood despite `data-native-menu="false"` styling —
  `page.select_option()` works fine against them directly).
- Field values seen historically: 10 Physical Sciences, 20 Chemical
  Sciences, 30 Life Sciences, 32/33/34/35 Life Sciences tracks, 40/41 Math
  and CS (+ Systems Biology track), 50/51/60 Science Teaching variants, 80
  Obligatory/enrichment. Years currently offered: 2023-2027. Don't hardcode
  these — `scrape_all.py` reads them live from the dropdowns every run.
- "Search" button: `<button type="button" onclick="apex.submit({request:'SUBMIT'})">`.
  Found via Playwright's `get_by_role("button", name="Search")` (robust to
  the button's actual `id` being an opaque generated string).
- Results table: `table.uReport.uReportAlternative`. Pagination is AJAX
  (`a.uPaginationNext`/`a.uPaginationPrevious`), unlike the Search button.
- Detail-page fields used, all `<span id="P30_X" ...>` inside a
  `<div id="P30_X_CONTAINER">` wrapper with a `<label id="P30_X_LABEL">`:
  `P30_CREDIT` (an `<input value="...">`, not a span), `P30_END_DATE`,
  `P30_COURSE_CODE`, `P30_PREREQ` (plain text), `P30_COURSE_SYLLABUS_NEW`
  (HTML `<ul><li>`), `P30_LEARNING_OUTCOME` (HTML `<p>`). Also present but
  unused so far: `P30_LANGUAGE`, `P30_GRADE_TYPE`, `P30_TA`, `P30_NOTE`
  (often a course URL), `P30_READING_LIST`, `P30_NO_OF_STUDENTS`,
  `P30_STUDENT_WORKLOAD`, exam-related fields — could be scraped the same
  way if ever wanted.
- End dates and course codes come through HTML-escaped (`&#x2F;` for `/`) —
  always `html.unescape()`/decode before storing.

## Frontend (`index.html`) — key concepts

Single file, vanilla JS, no build step, no framework. Roughly:
CSS in `<style>` → HTML body → one big `<script>` at the bottom.

- **State**: `ALL_COURSES` (the full catalog, loaded from `data/courses.json`
  at startup), `selected` (a `Map<courseKey, course>` — the current user's
  schedule, both real courses and custom events mixed together),
  `pointsMap`/`endDateMap` (shared, admin-edited, from Firestore
  `courseMeta`), `personalPointsMap` (this user's own point overrides, from
  their own Firestore user doc).
- **Year/semester scoping**: `getActiveYear()` reads the year `<select>`
  (mandatory, no "all years" option, defaults to the latest year found).
  Changing it re-scopes the calendar, "My schedule" list, and point totals —
  a course added under one year simply doesn't show when viewing another
  (but stays saved). `activeSemester` ('1st'/'2nd') similarly scopes the
  calendar grid; "My schedule" instead shows **both** semesters as separate
  grouped sections (Full Year courses appear in both groups, since they're
  one saved entry displayed twice — removing from either group removes both).
- **Points system**: `getPoints(c)` = shared/catalog value only (Firestore
  `courseMeta`, admin-edited, falls back to `c.points` baked into
  courses.json). `getEffectivePoints(c)` = what a *specific user* sees for
  their own schedule/totals — personal override first, else shared. Browse
  cards always show the shared value (`getPoints`); "My schedule" shows the
  effective value (`getEffectivePoints`). Only the admin (`OWNER_EMAIL`) can
  edit the shared value; everyone else gets a personal-only override, shown
  only for courses already in their schedule. Custom events have their own
  `points` field directly on the object (always editable by their owner,
  regardless of admin status — never touches the shared system at all).
- **Semester point totals**: computed as three *mutually exclusive* buckets
  (Semester 1 only, Semester 2 only, Full Year) that sum to the combined
  total — an earlier version double-counted Full Year courses into both
  semester totals since it filtered by `semester === X || semester ===
  'Full Year'` for both sides; fixed to strict equality per bucket.
- **Admin-only actions** (gated on `currentUserEmail === OWNER_EMAIL`,
  UI-level only — see "Security model"): editing shared course points,
  deleting reviews, the "Import parsed JSON" panel.
- **Custom/personal events**: created via "+ Add event" (title, faculty,
  instructor, semester, year, day, start/end time, location — day was added
  beyond what was originally asked for since the calendar needs one).
  Rendered with a dotted border to distinguish from real courses. Stored in
  the user's own Firestore doc (`users/{uid}.customEvents`), never shared.
- **Export to calendar**: clicking Export opens a checklist of the active
  year's scheduled courses (all checked by default) rather than exporting
  everything blindly; courses with an unparsed session show a red warning
  explaining they'll be missing/absent from the `.ics` file.
- **Unparsed sessions** (`day_index: null`): shown with the raw `note` text
  in red/warning styling in both the course card and the info modal, instead
  of a silent "? ?–?" — see pipeline gotcha #2 above for why some of these
  are unavoidable (genuinely irregular block-format courses).

## Security model (important — UI gating vs. real enforcement)

`OWNER_EMAIL` checks in `index.html` are **client-side only**. The actual
Firestore security rules (documented in `README.md` §4.4) are what provide
real enforcement:

```
courseMeta/{courseKey}: read=true, write=only OWNER_EMAIL
reviews/{reviewId}:      read=true, create=any signed-in user, update=false, delete=only OWNER_EMAIL
users/{uid}:              read/write=only that uid (covers personal points + custom events automatically)
```

These rules are documented in the README but **must be pasted into the
Firebase console manually** — nothing here deploys them automatically. If a
future change adds a new admin-only UI control, check whether it also needs
a matching Firestore rule change, and remind the user to apply it in the
console (this has come up multiple times in this project's history).

## Git workflow

- `main` — production, GitHub Pages deploys from here.
- `dev` — working branch; changes land here first, get tested, then get
  merged into `main` when ready to ship. This was set up explicitly at the
  user's request ("so changes won't be straight to production") partway
  through the project.
- The user sometimes merges `dev` → `main` via GitHub's web UI directly (PR
  merges) in parallel with local work — if a local push to `main` gets
  rejected as non-fast-forward, `git fetch` and check whether the remote
  tip's tree content actually matches local `dev`/`main` before assuming a
  real conflict; it has turned out to just be the same content reached via
  a different commit graph (merge commit vs. rebase/fast-forward) more than
  once.
- Never commit or push without being asked explicitly — this was corrected
  once early on (an unprompted commit was made, then un-done with `git
  reset --soft`) and is now a hard rule for this project specifically.
- When merging `dev` into `main` and a conflict arises in the scraper
  scripts specifically, it has consistently meant "`main` has an earlier
  cherry-picked version, `dev` has a later fix" — verify the "theirs" (dev)
  side is really the complete/correct one (diff the resolved file against
  `dev` directly) rather than hand-merging.

## Known gaps / things not yet done

- Firestore security rules exist only in `README.md` as documentation — a
  future session should double check whether they were actually applied in
  the Firebase console, since it's an out-of-band manual step.
- A handful of sessions (~4 out of 1306 currently) are genuinely irregular
  block-format courses that don't fit the weekly-recurring calendar model
  at all — by design, not a bug, but worth being aware of if someone asks
  "why doesn't course X show on the calendar."
- `P30_TA`, `P30_NOTE`, `P30_READING_LIST`, and a few other detail-page
  fields are known (see "Real site structure notes") but not currently
  scraped/shown — easy to add following the same pattern as
  syllabus/prerequisites if ever wanted.
- `scripts/refresh_details.py` and `scripts/scrape_all.py` have no
  automated test suite — they were validated by running against fake local
  pages built to mimic the real site's structure, and then against the real
  site itself. Any future change to the scraping logic should be
  re-verified the same way (build a quick fake page or two, confirm the
  navigation/extraction logic still works) before trusting it against the
  live site, given how many subtle real-site-only bugs turned up during
  development (see gotchas #3-6 above — none of these were catchable by
  code review alone, only by actually running against the real site).
