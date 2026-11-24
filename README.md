# lukasgeyer.com

The website for my apps: **Semestra** (study planner), **Paradeiser** (interval timer) and **Muninn** (flashcards, in development). A static site compiled from plain Markdown and one Python script, with no external dependencies.

## Structure

- `site.json` — Name, intro copy, contact email, links, and one block per app (name, subtitle, status, summary, platforms, pricing).
- `content/semestra/*.md`, `content/paradeiser/*.md`, `content/muninn/*.md` — One changelog entry per version.
- `content/writing/*.md` — Stories (`kind: story`) and essays (`kind: essay`). Empty right now: the Writing section and its menu item appear by themselves as soon as there is a file here.
- `assets/` — Stylesheet (`styles.css`), script (`reader.js`) and images (`img/`: app icons and screenshots). Everything in this folder is copied to the site root.
- `build.py` — The builder. It also holds the product pages, the privacy policies and the imprint, and writes everything into `dist/` (pages, RSS feed, sitemap, favicon, 404 page, `CNAME`, `.nojekyll`).
- `.github/workflows/pages.yml` — Builds and deploys `dist/` to GitHub Pages on every push to `main`.

`dist/` is build output: never edit it by hand, and it is not stored in git.

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
```

`status` is optional. `On the App Store` is shown in green; anything else (for example `In development`) is shown in grey, and the date then reads "Updated …". Keep the changelogs true: only list what is in that version.

## Legal Pages

The privacy policies (`/semestra/privacy-policy/`, `/paradeiser/privacy-policy/`, `/muninn/privacy/`) and the imprint (`/imprint/`) are written in `build.py`, in German and English. When an app starts handling data differently, update its policy and the "Stand / Last updated" date in both languages. Semestra's app links to `https://semestra.at/privacy/`, which lives in the separate `semestra-website` repository: keep the two in step.

## App Screenshots

The images in `assets/img/` are the raw App Store screenshots, scaled down (598 × 1300, JPEG). To refresh them after retaking the App Store screenshots:

```bash
sips -Z 1300 -s format jpeg -s formatOptions 78 "<raw screenshot>.png" --out assets/img/<name>.jpg
```

## Publishing a New Story or Essay

1. Create a `.md` file in `content/writing/`, for example `content/writing/winter-harbor.md`:

   ```markdown
   ---
   title: Winter Harbor
   subtitle: A short story in three parts.
   kind: story
   date: 2026-11-15
   reading_time: 8 min
   excerpt: Opening line or brief summary shown on the index, in link previews, and in the RSS feed.
   ---

   Your story text here.
   ```

   `date` is required and must be written as `YYYY-MM-DD`; the build stops with a message naming the file if it is missing or mistyped.

2. Preview locally (see below), then publish (see "Hosting & Deployment").

### Supported Markdown

The builder understands a deliberately small subset:

- Paragraphs separated by a blank line
- `## Heading` and `### Subheading` (a single `#` is not supported; the page title comes from `title:`)
- `**bold**`, `*italic*`, `` `code` ``
- `[link text](https://example.com)` — links must start with `https://`, `http://`, `mailto:`, `/` or `#`, and the address must not contain a `)`
- `- ` bullet lists and `1. ` numbered lists
- `> ` quotations
- `***` on its own line for a scene break
- Footnotes: `[^1]` in the text and `[^1]: Note text` on its own line (names may use letters, digits, `-` and `_`)

## Previewing Locally

```bash
python3 build.py
python3 -m http.server -d dist
```

Then open `http://localhost:8000`. Opening the files in `dist/` directly by double-clicking does not work, because pages link to each other with site-root addresses such as `/writing/`. The newsletter form only submits on the deployed site.

## Connecting the Newsletter Signup

In `site.json`, set `newsletter.action_url`:

- **No signup form (current setup):** leave `action_url` empty (`""`).
- **Buttondown:** `"action_url": "https://buttondown.com/api/emails/embed-subscribe/YOUR_HANDLE"`.
- **Other providers (Kit, Mailchimp, Formspree, etc.):** Paste the form action URL and adjust `"email_field"` if needed.

## Hosting & Deployment

The site is hosted on **GitHub Pages** at `https://lukasgeyer.com`. Pushing a commit to `main` triggers `.github/workflows/pages.yml`, which runs `python3 build.py` and deploys `dist/` automatically.
