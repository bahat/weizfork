/*
  WSoS Scheduler — paginated results scraper + points fetcher
  =============================================================
  WHAT THIS DOES:
  1. Clicks through every "Next" page of the CURRENT search results (pagination
     here is AJAX, not a real page load, so a script can safely click through it)
     and downloads one combined HTML file with every row — ready to hand straight
     to parse_courses.py, no manual Inspect/Copy-outerHTML needed per page.
  2. Clicks back to page 1 afterwards, so the UI is left in a sane state for the
     next field/year search instead of stranded on the last page.
  3. Reads the course_id/group_id pair out of each row it just captured and
     fetches that course's detail page (same-origin, no CORS issues) to pull its
     credit points and real semester end date — the same thing fetch-points.js
     does, but scoped automatically to just the courses on this field/year
     instead of a hand-maintained list. Downloads a second file with the result.

  WHAT THIS DOES NOT DO:
  It can't pick the Year/Field dropdowns and click Search for you — that's a
  real page navigation, which would kill this script mid-run. You still do
  that part by hand, once per field/year combination.

  HOW TO USE:
  1. On the courses page, set Academic Year + Field of study, click Search.
  2. Open DevTools (F12) -> Console.
  3. Paste this whole script, press Enter.
  4. Watch the console log each page it captures, then each course's points
     being fetched. When done, it downloads two files:
       - "wsos_<field>_<year>.html"         -> hand to parse_courses.py
       - "wsos_<field>_<year>_points.json"  -> import directly in the app via
                                                "Import parsed JSON" (or fold it
                                                into a wider wsos-points.json).
  5. Repeat for each field/year you want, then merge the .html outputs together
     with merge_courses.py.

  Still want to bulk-refresh points/end-dates for the ENTIRE already-known
  catalog without re-scraping any course lists? Use scripts/fetch-points.js —
  that one covers every course the app already knows about in a single run,
  independent of whatever field/year is currently selected here.
*/
(async function scrapeAllPages(){
  function getTable(){
    return document.querySelector('table.uReport.uReportAlternative');
  }
  function getPagingText(){
    const el = document.querySelector('.fielddata');
    return el ? el.textContent.trim() : null;
  }
  function getNextLink(){
    return document.querySelector('a.uPaginationNext');
  }
  function getPrevLink(){
    let el = document.querySelector('a.uPaginationPrevious, a.uPaginationPrev');
    if(el) return el;
    // Fallback: some APEX themes don't use a predictable class name for the
    // "previous" control — look near the Next link for anything that reads
    // like a previous/first-page control instead of guessing blindly.
    const next = getNextLink();
    const container = next ? next.closest('.uPagination, nav, div') : document;
    const candidates = container ? [...container.querySelectorAll('a')] : [];
    el = candidates.find(a => /prev|first|«|‹/i.test(
      `${a.textContent} ${a.getAttribute('aria-label') || ''} ${a.getAttribute('title') || ''}`
    ));
    return el || null;
  }
  function waitForChange(prevText, timeoutMs){
    const start = Date.now();
    return new Promise((resolve) => {
      const iv = setInterval(() => {
        const cur = getPagingText();
        if(cur !== prevText || Date.now() - start > timeoutMs){
          clearInterval(iv);
          resolve(cur);
        }
      }, 200);
    });
  }
  function grab(html, pattern){
    const m = html.match(pattern);
    return m ? m[1].trim() : null;
  }
  function download(content, type, filename){
    const blob = new Blob([content], { type });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  const table0 = getTable();
  if(!table0){
    console.error('No results table found — run a search first (set Year/Field, click Search), then run this script.');
    return;
  }

  const allRowsHTML = [];
  let theadHTML = table0.querySelector('thead').outerHTML;
  let page = 1;
  const MAX_PAGES = 20; // safety limit

  while(true){
    const table = getTable();
    if(!table){ console.error('Results table disappeared unexpectedly — stopping.'); break; }
    const rowsHTML = [...table.querySelectorAll('tbody tr')].map(tr => tr.outerHTML);
    allRowsHTML.push(...rowsHTML);
    console.log(`Page ${page}: captured ${rowsHTML.length} rows (running total: ${allRowsHTML.length})`);

    const nextLink = getNextLink();
    if(!nextLink){
      console.log('No more pages — done paginating forward.');
      break;
    }
    if(page >= MAX_PAGES){
      console.warn(`Stopped after ${MAX_PAGES} pages (safety limit) — increase MAX_PAGES if you really have more.`);
      break;
    }

    const prevText = getPagingText();
    nextLink.click();
    await waitForChange(prevText, 8000);
    await new Promise(r => setTimeout(r, 300)); // small settle buffer after the AJAX swap
    page++;
  }

  const totalPages = page;

  const yearSel = document.querySelector('#P20_YEAR');
  const fieldSel = document.querySelector('#P20_FIELD');
  const yearVal = yearSel ? yearSel.value : '';
  const yearLabel = yearSel && yearSel.selectedOptions[0] ? yearSel.selectedOptions[0].textContent : '';
  const fieldLabel = fieldSel && fieldSel.selectedOptions[0] ? fieldSel.selectedOptions[0].textContent : '';
  const safeField = (fieldLabel || 'unknown').replace(/[^a-z0-9]+/gi, '_');

  // Walk back to page 1 so the search results aren't left stranded on the
  // last page. Non-fatal if a previous-page link can't be found — the data
  // we came here for is already captured either way.
  if(page > 1){
    console.log(`Returning to page 1 (currently on page ${page})...`);
    let safety = page;
    while(page > 1 && safety > 0){
      const prevLink = getPrevLink();
      if(!prevLink){
        console.warn('Could not find a "previous page" link — click back to page 1 manually if you need to.');
        break;
      }
      const prevText = getPagingText();
      prevLink.click();
      await waitForChange(prevText, 8000);
      await new Promise(r => setTimeout(r, 300));
      page--;
      safety--;
    }
    console.log(page === 1 ? 'Back on page 1.' : `Stopped on page ${page} (couldn't get all the way back — click back manually if needed).`);
  }

  // Rebuild minimal select elements so parse_courses.py's auto-detection still works.
  const combinedHTML = `<!doctype html>
<html><head><title>Courses &amp; Schedules</title></head><body>
<select id="P20_YEAR"><option value="${yearVal}" selected="selected">${yearLabel}</option></select>
<select id="P20_FIELD"><option value="${fieldSel ? fieldSel.value : ''}" selected="selected">${fieldLabel}</option></select>
<table class="uReport uReportAlternative">
${theadHTML}
<tbody>
${allRowsHTML.join('\n')}
</tbody>
</table>
</body></html>`;

  const htmlFilename = `wsos_${safeField}_${yearVal || 'unknown'}.html`;
  download(combinedHTML, 'text/html', htmlFilename);
  console.log(`Downloaded ${htmlFilename} — ${allRowsHTML.length} total rows across ${totalPages} page(s).`);

  // Pull course_id/group_id pairs straight out of the rows we just captured
  // (same "det('...', pid, pprev)" links parse_courses.py reads) and fetch
  // each course's detail page for its credit points + real end date.
  const pairMap = new Map();
  allRowsHTML.forEach(rowHtml => {
    const m = rowHtml.match(/det\('[^']*',\s*(\d+)\s*,\s*(\d+)\s*\)/);
    if(m) pairMap.set(`${m[1]}-${m[2]}`, { pid: m[1], pprev: m[2] });
  });
  const coursePairs = [...pairMap.values()];

  const POINTS_BASE = 'https://erez.weizmann.ac.il/apx/r/ws1/186/30';
  const pointsResults = {};
  let done = 0;
  console.log(`Fetching points/end-dates for ${coursePairs.length} course(s)...`);
  for(const { pid, pprev } of coursePairs){
    const key = `${pid}-${pprev}`;
    const url = `${POINTS_BASE}?pid=${pid}&pprev=${pprev}`;
    try {
      const res = await fetch(url, { credentials: 'include' });
      const html = await res.text();
      const creditRaw = grab(html, /id="P30_CREDIT"[^>]*value="([^"]*)"/);
      const points = creditRaw ? parseFloat(creditRaw) : null;
      const end_date = grab(html, /id="P30_END_DATE"[^>]*>([^<]*)</);
      const course_code = grab(html, /id="P30_COURSE_CODE"[^>]*>([^<]*)</);
      pointsResults[key] = { points: isNaN(points) ? null : points, end_date: end_date || null, course_code: course_code || null };
    } catch (e) {
      pointsResults[key] = { points: null, end_date: null, error: String(e) };
    }
    done++;
    console.log(`[${done}/${coursePairs.length}] ${key} ->`, pointsResults[key]);
    await new Promise((r) => setTimeout(r, 250)); // be polite
  }

  const pointsFilename = `wsos_${safeField}_${yearVal || 'unknown'}_points.json`;
  download(JSON.stringify(pointsResults, null, 2), 'application/json', pointsFilename);

  console.log(`Done. Downloaded ${htmlFilename} (for parse_courses.py) and ${pointsFilename} (import directly, or merge into a wider wsos-points.json).`);
})();
