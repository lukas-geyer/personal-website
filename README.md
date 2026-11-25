# lukasgeyer.com

The website for my apps: **Semestra** (study planner), **Paradeiser** (interval timer) and **Muninn** (flashcards, in development). A static site compiled from plain Markdown and one Python script, with no external dependencies: no web fonts, no CDN, no analytics, no cookies.

## Structure

- `site.json`: Name, start page copy, contact email, links, and one block per app (see "The App Blocks in site.json").
- `content/semestra/*.md`, `content/paradeiser/*.md`, `content/muninn/*.md`: One changelog entry per version.
- `assets/`: Stylesheet (`styles.css`), script (`site.js`) and images (`img/`: app icons and screenshots). Everything in this folder is copied to the site root.
- `build.py`: The builder. It also holds the privacy policies and the imprint, and writes everything into `dist/` (pages, RSS feed, sitemap, favicon, 404 page, `CNAME`, `.nojekyll`).
- `.github/workflows/pages.yml`: Builds and deploys `dist/` to GitHub Pages on every push to `main`.

`dist/` is build output: never edit it by hand, and it is not stored in git.

## The Pages

| Address | What it is |
| --- | --- |
| `/` | Start page: one sentence, the three apps, the latest updates |
| `/semestra/`, `/paradeiser/`, `/muninn/` | One page per app: hero, features, facts, changelog |
| `/semestra/privacy-policy/`, `/paradeiser/privacy-policy/`, `/muninn/privacy/` | Privacy policies, German and English |
| `/paradeiser/privacy/` | An older address that forwards to `/paradeiser/privacy-policy/` |
| `/imprint/`, `/about/`, `/404.html` | Imprint (German and English), About, the not-found page |
| `/rss.xml`, `/sitemap.xml`, `/robots.txt` | Feed of app updates, sitemap, robots file |

The apps and App Store Connect link to these addresses. Do not rename them.

## The Design

The design note at the top of `assets/styles.css` has the details. In short:

- **Type:** the system typeface (San Francisco on Apple devices), in six sizes.
- **Colour:** white, one light grey and near-black; in the dark the reverse. The site follows the system's light or dark setting; there is no switch.
- **Accents:** one per app, used for links and buttons on that app's pages and as a tint behind its hero and its tile. The start page, About and the imprint stay neutral.
- **Motion:** content settles in as it is scrolled into view (`site.js`), tiles and buttons answer the pointer, and pages cross-fade. All of it is off when the system asks for reduced motion, and every page reads fully without JavaScript.

## The App Blocks in site.json

Each app has a block under its own name (`semestra`, `paradeiser`, `muninn`):

| Key | What it does |
| --- | --- |
| `name`, `subtitle`, `summary` | Name, the one line under it, and the paragraph in the hero |
| `status` | The chip. `On the App Store …` is shown in green; anything else in grey |
| `app_store_url` | When present, the hero shows the App Store button. Without it, the status takes the button's place |
| `platforms`, `pricing`, `support_email` | The facts under the features |
| `accent` | The app's colour, as `{"light": "#RRGGBB", "dark": "#RRGGBB"}`. Buttons carry white text in light mode and black text in dark mode, so the light value must be dark enough for white text and the dark value light enough for black text |
| `icon` | The app icon's file name in `assets/img/`: a square PNG without rounded corners (the stylesheet rounds them). Required |
| `icon_dark` | Optional: the icon's dark appearance, shown instead while the system is in dark mode |
| `tile_shot` | The screenshot on the app's tile on the start page: `{"file": "…", "alt": "…"}`. Without it the tile shows text only |
| `features_title`, `features` | The feature section of the app's page. Each feature has a `title` and a `text`. A feature with `shots` (a list of `{"file", "alt"}`) becomes a wide row with its screenshots in device frames; features without are set side by side as plain blocks |

The current accents are the suite's Jewel colours: Semestra Teal `#007F82` / `#4BC2C6`, Paradeiser Ruby `#B21826` / `#F45249`, Muninn Amethyst `#472C9C` / `#937AE5`.

## Replacing Icons and Screenshots

The site shows each app's own icon, in its default and its dark appearance (`assets/img/<app>-icon.png` and `assets/img/<app>-icon-dark.png`, 512 × 512). When an app's icon changes:

1. Export both appearances as square PNGs, 512 × 512, without rounded corners and without transparency.
2. Replace the two files in `assets/img/`. Using the same file names is enough; nothing else changes.
3. If a file has a new name, put that name into the app's `icon` or `icon_dark` in `site.json`. Without `icon_dark` the default icon is shown in dark mode too.

From a 1024 px render on a Mac:

```bash
sips -Z 512 "<icon render>.png" --out assets/img/<app>-icon.png
```

Screenshots are the raw App Store screenshots, scaled down (598 × 1300, JPEG). To refresh them after retaking the App Store screenshots, keep the file names and replace the files:

```bash
sips -Z 1300 -s format jpeg -s formatOptions 78 "<raw screenshot>.png" --out assets/img/<name>.jpg
```

A new screenshot is added by naming it in `site.json`: as `tile_shot`, or in a feature's `shots`. The builder reads each image's width and height from the file itself. Every screenshot needs an `alt` text that says what it shows. This is also how Muninn gets screenshots once there are some: add `shots` to its features and a `tile_shot`; the page layout follows.

## Posting an App Update

Create a `.md` file in the app's folder, for example `content/semestra/v2-1-short-name.md`:

```markdown
---
version: 2.1
title: Short Release Title
date: 2026-12-01
platform: iPhone · iPad · iOS 17 or later
status: On the App Store
highlights: One-line summary shown in the RSS feed
---

One or two sentences about the version.

### New

- **Short name:** What changed, in plain words.
```

`date` is required and must be written as `YYYY-MM-DD`; the build stops with a message naming the file if it is missing or mistyped. `status` is optional. `On the App Store` is shown in green; anything else (for example `In development`) is shown in grey, and the date then reads "Updated …". Keep the changelogs true: only list what is in that version.

The newest entries also appear under "Latest Updates" on the start page and in the RSS feed (`/rss.xml`), which carries app updates only.

### Supported Markdown

The builder understands a deliberately small subset:

- Paragraphs separated by a blank line
- `### Subheading` (a single `#` is not supported; the entry's title comes from `title:`)
- `**bold**`, `*italic*`, `` `code` ``
- `[link text](https://example.com)`: links must start with `https://`, `http://`, `mailto:`, `/` or `#`, and the address must not contain a `)`
- `- ` bullet lists and `1. ` numbered lists

## Legal Pages

The privacy policies (`/semestra/privacy-policy/`, `/paradeiser/privacy-policy/`, `/muninn/privacy/`) and the imprint (`/imprint/`) are written in `build.py`, in German and English, one after the other on the same page (`#de` and `#en` jump to each). They are legal texts: change their wording only on purpose. When an app starts handling data differently, update its policy and the "Stand / Last updated" date in both languages. Semestra's app links to `https://semestra.at/privacy/`, which lives in the separate `semestra-website` repository: keep the two in step.

Each page has one main heading, the German title. The English title is therefore an `h2` and the English sections are `h3`, while the German sections are `h2`; both look the same.

## Previewing Locally

```bash
python3 build.py
python3 -m http.server -d dist
```

Then open `http://localhost:8000`. Opening the files in `dist/` directly by double-clicking does not work, because pages link to each other with site-root addresses such as `/semestra/`.

## Hosting & Deployment

The site is hosted on **GitHub Pages** at `https://lukasgeyer.com`. Pushing a commit to `main` triggers `.github/workflows/pages.yml`, which runs `python3 build.py` and deploys `dist/` automatically.
