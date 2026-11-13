#!/usr/bin/env python3
"""
Zero-dependency static site generator for longform writing and Semestra dispatches.
Usage: python3 build.py
"""

from __future__ import annotations

import datetime
import email.utils
import html
import json
import pathlib
import re
import shutil
import xml.sax.saxutils as saxutils

ROOT = pathlib.Path(__file__).parent
CONTENT_WRITING = ROOT / "content" / "writing"
CONTENT_SEMESTRA = ROOT / "content" / "semestra"
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not match:
        return {}, text
    raw_meta, body = match.groups()
    meta: dict[str, str] = {}
    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body.strip()


def format_inline(text: str, footnotes: dict[str, str]) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        escaped,
    )

    def _fn_repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key in footnotes:
            return f'<span class="fn-ref"><a id="fnref-{key}" href="#fn-{key}">[{key}]</a></span>'
        return m.group(0)

    return re.sub(r"\[\^([^\]]+)\]", _fn_repl, escaped)


def render_markdown(md_text: str) -> str:
    lines = md_text.splitlines()
    footnotes: dict[str, str] = {}
    body_lines: list[str] = []

    for line in lines:
        fn_match = re.match(r"^\[\^([^\]]+)\]:\s*(.+)$", line)
        if fn_match:
            footnotes[fn_match.group(1)] = fn_match.group(2).strip()
        else:
            body_lines.append(line)

    blocks: list[str] = []
    i = 0
    n = len(body_lines)

    while i < n:
        line = body_lines[i].strip()
        if not line:
            i += 1
            continue

        if line in ("***", "---", "* * *"):
            blocks.append('<div class="scene-break" aria-hidden="true">&middot; &middot; &middot;</div>')
            i += 1
            continue

        if line.startswith("### "):
            blocks.append(f"<h3>{format_inline(line[4:], footnotes)}</h3>")
            i += 1
            continue

        if line.startswith("## "):
            blocks.append(f"<h2>{format_inline(line[3:], footnotes)}</h2>")
            i += 1
            continue

        if line.startswith("> "):
            quote_lines = []
            while i < n and body_lines[i].strip().startswith("> "):
                quote_lines.append(body_lines[i].strip()[2:])
                i += 1
            inner = "<br />".join(format_inline(q, footnotes) for q in quote_lines)
            blocks.append(f"<blockquote><p>{inner}</p></blockquote>")
            continue

        if line.startswith("- "):
            items = []
            while i < n and body_lines[i].strip().startswith("- "):
                items.append(f"<li>{format_inline(body_lines[i].strip()[2:], footnotes)}</li>")
                i += 1
            blocks.append("<ul>\n" + "\n".join(items) + "\n</ul>")
            continue

        if re.match(r"^\d+\.\s+", line):
            items = []
            while i < n and re.match(r"^\d+\.\s+", body_lines[i].strip()):
                item_text = re.sub(r"^\d+\.\s+", "", body_lines[i].strip())
                items.append(f"<li>{format_inline(item_text, footnotes)}</li>")
                i += 1
            blocks.append("<ol>\n" + "\n".join(items) + "\n</ol>")
            continue

        para_lines = []
        while i < n:
            cur = body_lines[i].strip()
            if (
                not cur
                or cur in ("***", "---", "* * *")
                or cur.startswith("## ")
                or cur.startswith("### ")
                or cur.startswith("> ")
                or cur.startswith("- ")
                or re.match(r"^\d+\.\s+", cur)
            ):
                break
            para_lines.append(cur)
            i += 1
        blocks.append(f"<p>{format_inline(' '.join(para_lines), footnotes)}</p>")

    if footnotes:
        fn_items = "".join(
            f'<li id="fn-{k}">{format_inline(v, footnotes)} '
            f'<a href="#fnref-{k}" aria-label="Back to content">&crarr;</a></li>'
            for k, v in footnotes.items()
        )
        blocks.append(f'<aside class="footnotes"><ol>{fn_items}</ol></aside>')

    return "\n".join(blocks)


def format_date(iso_date: str) -> str:
    try:
        dt = datetime.date.fromisoformat(iso_date)
        return dt.strftime("%b %d, %Y")
    except ValueError:
        return iso_date


def format_rfc822_date(iso_date: str) -> str:
    """Convert an ISO date (YYYY-MM-DD) into an RFC 822 timestamp for RSS."""
    try:
        dt = datetime.date.fromisoformat(iso_date)
        published = datetime.datetime.combine(
            dt, datetime.time(0, 0), tzinfo=datetime.timezone.utc
        )
        return email.utils.format_datetime(published)
    except ValueError:
        return iso_date


def xml_escape(text: str) -> str:
    return saxutils.escape(text, {"'": "&apos;", '"': "&quot;"})


def semestra_icon_svg(size: int = 24) -> str:
    return f"""<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="3" stroke="white" stroke-width="1.5"/>
      <line x1="3" y1="9" x2="21" y2="9" stroke="white" stroke-width="1.3"/>
      <rect x="6" y="12" width="5" height="3" rx="0.8" fill="white"/>
      <rect x="13" y="12" width="5" height="5" rx="0.8" fill="white" fill-opacity="0.65"/>
    </svg>"""


def render_newsletter(site: dict, compact: bool = False) -> str:
    nl = site.get("newsletter")
    if not nl:
        return ""
    action = nl.get("action_url", "").strip()
    email_field = nl.get("email_field", "email")
    cls = "newsletter-band compact" if compact else "newsletter-band"

    if action.lower() == "netlify":
        form_attrs = 'name="newsletter" method="POST" data-netlify="true" netlify-honeypot="bot-field" data-newsletter-mode="netlify"'
        hidden_input = (
            '<input type="hidden" name="form-name" value="newsletter" />'
            '<p style="display:none;"><label>Leave blank: <input name="bot-field" /></label></p>'
        )
    elif action:
        form_attrs = f'action="{html.escape(action)}" method="post" target="_blank"'
        hidden_input = ""
    else:
        form_attrs = 'data-newsletter-mode="demo"'
        hidden_input = ""

    return f"""
    <section class="{cls}" aria-label="Newsletter signup">
      <div>
        <div class="section-label" style="margin-bottom: 8px;">Dispatches</div>
        <h2 class="newsletter-title">{html.escape(nl.get('heading', 'Newsletter'))}</h2>
        <p class="newsletter-desc">{html.escape(nl.get('description', ''))}</p>
      </div>
      <div>
        <form class="newsletter-form" {form_attrs}>
          {hidden_input}
          <input
            class="newsletter-input"
            type="email"
            name="{html.escape(email_field)}"
            placeholder="you@example.com"
            aria-label="Email address"
            required
          />
          <button class="newsletter-btn" type="submit">{html.escape(nl.get('button_label', 'Subscribe'))}</button>
        </form>
        <div class="newsletter-footnote">{html.escape(nl.get('footnote', ''))}</div>
        <div class="newsletter-status" role="status" aria-live="polite"></div>
      </div>
    </section>
    """


def page_layout(
    *,
    title: str,
    site: dict,
    prefix: str,
    active_nav: str,
    content_html: str,
    show_progress: bool = False,
) -> str:
    name = html.escape(site["name"])
    footer_links = " ".join(
        f'<a href="{html.escape(prefix + link["url"].lstrip("/") if link["url"].startswith("/") else link["url"])}"'
        + (' target="_blank" rel="noopener noreferrer"' if link["url"].startswith("http") else "")
        + f'>{html.escape(link["label"])}</a>'
        for link in site.get("links", [])
    )
    progress_html = (
        '<div class="progress-track"><div class="progress-fill" id="progressFill"></div></div>'
        if show_progress
        else ""
    )

    def nav_cls(key: str) -> str:
        return ' class="active"' if active_nav == key else ""

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="paper">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="{prefix}styles.css" />
  <link rel="alternate" type="application/rss+xml" title="{name} RSS" href="{prefix}rss.xml" />
</head>
<body>
  {progress_html}
  <div class="page-shell">
    <header class="masthead">
      <a href="{prefix}index.html" class="site-brand">{name}</a>
      <div class="nav-group">
        <nav class="nav-links" aria-label="Primary">
          <a href="{prefix}writing/index.html"{nav_cls("writing")}>Writing</a>
          <a href="{prefix}semestra/index.html"{nav_cls("semestra")}>Semestra</a>
          <a href="{prefix}about/index.html"{nav_cls("about")}>About</a>
        </nav>
        <button class="theme-toggle" id="themeCycleBtn" type="button">Theme: Paper</button>
      </div>
    </header>

    {content_html}

    <footer class="site-footer">
      <span>&copy; 2026 {name}</span>
      <div class="footer-links">
        <a href="mailto:{html.escape(site['email'])}">Email</a>
        {footer_links}
      </div>
    </footer>
  </div>
  <script src="{prefix}reader.js"></script>
</body>
</html>
"""


def load_writings() -> list[dict]:
    items = []
    for path in sorted(CONTENT_WRITING.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        items.append(
            {
                "slug": path.stem,
                "title": meta.get("title", path.stem),
                "subtitle": meta.get("subtitle", ""),
                "kind": meta.get("kind", "story").lower(),
                "date": meta.get("date", "2026-01-01"),
                "reading_time": meta.get("reading_time", "5 min"),
                "featured": meta.get("featured", "false").lower() == "true",
                "excerpt": meta.get("excerpt", ""),
                "body_md": body,
                "body_html": render_markdown(body),
            }
        )
    items.sort(key=lambda x: x["date"], reverse=True)
    return items


def load_semestra_updates() -> list[dict]:
    items = []
    for path in sorted(CONTENT_SEMESTRA.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        items.append(
            {
                "slug": path.stem,
                "version": meta.get("version", "1.0"),
                "title": meta.get("title", path.stem),
                "date": meta.get("date", "2026-01-01"),
                "platform": meta.get("platform", "iOS"),
                "highlights": meta.get("highlights", ""),
                "body_md": body,
                "body_html": render_markdown(body),
            }
        )
    items.sort(key=lambda x: x["date"], reverse=True)
    return items


def build() -> None:
    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    writings = load_writings()
    updates = load_semestra_updates()

    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "writing").mkdir(parents=True, exist_ok=True)
    (DIST / "semestra").mkdir(parents=True, exist_ok=True)
    (DIST / "about").mkdir(parents=True, exist_ok=True)

    shutil.copy2(ASSETS / "styles.css", DIST / "styles.css")
    shutil.copy2(ASSETS / "reader.js", DIST / "reader.js")

    # 1. Home Page (dist/index.html)
    writing_rows = []
    for w in writings:
        kind_label = "Short Story" if w["kind"] == "story" else "Longform Essay"
        writing_rows.append(
            f"""<a href="writing/{w['slug']}.html" class="writing-entry" data-kind="{html.escape(w['kind'])}">
  <div class="entry-meta">
    <span>{format_date(w['date'])}</span>
    <span class="entry-kind">{kind_label}</span>
  </div>
  <div>
    <h2 class="entry-title">{html.escape(w['title'])}</h2>
    <p class="entry-excerpt">{html.escape(w['excerpt'])}</p>
  </div>
  <span class="entry-time">{html.escape(w['reading_time'])}</span>
</a>"""
        )

    release_rows = []
    for u in updates[:3]:
        release_rows.append(
            f"""<a href="semestra/index.html#{u['slug']}" class="release-mini-item">
  <span class="release-ver">v{html.escape(u['version'])}</span>
  <span class="release-mini-title">{html.escape(u['title'])}</span>
  <span class="release-mini-date">{format_date(u['date'])}</span>
</a>"""
        )

    sem = site["semestra"]
    home_content = f"""
    <section class="intro-band">
      <div class="kicker">{html.escape(site['location'])}</div>
      <h1 class="display-title">
        Longform <em>stories</em> &amp; quiet software, crafted with patience.
      </h1>
      <p class="intro-copy">{html.escape(site['intro'])}</p>
    </section>

    <section aria-label="Writing">
      <div class="section-bar">
        <span class="section-label">Recent Writing</span>
        <div class="filter-tabs" role="tablist">
          <button class="filter-btn active" data-kind="all" type="button">All</button>
          <button class="filter-btn" data-kind="story" type="button">Stories</button>
          <button class="filter-btn" data-kind="essay" type="button">Essays</button>
        </div>
      </div>
      <div class="writing-list">
        {''.join(writing_rows)}
      </div>
    </section>

    <section class="app-shelf" aria-label="Semestra iOS App">
      <div>
        <div class="app-header">
          <div class="app-mark">{semestra_icon_svg(24)}</div>
          <div>
            <div class="app-title">{html.escape(sem['name'])}</div>
            <div class="app-sub">{html.escape(sem['subtitle'])}</div>
          </div>
        </div>
        <p class="app-desc">{html.escape(sem['summary'])}</p>
        <div class="action-row">
          <a href="{html.escape(sem['app_store_url'])}" class="btn-solid" target="_blank" rel="noopener noreferrer">Download on App Store &#8599;</a>
          <a href="semestra/index.html" class="btn-outline">Release Notes &amp; Overview</a>
        </div>
      </div>

      <div>
        <div class="section-label" style="margin-bottom: 12px;">Latest App Updates</div>
        <div class="release-mini-list">
          {''.join(release_rows)}
        </div>
      </div>
    </section>

    {render_newsletter(site)}
    """
    (DIST / "index.html").write_text(
        page_layout(
            title=f"{site['name']} — Writing & Semestra",
            site=site,
            prefix="",
            active_nav="home",
            content_html=home_content,
        ),
        encoding="utf-8",
    )

    # 2. Writing Archive (dist/writing/index.html)
    archive_rows = []
    for w in writings:
        kind_label = "Short Story" if w["kind"] == "story" else "Longform Essay"
        archive_rows.append(
            f"""<a href="{w['slug']}.html" class="writing-entry" data-kind="{html.escape(w['kind'])}">
  <div class="entry-meta">
    <span>{format_date(w['date'])}</span>
    <span class="entry-kind">{kind_label}</span>
  </div>
  <div>
    <h2 class="entry-title">{html.escape(w['title'])}</h2>
    <p class="entry-excerpt">{html.escape(w['subtitle'] or w['excerpt'])}</p>
  </div>
  <span class="entry-time">{html.escape(w['reading_time'])}</span>
</a>"""
        )

    writing_index_html = f"""
    <section class="intro-band" style="margin-bottom: 40px;">
      <div class="kicker">Archive</div>
      <h1 class="display-title">Stories &amp; <em>longform</em> notes.</h1>
      <p class="intro-copy">Fiction, fragments, and occasional reflections on building software by hand.</p>
    </section>

    <div class="section-bar">
      <span class="section-label">{len(writings)} Published Pieces</span>
      <div class="filter-tabs" role="tablist">
        <button class="filter-btn active" data-kind="all" type="button">All</button>
        <button class="filter-btn" data-kind="story" type="button">Stories</button>
        <button class="filter-btn" data-kind="essay" type="button">Essays</button>
      </div>
    </div>
    <div class="writing-list">
      {''.join(archive_rows)}
    </div>
    """
    (DIST / "writing" / "index.html").write_text(
        page_layout(
            title=f"Writing — {site['name']}",
            site=site,
            prefix="../",
            active_nav="writing",
            content_html=writing_index_html,
        ),
        encoding="utf-8",
    )

    # 3. Individual Longform Reader Pages (dist/writing/<slug>.html)
    for idx, w in enumerate(writings):
        kind_label = "Short Story" if w["kind"] == "story" else "Longform Essay"
        body_cls = "prose-body is-story" if w["kind"] == "story" else "prose-body"

        prev_item = writings[idx - 1] if idx > 0 else None
        next_item = writings[idx + 1] if idx + 1 < len(writings) else None

        prev_html = (
            f'<a href="{prev_item["slug"]}.html"><div class="article-nav-label">&larr; Newer</div><div class="article-nav-title">{html.escape(prev_item["title"])}</div></a>'
            if prev_item
            else '<div></div>'
        )
        next_html = (
            f'<a href="{next_item["slug"]}.html" style="text-align:right;"><div class="article-nav-label">Older &rarr;</div><div class="article-nav-title">{html.escape(next_item["title"])}</div></a>'
            if next_item
            else '<div></div>'
        )

        article_html = f"""
        <article class="reader-container">
          <div class="reader-controls">
            <a href="index.html">&larr; All Writing</a>
            <div class="control-pills">
              <button class="ctrl-btn" data-set-theme="paper" type="button">Paper</button>
              <button class="ctrl-btn" data-set-theme="sepia" type="button">Sepia</button>
              <button class="ctrl-btn" data-set-theme="dusk" type="button">Dusk</button>
              <button class="ctrl-btn" id="fontDec" type="button" aria-label="Decrease text size">A-</button>
              <button class="ctrl-btn" id="fontInc" type="button" aria-label="Increase text size">A+</button>
              <button class="ctrl-btn" id="focusToggle" type="button">Focus</button>
            </div>
          </div>

          <header class="article-header">
            <div class="article-meta-line">
              <span class="kind-tag">{kind_label}</span>
              <span>&middot;</span>
              <span>{format_date(w['date'])}</span>
              <span>&middot;</span>
              <span>{html.escape(w['reading_time'])} read</span>
            </div>
            <h1 class="article-title">{html.escape(w['title'])}</h1>
            <p class="article-subtitle">{html.escape(w['subtitle'])}</p>
          </header>

          <div class="{body_cls}" id="proseBody">
            {w['body_html']}
          </div>

          {render_newsletter(site, compact=True)}

          <nav class="article-nav" aria-label="Story navigation">
            {prev_html}
            {next_html}
          </nav>
        </article>
        """
        (DIST / "writing" / f"{w['slug']}.html").write_text(
            page_layout(
                title=f"{w['title']} — {site['name']}",
                site=site,
                prefix="../",
                active_nav="writing",
                content_html=article_html,
                show_progress=True,
            ),
            encoding="utf-8",
        )

    # 4. Semestra Product & Changelog Page (dist/semestra/index.html)
    changelog_blocks = []
    for u in updates:
        changelog_blocks.append(
            f"""<article class="changelog-entry" id="{u['slug']}">
  <aside class="changelog-aside">
    <div class="changelog-version">Version {html.escape(u['version'])}</div>
    <div>{format_date(u['date'])}</div>
    <div style="margin-top: 6px;">{html.escape(u['platform'])}</div>
  </aside>
  <div>
    <h2 class="changelog-title">{html.escape(u['title'])}</h2>
    <div class="changelog-body">
      {u['body_html']}
    </div>
  </div>
</article>"""
        )

    support_email = sem.get("support_email", "").strip()
    support_meta_html = (
        f'<div>Support: <a href="mailto:{html.escape(support_email)}">{html.escape(support_email)}</a></div>'
        if support_email
        else ""
    )

    semestra_html = f"""
    <section class="semestra-hero">
      <div>
        <div class="app-header">
          <div class="app-mark">{semestra_icon_svg(24)}</div>
          <div>
            <div class="app-title" style="font-size: 26px;">{html.escape(sem['name'])}</div>
            <div class="app-sub">{html.escape(sem['subtitle'])}</div>
          </div>
        </div>
        <p class="intro-copy" style="margin-bottom: 24px;">{html.escape(sem['summary'])}</p>
        <div class="action-row" style="margin-bottom: 16px;">
          <a href="{html.escape(sem['app_store_url'])}" class="btn-solid" target="_blank" rel="noopener noreferrer">View on App Store &#8599;</a>
          <a href="#changelog" class="btn-outline">Read Changelog</a>
        </div>
        <div class="semestra-meta">
          <div>{html.escape(sem['platforms'])} &middot; {html.escape(sem['pricing'])}</div>
          {support_meta_html}
        </div>
      </div>

      <div class="schematic-card">
        <div class="schematic-head">
          <span id="schematicNote">Initial .ics import &middot; Exam Friday</span>
          <div class="state-switch">
            <button class="state-btn active" data-semestra-state="before" type="button">Original</button>
            <button class="state-btn" data-semestra-state="after" type="button">Rebalanced</button>
          </div>
        </div>
        <div id="semestraSchematic"></div>
      </div>
    </section>

    <section class="capabilities-grid" aria-label="Core capabilities">
      <div class="cap-item">
        <h3>Adaptive .ics &amp; Syllabus Planning</h3>
        <p>Subscribe to university timetable links or scan a syllabus photo to extract exam dates, labs, and deadlines—then automatically schedule revision around free hours.</p>
      </div>
      <div class="cap-item">
        <h3>Lock Screen Live Activities</h3>
        <p>Keep upcoming study blocks, focus timers, and exam countdowns visible on your Lock Screen and Dynamic Island while preserving personal calendar privacy.</p>
      </div>
      <div class="cap-item">
        <h3>Active Recall &amp; Spaced Review</h3>
        <p>Turn syllabus outlines into concise lesson summaries, practice quizzes, flashcards, and natural-voice audio playback tuned to what you're most likely to forget.</p>
      </div>
      <div class="cap-item">
        <h3>Shared Semesters &amp; Study Groups</h3>
        <p>Share course timetables with classmates in one tap, exchange flashcard decks, and track ECTS credits and grades with Semestra Plus.</p>
      </div>
    </section>

    <section id="changelog">
      <div class="section-bar">
        <span class="section-label">Development Updates &amp; Release Notes</span>
        <span class="section-label">{len(updates)} Releases</span>
      </div>
      {''.join(changelog_blocks)}
    </section>

    {render_newsletter(site, compact=True)}
    """
    (DIST / "semestra" / "index.html").write_text(
        page_layout(
            title=f"Semestra — {site['name']}",
            site=site,
            prefix="../",
            active_nav="semestra",
            content_html=semestra_html,
        ),
        encoding="utf-8",
    )

    # 5. About Page (dist/about/index.html)
    github_link = next(
        (
            link["url"]
            for link in site.get("links", [])
            if link.get("label", "").lower() == "github" and link.get("url")
        ),
        "",
    )
    support_aside_html = (
        f'<li><span class="aside-note">Semestra support</span>'
        f'<a href="mailto:{html.escape(support_email)}">{html.escape(support_email)}</a></li>'
        if support_email
        else ""
    )
    github_aside_html = (
        f'<li><a href="{html.escape(github_link)}" target="_blank" rel="noopener noreferrer">GitHub &#8599;</a></li>'
        if github_link
        else ""
    )

    about_html = f"""
    <section class="intro-band" style="margin-bottom: 40px;">
      <div class="kicker">Colophon &amp; Notes</div>
      <h1 class="display-title">About {html.escape(site['name'])}.</h1>
    </section>

    <div class="about-grid">
      <div class="prose-body" style="font-size: 17px;">
        <p>
          I write short stories and longform essays alongside designing and engineering
          <strong>Semestra</strong>, an independent study planner for iPhone, iPad, and Mac.
        </p>
        <p>
          This site is intentionally static and quiet: plain text compiled into clean HTML,
          set in traditional book proportions for comfortable reading on any screen.
        </p>
        <p>
          If you read a story that resonated with you—or have feedback on Semestra—I'd always love
          to hear from you.
        </p>
      </div>

      <aside class="about-aside">
        <h3>Correspondence &amp; Links</h3>
        <ul>
          <li><span class="aside-note">Writing &amp; general</span><a href="mailto:{html.escape(site['email'])}">{html.escape(site['email'])}</a></li>
          {support_aside_html}
          <li><a href="{html.escape(sem['app_store_url'])}" target="_blank" rel="noopener noreferrer">Semestra on the App Store &#8599;</a></li>
          {github_aside_html}
          <li><a href="../writing/index.html">Writing Archive</a></li>
          <li><a href="../rss.xml">RSS Feed</a></li>
        </ul>
      </aside>
    </div>
    """
    (DIST / "about" / "index.html").write_text(
        page_layout(
            title=f"About — {site['name']}",
            site=site,
            prefix="../",
            active_nav="about",
            content_html=about_html,
        ),
        encoding="utf-8",
    )

    # 6. RSS Feed (dist/rss.xml)
    site_url = site.get("url", "").rstrip("/")

    def abs_url(path: str) -> str:
        return f"{site_url}{path}" if site_url else path

    feed_entries = [
        {
            "date": w["date"],
            "title": w["title"],
            "link": abs_url(f"/writing/{w['slug']}.html"),
            "description": w["excerpt"],
        }
        for w in writings
    ] + [
        {
            "date": u["date"],
            "title": f"Semestra {u['version']}: {u['title']}",
            "link": abs_url(f"/semestra/index.html#{u['slug']}"),
            "description": u["highlights"],
        }
        for u in updates
    ]
    feed_entries.sort(key=lambda item: item["date"], reverse=True)

    permalink_attr = "true" if site_url else "false"
    rss_items = [
        f"""  <item>
    <title>{xml_escape(item['title'])}</title>
    <link>{xml_escape(item['link'])}</link>
    <guid isPermaLink="{permalink_attr}">{xml_escape(item['link'])}</guid>
    <pubDate>{format_rfc822_date(item['date'])}</pubDate>
    <description>{xml_escape(item['description'])}</description>
  </item>"""
        for item in feed_entries
    ]

    channel_link = f"  <link>{xml_escape(site_url)}/</link>\n" if site_url else ""
    atom_link = (
        f'  <atom:link href="{xml_escape(site_url)}/rss.xml" rel="self" type="application/rss+xml" />\n'
        if site_url
        else ""
    )

    rss_xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{xml_escape(site['name'])}</title>
{channel_link}{atom_link}  <description>{xml_escape(site['tagline'])}</description>
{chr(10).join(rss_items)}
</channel>
</rss>
"""
    (DIST / "rss.xml").write_text(rss_xml, encoding="utf-8")
    print(f"Built {len(writings)} stories/essays and {len(updates)} Semestra updates into {DIST}")


if __name__ == "__main__":
    build()
