# Personal Website & Semestra Log

A quiet, static longform writing site and release log for **Semestra**, compiled from plain Markdown with zero external dependencies.

## Structure

- `site.json` — Your name, kicker and intro copy, contact email, social links, newsletter config, and Semestra App Store link.
- `content/writing/*.md` — Short stories (`kind: story`) and longform essays (`kind: essay`).
- `content/semestra/*.md` — Versioned Semestra iOS release notes and development dispatches.
- `assets/` — Shared stylesheet (`styles.css`) and reader controls (`reader.js`). Every file in this folder is copied to the site root.
- `build.py` — Static site builder outputting everything into `dist/` (pages, RSS feed, sitemap, favicon, 404 page, and the `_headers` file with the Content-Security-Policy).
- `netlify.toml` — Netlify build command and security headers.

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

- **Netlify Forms (current setup):** `"action_url": "netlify"`. Form detection must be enabled for the site in the Netlify dashboard (Forms).
- **Buttondown:** `"action_url": "https://buttondown.com/api/emails/embed-subscribe/YOUR_HANDLE"`.
- **Other providers (Kit, Mailchimp, etc.):** Paste the form action URL and adjust `"email_field"` if needed.
- **No signup form:** leave `action_url` empty.

## Hosting & Deployment

The site is hosted on **Netlify**, connected to this git repository. Pushing a commit is all it takes: Netlify runs `python3 build.py` and publishes `dist/` (both configured in `netlify.toml`).

Security headers live in two places: the fixed ones in `netlify.toml`, and the Content-Security-Policy in `dist/_headers`, which `build.py` regenerates on every build because it contains a fingerprint of the small theme script in each page's `<head>`. The policy only allows files served by this site itself, so if you ever add something loaded from another address (web fonts, analytics, embedded media), extend the policy in `build.py` as well.
