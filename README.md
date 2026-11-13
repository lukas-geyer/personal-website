# Personal Website & Semestra Log

A quiet, static longform writing site and release log for **Semestra**, compiled from plain Markdown with zero external dependencies.

## Structure

- `site.json` — Your name, intro copy, contact email, social links, newsletter config, and Semestra App Store link.
- `content/writing/*.md` — Short stories (`kind: story`) and longform essays (`kind: essay`).
- `content/semestra/*.md` — Versioned Semestra iOS release notes and development dispatches.
- `assets/` — Shared stylesheet (`styles.css`) and progressive reader controls (`reader.js`).
- `build.py` — Static site builder outputting everything into `dist/`.

## Publishing a New Story or Essay

1. Create a `.md` file in `content/writing/`, for example `content/writing/winter-harbor.md`:

   ```markdown
   ---
   title: Winter Harbor
   subtitle: A short story in three parts.
   kind: story
   date: 2026-11-15
   reading_time: 8 min
   excerpt: Opening line or brief summary shown on the index.
   ---

   Your story text here. Use `***` on its own line for a scene break,
   and `[^1]` / `[^1]: Note text` for footnotes.
   ```

2. Rebuild the site:

   ```bash
   python3 build.py
   ```

## Posting a Semestra Update

Create a `.md` file in `content/semestra/` with `version`, `title`, `date`, and `platform` frontmatter, then run `python3 build.py`.

## Connecting the Newsletter Signup

In `site.json`, set `newsletter.action_url`:

- **Buttondown (recommended for indie writers, free tier):** Set `"action_url": "https://buttondown.com/api/emails/embed-subscribe/YOUR_HANDLE"`.
- **Netlify Forms (built-in if hosting on Netlify):** Set `"action_url": "netlify"`.
- **Other providers (Kit, Mailchimp, etc.):** Paste the form action URL and adjust `"email_field"` if needed.

Then run `python3 build.py`.

## Hosting & Deployment (No WordPress Needed)

Because this site builds into pure HTML/CSS/JS inside `dist/`, you don't need WordPress, a database, or PHP hosting. Free static hosts with automatic HTTPS and custom domains:

- **Netlify Drop (easiest):** Run `python3 build.py`, then drag the `dist/` folder onto `app.netlify.com/drop`.
- **Cloudflare Pages:** Connect a GitHub repo (Build command: `python3 build.py`, Output directory: `dist`) or upload `dist/` directly.
- **GitHub Pages:** Serve `dist/` directly from your repository.
