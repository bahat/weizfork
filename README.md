# WSoS Scheduler

A course browser and weekly-schedule planner for the Weizmann School of Science,
built from data scraped off the public course catalog (`erez.weizmann.ac.il`).
The frontend is a static site (GitHub Pages, no build step); sign-in, saved
schedules, shared course points/end-dates, and reviews are backed by Firebase.

```
.
├── index.html              the whole app (UI + logic)
├── data/
│   └── courses.json        course data, loaded at runtime via fetch()
└── scripts/
    ├── parse_courses.py    turns a saved catalog page into courses.json
    ├── merge_courses.py    combines multiple parse_courses.py outputs
    ├── build_courses.py    one-shot: turns a folder of raw/*.html + raw/*.json
    │                       (scrape-pages.js's downloads) into one courses.json
    ├── scrape-pages.js     browser console script: paginates a field/year's
    │                       search results and fetches those courses' credit
    │                       points/end-dates, in one run
    └── fetch-points.js     browser console script to bulk-fetch credit points
                            for the whole already-known catalog at once
```

---

## 1. Collect the data

The catalog (`https://erez.weizmann.ac.il/apx/r/ws1/f1862681863611861860186/courses`)
blocks automated scraping (`robots.txt`), so pages are collected by hand and parsed
locally — one page per (Field of study × Academic Year) combination you want covered.

**Per field/year:**

1. Open the courses page, set **Academic Year** and **Field of study**, click Search.
2. Open DevTools (F12) → Console, paste the full contents of
   `scripts/scrape-pages.js`, press Enter. It pages through every result page
   (AJAX pagination, so it's safe to click through by script), returns to page 1
   when it's done, then fetches each course's detail page for its credit points
   and real end date. It downloads two files:
   - `wsos_<field>_<year>.html` — the combined course rows, for `parse_courses.py`
   - `wsos_<field>_<year>_points.json` — points/end-dates, ready to import
3. Move both files into `raw/` and repeat for every field/year you want
   (Physical Sciences, Chemical Sciences, Life Sciences, Mathematics and
   Computer Science, etc., × each year back to 2023).

4. Once `raw/` has all the `.html` + `.json` pairs, build the combined dataset
   in one shot:
   ```
   python3 scripts/build_courses.py raw data/courses.json
   ```
   This parses every `.html` file, merges them (de-duplicating cross-listed
   courses into a `fields` list, same as `merge_courses.py`), and attaches
   `points`/`end_date` from every `.json` file it finds — safe to re-run
   any time `raw/` gets new files.

   (`parse_courses.py` + `merge_courses.py` still work individually the same
   way if you'd rather process files one at a time.)

5. Once the site is live and Firebase is configured (§4 below), open it, **sign
   in**, and use **Import parsed JSON** in the sidebar to load each
   `..._points.json` file — it's auto-detected as a points/end-date map and
   published to Firestore, so it becomes visible to every visitor immediately,
   not just you. (`build_courses.py` bakes points/end-dates into
   `data/courses.json` too, but the live app currently reads them from
   Firestore, not from that file — so this step is still needed for other
   visitors to see them.)

**Refreshing points/end-dates later without re-scraping** (e.g. mid-semester,
to pick up updated end dates for courses you've already imported):

1. Open the courses page in a browser tab (any page on `erez.weizmann.ac.il` works).
2. Open DevTools (F12) → Console.
3. Paste the full contents of `scripts/fetch-points.js` and press Enter.
   It fetches every course the app already knows about (same-origin, no CORS
   issues), waits briefly between requests, and downloads `wsos-points.json`
   when done — import it the same way as above.

---

## 2. Upload to GitHub

```bash
cd wsos-scheduler          # this folder
git init
git add .
git commit -m "Initial commit"
```

Create a new repository on GitHub (github.com → New repository — don't
initialize it with a README, since you already have one), then:

```bash
git remote add origin https://github.com/<your-username>/<repo-name>.git
git branch -M main
git push -u origin main
```

---

## 3. Host it with GitHub Pages

1. On GitHub, go to your repo → **Settings** → **Pages**.
2. Under "Build and deployment", set **Source** to "Deploy from a branch".
3. Branch: `main`, folder: `/ (root)`. Save.
4. GitHub gives you a URL like `https://<your-username>.github.io/<repo-name>/`
   — it takes a minute or two to go live the first time.

That's it — `index.html` fetches `data/courses.json` from the same origin, so
no server-side code is needed.

---

## 4. Set up the backend (Firebase — Auth + database)

Everyone's sign-in, shared course points/end-dates, and reviews are backed by
[Firebase](https://firebase.google.com) (Google's app backend platform — free
for this scale of usage). Firebase also manages the Google Sign-In OAuth client
for you, so there's no separate Google Cloud Console step.

### 4.1 Create the Firebase project

1. Go to the [Firebase console](https://console.firebase.google.com) → **Add project**.
2. Name it whatever you like, disable Google Analytics if you don't need it, create.

### 4.2 Register a Web App

1. In the project overview, click the **`</>`** (Web) icon to add a web app.
2. Give it a nickname, skip Firebase Hosting (you're using GitHub Pages instead).
3. It'll show you a `firebaseConfig` object like:
   ```js
   const firebaseConfig = {
     apiKey: "AIza...",
     authDomain: "your-project.firebaseapp.com",
     projectId: "your-project",
     storageBucket: "your-project.appspot.com",
     messagingSenderId: "123456789",
     appId: "1:123456789:web:abcdef",
   };
   ```
4. In `index.html`, find the `firebaseConfig` placeholder near the top of the
   `<script>` block and replace it with this real object.

### 4.3 Enable Google Sign-In

1. In the Firebase console: **Authentication** → **Sign-in method** → enable **Google**.
2. Pick a support email when prompted, save.
3. Go to **Authentication** → **Settings** → **Authorized domains** → **Add domain**.
   Add your GitHub Pages host, e.g.:
   ```
   <your-username>.github.io
   ```
   (Firebase already includes `localhost` and `<project>.firebaseapp.com` by default.)

### 4.4 Create the Firestore database

1. **Firestore Database** → **Create database** → choose a region close to you → start in **production mode**.
2. Go to the **Rules** tab and replace the default rules with:
   ```
   rules_version = '2';
   service cloud.firestore {
     match /databases/{database}/documents {

       // Course points & end dates: everyone can read, only signed-in users can edit.
       match /courseMeta/{courseKey} {
         allow read: if true;
         allow write: if request.auth != null;
       }

       // Reviews: everyone can read, only signed-in users can post, nobody can edit/delete
       // (keeps things simple; the app already hides who posted what).
       match /reviews/{reviewId} {
         allow read: if true;
         allow create: if request.auth != null;
         allow update, delete: if false;
       }

       // Each user's saved schedule: only that user can read/write their own doc.
       match /users/{uid} {
         allow read, write: if request.auth != null && request.auth.uid == uid;
       }
     }
   }
   ```
3. Click **Publish**.

### 4.5 Push and test

```bash
git add index.html
git commit -m "Configure Firebase backend"
git push
```

Reload the live GitHub Pages site — you should see a real "Sign in with Google"
button. Once signed in:
- Your selected schedule saves automatically and follows you across devices.
- Points/end-dates you edit (or bulk-import via `fetch-points.js`) are written
  to Firestore and visible to **every visitor**, not just you.
- Reviews you post are visible to everyone, shown anonymously.

**Notes:**
- The Firebase free ("Spark") tier comfortably covers a small-to-medium course
  catalog and a modest number of visitors — you'd need real scale before
  hitting any limits.
- `firebaseConfig` values (including the API key) are meant to be public in
  client-side code — Firebase's actual access control is enforced by the
  Firestore security rules above, not by hiding the config.
- If you use a custom domain with GitHub Pages later, add it under
  Authentication → Settings → Authorized domains the same way.


---

## Updating the data later

Re-run steps in **§1** for whichever field/year changed, re-merge into
`data/courses.json`, then:

```bash
git add data/courses.json
git commit -m "Update course data"
git push
```

GitHub Pages picks up the change automatically within a minute or two.
