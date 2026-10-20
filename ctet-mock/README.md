# CTET Mock

A mobile-installable PWA that hosts CTET mock papers and works with no signal.
Papers are filed on the landing page as **Paper → Subject → Class → Lesson → Mock**.

This folder is a self-contained side project. It does not touch the StudySynth
pipeline, templates or tests.

---

## 1. What is in here

```
ctet-mock/
  build.py               the build command: classify the mocks, write the catalogue
  vercel.json            static hosting config
  public/                everything the phone downloads
    index.html           the library
    player.html          opens one mock paper
    app.css  app.js      the library's styles and behaviour
    player.js
    manifest.webmanifest
    catalog.json         generated - the classified library
    sw.js                generated - the offline worker
    icons/               generated - the app icon
    mocks/               YOUR MOCK PAPERS GO HERE
  ctetmock/              the build code
  tools/make_icons.py    regenerates the icon
  tests/                 unit and browser tests
```

`catalog.json` and `sw.js` are generated. Rebuild them whenever the mocks
change, and commit the result.

## 2. Adding a mock paper

Four steps.

**1. Generate the mock** with the StudySynth pipeline, using the CTET profile:

```bash
python scripts/build_web.py build/<run>/quiz_package.json \
  --out ctet-mock/public/mocks/p2-sci-c8-light-m01.html \
  --title "Light"
```

**2. Name the file** so the library can file it:

```
<paper>-<subject>-<class>-<lesson>-<mock>.html
```

Example: `p2-sci-c8-light-m01.html`

| Part      | Accepted values |
| --------- | --------------- |
| paper     | `p1` `p2` `paper1` `paper2` `paper-i` `paper-ii` |
| subject   | `cdp` `math` `maths` `evs` `science` `sci` `social` `socialscience` `socialstudies` `sst` `lang1` `hindi` `lang2` `english` |
| class     | `c1`…`c8` `class-7` `grade8` |
| lesson    | any words, joined with `-` |
| mock      | `m01` `m1` `mock2` `mock-03` `set4` |

A class is optional in the name but strongly recommended: `c8` is read as
Class 8, while a bare number is only used when no `cN` form is present, so
`chapter-1` is never mistaken for a class.

If a name will not fit the convention, put a sidecar next to the mock:

```json
{
  "paper": "Paper II",
  "subject": "Science",
  "class": 8,
  "lesson": "Light",
  "mock": "Mock 1",
  "title": "Light - Mock 1"
}
```

Save it as `light-m01.meta.json` beside `light-m01.html`. The sidecar wins
over the file name.

**3. Rebuild:**

```bash
python ctet-mock/build.py
```

It prints what it found:

```
paper   subject        class  lesson              mock    questions  source
------  -------------  -----  ------------------  ------  ---------  ---------
Paper I Environmental  4      Plants              Mock 1  24         filename
Paper II Social Sci    8      Natural Resources   Mock 1  24         filename
```

Anything it cannot file is reported as `INCOMPLETE` and the command exits
with an error, so a paper never silently disappears. `--allow-unclassified`
publishes them anyway under an "Unclassified" heading.

**4. Commit and deploy.**

The build also gives every mock a distinct title inside the mock itself, so
two mocks of the same lesson never share a saved session.

## 3. Trying it on a phone

```bash
cd ctet-mock
python -m http.server 8000
```

Open `http://<your-computer-ip>:8000` on the phone. Use the browser menu →
**Add to Home Screen**. After the first load the whole library is cached and
works with the network off.

On a laptop you can also open `ctet-mock/public/index.html` directly, but the
service worker needs a real web address, so offline caching will not work.

## 4. Deploying to Vercel

The site is plain static files - no build step on the server.

1. `vercel login`
2. `vercel --cwd ctet-mock --prod`
   (or point the Vercel project's **Root Directory** at `ctet-mock`)

`vercel.json` sets `outputDirectory: "public"` and the cache headers:
the worker and the catalogue are always revalidated, icons are cached for a
year. `catalog.json` and `sw.js` are committed, so a deploy needs no server
side build - just run `python ctet-mock/build.py` and commit before deploying.

## 5. Offline behaviour

- The service worker precaches the library, the catalogue, the icons and
  every mock the first time the app opens.
- A banner reports how much is cached while it fills up.
- The cache is keyed on the **content** of the files, so a paper you
  regenerate under the same name still reaches the phone.
- When a new version is ready, a banner offers a refresh.

## 6. Tests

```bash
python -m pytest ctet-mock/tests -v
```

- `test_icons.py` - the manifest and the generated icon
- `test_intake.py` - the naming convention and the fallbacks
- `test_catalog.py` - the tree, the ordering, unique titles and session keys
- `test_sw.py` - the offline worker, the build command, the deploy config
- `test_ui_static.py` - the landing page and the player
- `test_ui.py` - a real browser: the drill-down, the search, the player, and
  the whole library with the network switched off

`test_ui.py` needs Playwright with Chromium installed; it skips itself if
they are missing.

## 7. Regenerating the icon

```bash
python ctet-mock/tools/make_icons.py
```

The icon is drawn with the standard library only - no image files to keep.
