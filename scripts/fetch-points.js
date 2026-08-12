/*
  WSoS Scheduler — bulk points/end-date fetcher (whole known catalog)
  =======================================================================
  Scraping a field/year with scrape-pages.js now also fetches points/end-dates
  for just that field/year automatically. Use THIS script instead when you want
  to refresh points/end-dates for every course the app already knows about
  (e.g. mid-semester, to pick up updated end dates) without re-scraping any
  course lists.

  HOW TO USE:
  1. Open https://erez.weizmann.ac.il/apx/r/ws1/f1862681863611861860186/courses
     in your browser (any tab on that site works, since fetch() below is same-origin).
  2. Open DevTools (F12) -> Console tab.
  3. Paste this entire script and press Enter.
  4. Wait — it fetches each course's detail page one at a time with a short delay
     to be polite to the server. Progress prints to the console.
  5. When done, it automatically downloads "wsos-points.json" to your Downloads folder.
  6. Upload that file in the scheduler app via "Import parsed JSON" — the app detects
     this is a points/end-date map (not a course list) and merges it automatically.

  If you added more departments/years to the app, re-run parse_courses.py on those
  pages first, then ask Claude to generate an updated version of this script with
  the new course_id/group_id pairs included.
*/
(async function () {
  const COURSE_PAIRS = [{"key": "15883-0", "pid": "15883", "pprev": "0"}, {"key": "15880-13729", "pid": "15880", "pprev": "13729"}, {"key": "15881-15597", "pid": "15881", "pprev": "15597"}, {"key": "15872-0", "pid": "15872", "pprev": "0"}, {"key": "16045-15026", "pid": "16045", "pprev": "15026"}, {"key": "15885-15696", "pid": "15885", "pprev": "15696"}, {"key": "15833-15703", "pid": "15833", "pprev": "15703"}, {"key": "15830-15375", "pid": "15830", "pprev": "15375"}, {"key": "15832-15573", "pid": "15832", "pprev": "15573"}, {"key": "15831-15603", "pid": "15831", "pprev": "15603"}, {"key": "15840-0", "pid": "15840", "pprev": "0"}, {"key": "16037-15572", "pid": "16037", "pprev": "15572"}, {"key": "16039-0", "pid": "16039", "pprev": "0"}, {"key": "16028-15574", "pid": "16028", "pprev": "15574"}, {"key": "15838-15579", "pid": "15838", "pprev": "15579"}, {"key": "16058-15605", "pid": "16058", "pprev": "15605"}, {"key": "16047-0", "pid": "16047", "pprev": "0"}, {"key": "16038-0", "pid": "16038", "pprev": "0"}, {"key": "16044-13727", "pid": "16044", "pprev": "13727"}, {"key": "15882-15592", "pid": "15882", "pprev": "15592"}, {"key": "15884-15580", "pid": "15884", "pprev": "15580"}, {"key": "16009-15576", "pid": "16009", "pprev": "15576"}, {"key": "16036-15566", "pid": "16036", "pprev": "15566"}, {"key": "15828-15240", "pid": "15828", "pprev": "15240"}, {"key": "16035-15339", "pid": "16035", "pprev": "15339"}, {"key": "16059-15595", "pid": "16059", "pprev": "15595"}, {"key": "15829-15609", "pid": "15829", "pprev": "15609"}, {"key": "16025-0", "pid": "16025", "pprev": "0"}, {"key": "16052-15575", "pid": "16052", "pprev": "15575"}, {"key": "15836-15599", "pid": "15836", "pprev": "15599"}, {"key": "15837-15600", "pid": "15837", "pprev": "15600"}, {"key": "15834-15570", "pid": "15834", "pprev": "15570"}, {"key": "15835-15571", "pid": "15835", "pprev": "15571"}, {"key": "16050-0", "pid": "16050", "pprev": "0"}, {"key": "16034-15237", "pid": "16034", "pprev": "15237"}, {"key": "15865-0", "pid": "15865", "pprev": "0"}, {"key": "15842-15165", "pid": "15842", "pprev": "15165"}, {"key": "15928-0", "pid": "15928", "pprev": "0"}, {"key": "16061-15235", "pid": "16061", "pprev": "15235"}, {"key": "16051-0", "pid": "16051", "pprev": "0"}, {"key": "16053-16051", "pid": "16053", "pprev": "16051"}, {"key": "15912-15594", "pid": "15912", "pprev": "15594"}, {"key": "15860-0", "pid": "15860", "pprev": "0"}, {"key": "15994-15200", "pid": "15994", "pprev": "15200"}, {"key": "15962-15191", "pid": "15962", "pprev": "15191"}, {"key": "15804-15427", "pid": "15804", "pprev": "15427"}, {"key": "16033-0", "pid": "16033", "pprev": "0"}]
;

  const BASE = "https://erez.weizmann.ac.il/apx/r/ws1/186/30";
  const results = {};
  let done = 0;

  function grab(html, pattern) {
    const m = html.match(pattern);
    return m ? m[1].trim() : null;
  }

  for (const { key, pid, pprev } of COURSE_PAIRS) {
    const url = `${BASE}?pid=${pid}&pprev=${pprev}`;
    try {
      const res = await fetch(url, { credentials: "include" });
      const html = await res.text();

      const creditRaw = grab(html, /id="P30_CREDIT"[^>]*value="([^"]*)"/);
      const points = creditRaw ? parseFloat(creditRaw) : null;
      const end_date = grab(html, /id="P30_END_DATE"[^>]*>([^<]*)</);
      const course_code = grab(html, /id="P30_COURSE_CODE"[^>]*>([^<]*)</);
      // Syllabus/learning-outcomes render as HTML (a <ul><li> list / a <p>),
      // not plain text, so capture everything up to the closing </span>
      // instead of stopping at the first "<" (which matched empty every
      // time — confirmed against a real detail page).
      const syllabus = grab(html, /id="P30_COURSE_SYLLABUS_NEW"[^>]*>([\s\S]*?)<\/span>/);
      const learning_outcomes = grab(html, /id="P30_LEARNING_OUTCOME"[^>]*>([\s\S]*?)<\/span>/);
      const prerequisites = grab(html, /id="P30_PREREQ"[^>]*>([^<]*)</);

      results[key] = {
        points: isNaN(points) ? null : points,
        end_date: end_date || null,
        course_code: course_code || null,
        syllabus: syllabus || null,
        learning_outcomes: learning_outcomes || null,
        prerequisites: prerequisites || null,
      };
    } catch (e) {
      results[key] = { points: null, end_date: null, error: String(e) };
    }
    done++;
    console.log(`[${done}/${COURSE_PAIRS.length}] ${key} ->`, results[key]);
    await new Promise((r) => setTimeout(r, 250)); // be polite
  }

  const blob = new Blob([JSON.stringify(results, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "wsos-points.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  console.log("Done. Downloaded wsos-points.json — import it into the scheduler app.");
})();
