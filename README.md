# Personal Website & Semestra Log

A quiet, static longform writing site and release log for **Semestra**, compiled from plain Markdown with zero external dependencies.

## Structure

- `site.json` — Your name, kicker and intro copy, contact email, social links, newsletter config, and Semestra App Store link.
- `content/writing/*.md` — Short stories (`kind: story`) and longform essays (`kind: essay`).
- `content/semestra/*.md` — Versioned Semestra iOS release notes and development dispatches.
- `assets/` — Shared stylesheet (`styles.css`) and reader controls (`reader.js`). Every file in this folder is copied to the site root.
- `build.py` — Static site builder outputting everything into `dist/` (pages, RSS feed, sitemap, favicon, 404 page, `CNAME`, and `.nojekyll`).
- `.github/workflows/pages.yml` — GitHub Actions workflow that builds and deploys `dist/` to GitHub Pages on every push to `main`.

`dist/` is build output: never edit it by hand, and it is not stored in git.

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

## Posting a Semestra Update

Create a `.md` file in `content/semestra/` with this frontmatter, then the release notes below it:

```markdown
---
version: 2.5
title: Short Release Title
date: 2026-12-01
platform: iOS 18 · iPadOS · macOS
highlights: One-line summary shown in the RSS feed
---
```

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
