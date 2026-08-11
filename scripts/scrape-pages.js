/*
  WSoS Scheduler — paginated results scraper
  =============================================
  WHAT THIS DOES:
  Clicks through every "Next" page of the CURRENT search results (pagination
  here is AJAX, not a real page load, so a script can safely click through it)
  and downloads one combined HTML file with every row — ready to hand straight
  to parse_courses.py, no manual Inspect/Copy-outerHTML needed per page.

  WHAT THIS DOES NOT DO:
  It can't pick the Year/Field dropdowns and click Search for you — that's a
  real page navigation, which would kill this script mid-run. You still do
  that part by hand, once per field/year combination. This just eliminates
  the multi-page copy-paste after you've searched.

  HOW TO USE:
  1. On the courses page, set Academic Year + Field of study, click Search.
  2. Open DevTools (F12) -> Console.
  3. Paste this whole script, press Enter.
  4. Watch the console log each page it captures. When done, it downloads
     a file like "wsos_Chemical_Sciences_2027.html".
  5. Hand that file to parse_courses.py as usual — it still auto-detects
     the year/field from the selected dropdown options embedded in the file.
  6. Repeat for each field/year you want, then merge_courses.py them together.
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
      console.log('No more pages — done.');
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

  const yearSel = document.querySelector('#P20_YEAR');
  const fieldSel = document.querySelector('#P20_FIELD');
  const yearVal = yearSel ? yearSel.value : '';
  const yearLabel = yearSel && yearSel.selectedOptions[0] ? yearSel.selectedOptions[0].textContent : '';
  const fieldLabel = fieldSel && fieldSel.selectedOptions[0] ? fieldSel.selectedOptions[0].textContent : '';

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

  const blob = new Blob([combinedHTML], { type: 'text/html' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  const safeField = (fieldLabel || 'unknown').replace(/[^a-z0-9]+/gi, '_');
  a.download = `wsos_${safeField}_${yearVal || 'unknown'}.html`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  console.log(`Done — ${allRowsHTML.length} total rows across ${page} page(s), downloaded as ${a.download}`);
})();
