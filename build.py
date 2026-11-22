#!/usr/bin/env python3
"""
Zero-dependency static site generator for longform writing and Semestra dispatches.
Usage: python3 build.py
"""

from __future__ import annotations

import base64
import datetime
import email.utils
import hashlib
import html
import json
import pathlib
import re
import shutil
import urllib.parse

ROOT = pathlib.Path(__file__).parent
CONTENT_WRITING = ROOT / "content" / "writing"
CONTENT_SEMESTRA = ROOT / "content" / "semestra"
CONTENT_PARADEISER = ROOT / "content" / "paradeiser"
CONTENT_MUNINN = ROOT / "content" / "muninn"
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"

# Runs in <head> before first paint so a saved (or system dark) theme never flashes.
# The saved choice always wins; the system preference is only the fallback.
# Its SHA-256 hash is written into the Content-Security-Policy (see build()).
THEME_SCRIPT = (
    "(function(){var t;try{t=localStorage.getItem('site-theme')}catch(e){}"
    "if(['paper','sepia','dusk'].indexOf(t)<0){"
    "t=window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches?'dusk':'paper'}"
    "document.documentElement.setAttribute('data-theme',t)})()"
)

ICON_SHAPES = """<rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" stroke-width="1.5"/>
      <line x1="3" y1="9" x2="21" y2="9" stroke="currentColor" stroke-width="1.3"/>
      <rect x="6" y="12" width="5" height="3" rx="0.8" fill="currentColor"/>
      <rect x="13" y="12" width="5" height="5" rx="0.8" fill="currentColor" fill-opacity="0.65"/>"""

SEMESTRA_ICON = f"""<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      {ICON_SHAPES}
    </svg>"""

PARADEISER_ICON = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <circle cx="12" cy="14" r="6.5" stroke="currentColor" stroke-width="1.6"/>
      <path d="M9 6.2L10.6 7.4L12.3 5.2L13.8 7.5L15.7 6.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>"""

MUNINN_ICON = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect x="4" y="6.5" width="13" height="11" rx="2.2" stroke="currentColor" stroke-width="1.5"/>
      <path d="M8.5 6.5V5.2C8.5 4.5 9 4 9.7 4H18.8C19.5 4 20 4.5 20 5.2V14.3C20 15 19.5 15.5 18.8 15.5H17" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      <line x1="7.5" y1="11.5" x2="13.5" y2="11.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
    </svg>"""

FAVICON_SVG = f"""<svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="32" height="32" rx="8" fill="#1F4486"/>
  <g transform="translate(4 4)" color="#F6F3EC">
      {ICON_SHAPES}
  </g>
</svg>
"""

SAFE_HREF = re.compile(r"^(https?://|mailto:|/|#)")
SCENE_BREAKS = ("***", "---", "* * *")
ORDERED_ITEM = re.compile(r"^\d+\.\s+")


# ---------------------------------------------------------------- Markdown

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
    out = html.escape(text)

    # Park `code` spans so the emphasis rules below cannot touch their contents.
    code_spans: list[str] = []

    def _stash_code(m: re.Match[str]) -> str:
        code_spans.append(m.group(1))
        return f"\x00{len(code_spans) - 1}\x00"

    def _link(m: re.Match[str]) -> str:
        label, url = m.groups()
        if not SAFE_HREF.match(url):
            return m.group(0)
        return f'<a href="{url}">{label}</a>'

    def _footnote(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in footnotes:
            return m.group(0)
        return f'<span class="fn-ref"><a id="fnref-{key}" href="#fn-{key}">[{key}]</a></span>'

    out = re.sub(r"`([^`]+)`", _stash_code, out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, out)
    out = re.sub(r"\[\^([\w-]+)\]", _footnote, out)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{code_spans[int(m.group(1))]}</code>", out)


def starts_block(line: str) -> bool:
    return (
        not line
        or line in SCENE_BREAKS
        or line.startswith(("## ", "### ", "> ", "- "))
        or bool(ORDERED_ITEM.match(line))
    )


def render_markdown(md_text: str) -> str:
    footnotes: dict[str, str] = {}
    body_lines: list[str] = []

    for line in md_text.splitlines():
        fn_match = re.match(r"^\[\^([\w-]+)\]:\s*(.+)$", line)
        if fn_match:
            footnotes[fn_match.group(1)] = fn_match.group(2).strip()
        else:
            body_lines.append(line.strip())

    def inline(text: str) -> str:
        return format_inline(text, footnotes)

    blocks: list[str] = []
    i = 0
    n = len(body_lines)

    while i < n:
        line = body_lines[i]
        if not line:
            i += 1
        elif line in SCENE_BREAKS:
            blocks.append('<hr class="scene-break" />')
            i += 1
        elif line.startswith("### "):
            blocks.append(f"<h3>{inline(line[4:])}</h3>")
            i += 1
        elif line.startswith("## "):
            blocks.append(f"<h2>{inline(line[3:])}</h2>")
            i += 1
        elif line.startswith("> "):
            quote_lines = []
            while i < n and body_lines[i].startswith("> "):
                quote_lines.append(inline(body_lines[i][2:]))
                i += 1
            blocks.append(f"<blockquote><p>{'<br />'.join(quote_lines)}</p></blockquote>")
        elif line.startswith("- "):
            items = []
            while i < n and body_lines[i].startswith("- "):
                items.append(f"<li>{inline(body_lines[i][2:])}</li>")
                i += 1
            blocks.append("<ul>\n" + "\n".join(items) + "\n</ul>")
        elif ORDERED_ITEM.match(line):
            items = []
            while i < n and ORDERED_ITEM.match(body_lines[i]):
                items.append(f"<li>{inline(ORDERED_ITEM.sub('', body_lines[i]))}</li>")
                i += 1
            blocks.append("<ol>\n" + "\n".join(items) + "\n</ol>")
        else:
            para_lines = [line]
            i += 1
            while i < n and not starts_block(body_lines[i]):
                para_lines.append(body_lines[i])
                i += 1
            blocks.append(f"<p>{inline(' '.join(para_lines))}</p>")

    if footnotes:
        fn_items = "".join(
            f'<li id="fn-{k}">{inline(v)} '
            f'<a href="#fnref-{k}" aria-label="Back to content">&crarr;</a></li>'
            for k, v in footnotes.items()
        )
        blocks.append(f'<aside class="footnotes"><ol>{fn_items}</ol></aside>')

    return "\n".join(blocks)


# ---------------------------------------------------------------- Content

def load_entries(folder: pathlib.Path) -> list[dict]:
    """Read every Markdown file in a folder, newest first. A bad date stops the build."""
    items = []
    for path in sorted(folder.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        try:
            date = datetime.date.fromisoformat(meta.get("date", ""))
        except ValueError:
            raise SystemExit(
                f"{path.relative_to(ROOT)}: 'date' must be written as YYYY-MM-DD "
                f"(found {meta.get('date')!r})"
            ) from None
        items.append(
            {
                **meta,
                "slug": path.stem,
                "title": meta.get("title", path.stem),
                "date": date,
                "body_html": render_markdown(body),
            }
        )
    items.sort(key=lambda x: x["date"], reverse=True)
    return items


def load_writings() -> list[dict]:
    items = load_entries(CONTENT_WRITING)
    for w in items:
        w["kind"] = w.get("kind", "story").lower()
        w["kind_label"] = "Short Story" if w["kind"] == "story" else "Longform Essay"
        w["url"] = f"/writing/{w['slug']}.html"
        for key, default in (("subtitle", ""), ("excerpt", ""), ("reading_time", "5 min")):
            w.setdefault(key, default)
    return items


def load_app_updates(folder: pathlib.Path, base_path: str) -> list[dict]:
    if not folder.exists():
        return []
    items = load_entries(folder)
    for u in items:
        u["url"] = f"{base_path}#{u['slug']}"
        for key, default in (("version", "1.0"), ("platform", "iOS"), ("highlights", "")):
            u.setdefault(key, default)
    return items


def load_semestra_updates() -> list[dict]:
    return load_app_updates(CONTENT_SEMESTRA, "/semestra/")


def render_changelog_section(updates: list[dict]) -> str:
    release_label = "1 Release" if len(updates) == 1 else f"{len(updates)} Releases"
    changelog_blocks = "".join(
        f"""<article class="changelog-entry" id="{u['slug']}">
  <aside class="changelog-aside">
    <div class="changelog-version">Version {html.escape(u['version'])}</div>
    <div>{time_tag(u['date'])}</div>
    <div class="changelog-platform">{html.escape(u['platform'])}</div>
  </aside>
  <div>
    <h2 class="changelog-title">{html.escape(u['title'])}</h2>
    <div class="changelog-body">
      {u['body_html']}
    </div>
  </div>
</article>"""
        for u in updates
    )
    return f"""
    <section id="changelog">
      <div class="section-bar">
        <span class="section-label">Development Updates &amp; Release Notes</span>
        <span class="section-label">{release_label}</span>
      </div>
      {changelog_blocks}
    </section>
    """


# ---------------------------------------------------------------- Template pieces

def time_tag(date: datetime.date) -> str:
    return f'<time datetime="{date.isoformat()}">{date:%b} {date.day}, {date.year}</time>'


def rfc822(date: datetime.date) -> str:
    midnight = datetime.datetime.combine(date, datetime.time(), tzinfo=datetime.timezone.utc)
    return email.utils.format_datetime(midnight)


def link_attrs(url: str) -> str:
    """href (plus new-tab attributes for external links), HTML-escaped."""
    attrs = f'href="{html.escape(url)}"'
    if url.startswith("http"):
        attrs += ' target="_blank" rel="noopener noreferrer"'
    return attrs


def writing_row(w: dict, blurb: str) -> str:
    return f"""<a href="{w['url']}" class="writing-entry" data-kind="{html.escape(w['kind'])}">
  <div class="entry-meta">
    {time_tag(w['date'])}
    <span class="entry-kind">{w['kind_label']}</span>
  </div>
  <div>
    <h2 class="entry-title">{html.escape(w['title'])}</h2>
    <p class="entry-excerpt">{html.escape(blurb)}</p>
  </div>
  <span class="entry-time">{html.escape(w['reading_time'])}</span>
</a>"""


FILTER_TABS = """<div class="filter-tabs" role="group" aria-label="Filter writing">
          <button class="filter-btn active" data-kind="all" type="button" aria-pressed="true">All</button>
          <button class="filter-btn" data-kind="story" type="button" aria-pressed="false">Stories</button>
          <button class="filter-btn" data-kind="essay" type="button" aria-pressed="false">Essays</button>
        </div>"""


def app_header(app: dict, title_tag: str = "div", icon: str = SEMESTRA_ICON, mark_class: str = "") -> str:
    cls = f"app-mark {mark_class}".strip()
    return f"""<div class="app-header">
          <div class="{cls}">{icon}</div>
          <div>
            <{title_tag} class="app-title">{html.escape(app['name'])}</{title_tag}>
            <div class="app-sub">{html.escape(app['subtitle'])}</div>
          </div>
        </div>"""


def article_nav_link(item: dict | None, label: str, cls: str = "") -> str:
    if not item:
        return "<div></div>"
    cls_attr = f' class="{cls}"' if cls else ""
    return (
        f'<a href="{item["url"]}"{cls_attr}><div class="article-nav-label">{label}</div>'
        f'<div class="article-nav-title">{html.escape(item["title"])}</div></a>'
    )


def render_newsletter(site: dict, compact: bool = False) -> str:
    nl = site.get("newsletter") or {}
    action = nl.get("action_url", "").strip()
    if not action:
        return ""
    cls = "newsletter-band compact" if compact else "newsletter-band"

    if action.lower() == "netlify":
        form_attrs = 'name="newsletter" method="POST" data-netlify="true" netlify-honeypot="bot-field" data-newsletter-mode="netlify"'
        hidden_input = (
            '<input type="hidden" name="form-name" value="newsletter" />'
            '<p hidden><label>Leave blank: <input name="bot-field" /></label></p>'
        )
    else:
        form_attrs = f'action="{html.escape(action)}" method="post" target="_blank"'
        hidden_input = ""

    return f"""
    <section class="{cls}" aria-label="Newsletter signup">
      <div>
        <div class="section-label">Dispatches</div>
        <h2 class="newsletter-title">{html.escape(nl.get('heading', 'Newsletter'))}</h2>
        <p class="newsletter-desc">{html.escape(nl.get('description', ''))}</p>
      </div>
      <div>
        <form class="newsletter-form" {form_attrs}>
          {hidden_input}
          <input
            class="newsletter-input"
            type="email"
            name="{html.escape(nl.get('email_field', 'email'))}"
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
    path: str | None,
    active_nav: str,
    content_html: str,
    description: str = "",
    og_type: str = "website",
    show_progress: bool = False,
) -> str:
    """Wrap page content in the shared shell. `path` is the page's URL path
    (e.g. "/writing/"); pass None for pages that should not be indexed (404)."""
    name = html.escape(site["name"])
    title_attr = html.escape(title)
    desc_attr = html.escape(description or site.get("tagline", ""))
    site_url = site.get("url", "").rstrip("/")

    head_meta = [
        f'<meta name="description" content="{desc_attr}" />',
        f'<meta property="og:title" content="{title_attr}" />',
        f'<meta property="og:description" content="{desc_attr}" />',
        f'<meta property="og:type" content="{og_type}" />',
        f'<meta property="og:site_name" content="{name}" />',
        '<meta name="twitter:card" content="summary" />',
    ]
    if path is None:
        head_meta.append('<meta name="robots" content="noindex" />')
    elif site_url:
        page_url = html.escape(site_url + path)
        head_meta.append(f'<meta property="og:url" content="{page_url}" />')
        head_meta.append(f'<link rel="canonical" href="{page_url}" />')

    footer_links = " ".join(
        f'<a {link_attrs(link["url"])}>{html.escape(link["label"])}</a>'
        for link in site.get("links", [])
    )
    progress_html = (
        '<div class="progress-track"><div class="progress-fill" id="progressFill"></div></div>'
        if show_progress
        else ""
    )

    def nav_attrs(key: str) -> str:
        return ' class="active" aria-current="page"' if active_nav == key else ""

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="paper">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <script>{THEME_SCRIPT}</script>
  <title>{title_attr}</title>
  {chr(10).join('  ' + tag for tag in head_meta).strip()}
  <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
  <link rel="stylesheet" href="/styles.css" />
  <link rel="alternate" type="application/rss+xml" title="{name} RSS" href="/rss.xml" />
  <script src="/reader.js" defer></script>
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  {progress_html}
  <div class="page-shell">
    <header class="masthead">
      <a href="/" class="site-brand">{name}</a>
      <div class="nav-group">
        <nav class="nav-links" aria-label="Primary">
          <a href="/writing/"{nav_attrs("writing")}>Writing</a>
          <a href="/semestra/"{nav_attrs("semestra")}>Semestra</a>
          <a href="/paradeiser/"{nav_attrs("paradeiser")}>Paradeiser</a>
          <a href="/muninn/"{nav_attrs("muninn")}>Muninn</a>
          <a href="/about/"{nav_attrs("about")}>About</a>
        </nav>
        <button class="theme-toggle" id="themeCycleBtn" type="button">Theme: Paper</button>
      </div>
    </header>

    <main id="main">
    {content_html}
    </main>

    <footer class="site-footer">
      <span>&copy; {datetime.date.today().year} {name}</span>
      <div class="footer-links">
        <a href="mailto:{html.escape(site['email'])}">Email</a>
        {footer_links}
      </div>
    </footer>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------- Build

def build() -> None:
    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    writings = load_writings()
    updates = load_semestra_updates()
    paradeiser_updates = load_app_updates(CONTENT_PARADEISER, "/paradeiser/")
    muninn_updates = load_app_updates(CONTENT_MUNINN, "/muninn/")
    sem = site["semestra"]
    site_url = site.get("url", "").rstrip("/")

    shutil.rmtree(DIST, ignore_errors=True)
    shutil.copytree(ASSETS, DIST)  # everything in assets/ is published as-is
    for folder in ("writing", "semestra", "paradeiser", "paradeiser/privacy", "muninn", "muninn/privacy", "about"):
        (DIST / folder).mkdir(parents=True, exist_ok=True)
    (DIST / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8")

    def write_page(file: str, **kwargs) -> None:
        (DIST / file).write_text(page_layout(site=site, **kwargs), encoding="utf-8")

    # 1. Home Page (dist/index.html)
    release_rows = "".join(
        f"""<a href="{u['url']}" class="release-mini-item">
  <span class="release-ver">v{html.escape(u['version'])}</span>
  <span class="release-mini-title">{html.escape(u['title'])}</span>
  <span class="release-mini-date">{time_tag(u['date'])}</span>
</a>"""
        for u in updates[:3]
    )

    home_content = f"""
    <section class="intro-band">
      <div class="kicker">{html.escape(site['kicker'])}</div>
      <h1 class="display-title">
        Longform <em>stories</em> &amp; quiet software, crafted with patience.
      </h1>
      <p class="intro-copy">{html.escape(site['intro'])}</p>
    </section>

    <section aria-label="Writing">
      <div class="section-bar">
        <span class="section-label">Recent Writing</span>
        {FILTER_TABS}
      </div>
      <div class="writing-list">
        {''.join(writing_row(w, w['excerpt']) for w in writings)}
      </div>
    </section>

    <section class="app-shelf" aria-label="Semestra iOS App">
      <div>
        {app_header(sem)}
        <p class="app-desc">{html.escape(sem['summary'])}</p>
        <div class="action-row">
          <a {link_attrs(sem['app_store_url'])} class="btn-solid">Download on App Store &#8599;</a>
          <a href="/semestra/" class="btn-outline">Release Notes &amp; Overview</a>
        </div>
      </div>

      <div>
        <div class="section-label">Latest App Updates</div>
        <div class="release-mini-list">
          {release_rows}
        </div>
      </div>
    </section>

    {render_newsletter(site)}
    """
    write_page(
        "index.html",
        title=f"{site['name']} — Writing & Semestra",
        path="/",
        active_nav="home",
        content_html=home_content,
        description=site["intro"],
    )

    # 2. Writing Archive (dist/writing/index.html)
    archive_intro = "Fiction, fragments, and occasional reflections on building software by hand."
    writing_index_html = f"""
    <section class="intro-band intro-band--tight">
      <div class="kicker">Archive</div>
      <h1 class="display-title">Stories &amp; <em>longform</em> notes.</h1>
      <p class="intro-copy">{archive_intro}</p>
    </section>

    <div class="section-bar">
      <span class="section-label">{len(writings)} Published Pieces</span>
      {FILTER_TABS}
    </div>
    <div class="writing-list">
      {''.join(writing_row(w, w['subtitle'] or w['excerpt']) for w in writings)}
    </div>
    """
    write_page(
        "writing/index.html",
        title=f"Writing — {site['name']}",
        path="/writing/",
        active_nav="writing",
        content_html=writing_index_html,
        description=archive_intro,
    )

    # 3. Individual Longform Reader Pages (dist/writing/<slug>.html)
    for idx, w in enumerate(writings):
        body_cls = "prose-body is-story" if w["kind"] == "story" else "prose-body"
        newer = writings[idx - 1] if idx > 0 else None
        older = writings[idx + 1] if idx + 1 < len(writings) else None
        subtitle_html = (
            f'<p class="article-subtitle">{html.escape(w["subtitle"])}</p>' if w["subtitle"] else ""
        )

        article_html = f"""
        <article class="reader-container">
          <div class="reader-controls">
            <a href="/writing/">&larr; All Writing</a>
            <div class="control-pills">
              <button class="ctrl-btn" data-set-theme="paper" type="button">Paper</button>
              <button class="ctrl-btn" data-set-theme="sepia" type="button">Sepia</button>
              <button class="ctrl-btn" data-set-theme="dusk" type="button">Dusk</button>
              <button class="ctrl-btn" id="fontDec" type="button" aria-label="Decrease text size">A-</button>
              <button class="ctrl-btn" id="fontInc" type="button" aria-label="Increase text size">A+</button>
              <button class="ctrl-btn" id="focusToggle" type="button" aria-pressed="false">Focus</button>
            </div>
          </div>

          <header class="article-header">
            <div class="article-meta-line">
              <span class="kind-tag">{w['kind_label']}</span>
              <span>&middot;</span>
              {time_tag(w['date'])}
              <span>&middot;</span>
              <span>{html.escape(w['reading_time'])} read</span>
            </div>
            <h1 class="article-title">{html.escape(w['title'])}</h1>
            {subtitle_html}
          </header>

          <div class="{body_cls}" id="proseBody">
            {w['body_html']}
          </div>

          {render_newsletter(site, compact=True)}

          <nav class="article-nav" aria-label="Story navigation">
            {article_nav_link(newer, "&larr; Newer")}
            {article_nav_link(older, "Older &rarr;", "article-nav-next")}
          </nav>
        </article>
        """
        write_page(
            f"writing/{w['slug']}.html",
            title=f"{w['title']} — {site['name']}",
            path=w["url"],
            active_nav="writing",
            content_html=article_html,
            description=w["excerpt"] or w["subtitle"],
            og_type="article",
            show_progress=True,
        )

    # 4. Semestra Product & Changelog Page (dist/semestra/index.html)
    support_email = html.escape(sem.get("support_email", "").strip())
    support_link = f'<a href="mailto:{support_email}">{support_email}</a>'
    support_meta_html = f"<div>Support: {support_link}</div>" if support_email else ""

    semestra_html = f"""
    <section class="semestra-hero">
      <div>
        {app_header(sem, title_tag="h1")}
        <p class="intro-copy">{html.escape(sem['summary'])}</p>
        <div class="action-row">
          <a {link_attrs(sem['app_store_url'])} class="btn-solid">View on App Store &#8599;</a>
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
          <div class="state-switch" role="group" aria-label="Schedule state">
            <button class="state-btn active" data-semestra-state="before" type="button" aria-pressed="true">Original</button>
            <button class="state-btn" data-semestra-state="after" type="button" aria-pressed="false">Rebalanced</button>
          </div>
        </div>
        <div id="semestraSchematic"></div>
      </div>
    </section>

    <section class="capabilities-grid" aria-label="Core capabilities">
      <div class="cap-item">
        <h2>Adaptive .ics &amp; Syllabus Planning</h2>
        <p>Subscribe to university timetable links or scan a syllabus photo to extract exam dates, labs, and deadlines—then automatically schedule revision around free hours.</p>
      </div>
      <div class="cap-item">
        <h2>Lock Screen Live Activities</h2>
        <p>Keep upcoming study blocks, focus timers, and exam countdowns visible on your Lock Screen and Dynamic Island while preserving personal calendar privacy.</p>
      </div>
      <div class="cap-item">
        <h2>Active Recall &amp; Spaced Review</h2>
        <p>Turn syllabus outlines into concise lesson summaries, practice quizzes, flashcards, and natural-voice audio playback tuned to what you're most likely to forget.</p>
      </div>
      <div class="cap-item">
        <h2>Shared Semesters &amp; Study Groups</h2>
        <p>Share course timetables with classmates in one tap, exchange flashcard decks, and track ECTS credits and grades with Semestra Plus.</p>
      </div>
    </section>

    {render_changelog_section(updates)}

    {render_newsletter(site, compact=True)}
    """
    write_page(
        "semestra/index.html",
        title=f"Semestra — {site['name']}",
        path="/semestra/",
        active_nav="semestra",
        content_html=semestra_html,
        description=sem["summary"],
    )

    # 4b. Paradeiser Product & Privacy Pages (dist/paradeiser/index.html & privacy)
    paradeiser = site["paradeiser"]
    paradeiser_email = html.escape(paradeiser.get("support_email", site["email"]).strip())
    paradeiser_html = f"""
    <section class="semestra-hero semestra-hero--single">
      <div>
        {app_header(paradeiser, title_tag="h1", icon=PARADEISER_ICON, mark_class="app-mark--paradeiser")}
        <p class="intro-copy">{html.escape(paradeiser['summary'])}</p>
        <div class="action-row">
          <span class="btn-solid btn-disabled" aria-disabled="true">View on App Store &#8599;</span>
          <a href="#changelog" class="btn-outline">Read Changelog</a>
        </div>
        <div class="semestra-meta">
          <div>{html.escape(paradeiser['platforms'])} &middot; {html.escape(paradeiser['pricing'])}</div>
          <div>Support: <a href="mailto:{paradeiser_email}">{paradeiser_email}</a> &middot; <a href="/paradeiser/privacy/">Privacy Policy</a></div>
        </div>
      </div>
    </section>

    <section class="capabilities-grid" aria-label="Paradeiser features">
      <div class="cap-item">
        <h2>Custom Intervals &amp; Presets</h2>
        <p>Configure any combination of focus blocks and breaks with one-minute precision—such as three 45-minute study sessions with 15-minute breaks in between—and switch presets in one tap.</p>
      </div>
      <div class="cap-item">
        <h2>Lock Screen &amp; Dynamic Island</h2>
        <p>Follow your active interval on the Lock Screen and Dynamic Island via native Live Activities, backed by a wall-clock timer that stays accurate across backgrounding and restarts.</p>
      </div>
      <div class="cap-item">
        <h2>Focus Statistics &amp; History</h2>
        <p>Track when you focused and for how long with daily and 30-day charts, streaks, and a complete day-by-day session timeline with Paradeiser Plus.</p>
      </div>
      <div class="cap-item">
        <h2>Quiet, Local &amp; Bilingual</h2>
        <p>Built natively with SwiftUI, Liquid Glass, and on-device SwiftData—available in English and German, and architected from day one for a future macOS companion app with iCloud sync.</p>
      </div>
    </section>

    {render_changelog_section(paradeiser_updates)}

    {render_newsletter(site, compact=True)}
    """
    write_page(
        "paradeiser/index.html",
        title=f"Paradeiser — {site['name']}",
        path="/paradeiser/",
        active_nav="paradeiser",
        content_html=paradeiser_html,
        description=paradeiser["summary"],
    )

    paradeiser_privacy_html = f"""
    <article class="reader-container">
      <div class="reader-controls">
        <a href="/paradeiser/">&larr; Back to Paradeiser</a>
      </div>
      <header class="article-header">
        <div class="article-meta-line">
          <span class="kind-tag">Privacy Policy</span>
          <span>&middot;</span>
          <span>Paradeiser</span>
        </div>
        <h1 class="article-title">Privacy Policy</h1>
        <p class="article-subtitle">Paradeiser is designed to keep your focus data private and on your device.</p>
      </header>
      <div class="prose-body">
        <h2>Data We Collect</h2>
        <p><strong>None.</strong> Paradeiser does not collect, sell, or share personal data, does not require an account, and does not include third-party analytics or advertising SDKs.</p>

        <h2>On-Device Storage</h2>
        <p>Your custom timer presets, preferences, and focus session history are stored locally on your device using Apple's SwiftData and UserDefaults frameworks. If iCloud Sync is enabled in a future release, your data will sync strictly through your private Apple iCloud account.</p>

        <h2>Subscriptions &amp; Purchases</h2>
        <p>Optional <strong>Paradeiser Plus</strong> subscriptions are processed directly by Apple through StoreKit and the App Store. We never receive or store your payment information. You can manage or cancel your subscription at any time in your Apple Account settings.</p>

        <h2>Notifications</h2>
        <p>If you grant notification permission, Paradeiser schedules local notifications exclusively on your device to alert you when focus or break intervals finish.</p>

        <h2>Contact</h2>
        <p>If you have any questions about this privacy policy, email <a href="mailto:{paradeiser_email}">{paradeiser_email}</a>.</p>
      </div>
    </article>
    """
    write_page(
        "paradeiser/privacy/index.html",
        title=f"Paradeiser Privacy Policy — {site['name']}",
        path="/paradeiser/privacy/",
        active_nav="paradeiser",
        content_html=paradeiser_privacy_html,
        description="Privacy Policy for the Paradeiser interval focus timer app.",
    )

    # 4c. Muninn Product & Privacy Pages (dist/muninn/index.html & privacy)
    muninn = site["muninn"]
    muninn_email = html.escape(muninn.get("support_email", site["email"]).strip())
    muninn_html = f"""
    <section class="semestra-hero semestra-hero--single">
      <div>
        {app_header(muninn, title_tag="h1", icon=MUNINN_ICON, mark_class="app-mark--muninn")}
        <p class="intro-copy">{html.escape(muninn['summary'])}</p>
        <div class="action-row">
          <span class="btn-solid btn-disabled" aria-disabled="true">View on App Store &#8599;</span>
          <a href="#changelog" class="btn-outline">Read Changelog</a>
        </div>
        <div class="semestra-meta">
          <div>{html.escape(muninn['platforms'])} &middot; {html.escape(muninn['pricing'])}</div>
          <div>Support: <a href="mailto:{muninn_email}">{muninn_email}</a> &middot; <a href="/muninn/privacy/">Privacy Policy</a></div>
        </div>
      </div>
    </section>

    <section class="capabilities-grid" aria-label="Muninn architecture and goals">
      <div class="cap-item">
        <h2>Shared Rust Core &amp; FSRS-7</h2>
        <p>A single Rust core handles the collection model, scheduling math via FSRS-7, file format, and sync—shared identically across every platform through generated native bindings.</p>
      </div>
      <div class="cap-item">
        <h2>Lossless Anki Import &amp; Export</h2>
        <p>Import existing Anki <code>.apkg</code> decks into clean native card types while preserving original templates so exporting back to Anki remains lossless.</p>
      </div>
      <div class="cap-item">
        <h2>Native on Every Platform</h2>
        <p>No sluggish web wrappers: starting with a unified SwiftUI codebase for iOS and macOS, followed by native Android, Windows, and Linux clients.</p>
      </div>
      <div class="cap-item">
        <h2>Free Core, Calm Design</h2>
        <p>Named after Odin's raven of memory, Muninn keeps spaced repetition fast, focused, and free on every platform, with an optional Plus tier for extras beyond core flashcards.</p>
      </div>
    </section>

    {render_changelog_section(muninn_updates)}

    {render_newsletter(site, compact=True)}
    """
    write_page(
        "muninn/index.html",
        title=f"Muninn — {site['name']}",
        path="/muninn/",
        active_nav="muninn",
        content_html=muninn_html,
        description=muninn["summary"],
    )

    muninn_privacy_html = f"""
    <article class="reader-container">
      <div class="reader-controls">
        <a href="/muninn/">&larr; Back to Muninn</a>
      </div>
      <header class="article-header">
        <div class="article-meta-line">
          <span class="kind-tag">Privacy Policy</span>
          <span>&middot;</span>
          <span>Muninn</span>
        </div>
        <h1 class="article-title">Privacy Policy</h1>
        <p class="article-subtitle">Muninn is built offline-first so your study collections belong to you.</p>
      </header>
      <div class="prose-body">
        <h2>Offline-First by Design</h2>
        <p>Muninn stores your flashcard decks, notes, and review history locally on your device. Muninn does not include third-party advertising or behavioral tracking.</p>

        <h2>Optional Sync</h2>
        <p>When optional cross-device sync is introduced, syncing will remain opt-in and used solely to keep your collections up to date across your own devices.</p>

        <h2>Contact</h2>
        <p>For questions about Muninn or privacy, email <a href="mailto:{muninn_email}">{muninn_email}</a>.</p>
      </div>
    </article>
    """
    write_page(
        "muninn/privacy/index.html",
        title=f"Muninn Privacy Policy — {site['name']}",
        path="/muninn/privacy/",
        active_nav="muninn",
        content_html=muninn_privacy_html,
        description="Privacy Policy for the Muninn spaced-repetition flashcard app.",
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
        f'<li><span class="aside-note">Semestra support</span>{support_link}</li>'
        if support_email
        else ""
    )
    github_aside_html = (
        f"<li><a {link_attrs(github_link)}>GitHub &#8599;</a></li>" if github_link else ""
    )
    site_email = html.escape(site["email"])

    about_html = f"""
    <section class="intro-band intro-band--tight">
      <div class="kicker">Colophon &amp; Notes</div>
      <h1 class="display-title">About {html.escape(site['name'])}.</h1>
    </section>

    <div class="about-grid">
      <div class="prose-body">
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
        <h2>Correspondence &amp; Links</h2>
        <ul>
          <li><span class="aside-note">Writing &amp; general</span><a href="mailto:{site_email}">{site_email}</a></li>
          {support_aside_html}
          <li><a {link_attrs(sem['app_store_url'])}>Semestra on the App Store &#8599;</a></li>
          {github_aside_html}
          <li><a href="/writing/">Writing Archive</a></li>
          <li><a href="/rss.xml">RSS Feed</a></li>
        </ul>
      </aside>
    </div>
    """
    write_page(
        "about/index.html",
        title=f"About — {site['name']}",
        path="/about/",
        active_nav="about",
        content_html=about_html,
    )

    # 6. Not-found page (dist/404.html — GitHub Pages serves it for unknown URLs)
    write_page(
        "404.html",
        title=f"Page not found — {site['name']}",
        path=None,
        active_nav="",
        content_html="""
    <section class="intro-band">
      <div class="kicker">Error 404</div>
      <h1 class="display-title">This page has gone <em>missing</em>.</h1>
      <p class="intro-copy">The link may be old or mistyped. Try the <a href="/">home page</a> or the <a href="/writing/">writing archive</a>.</p>
    </section>
    """,
    )

    # 7. RSS Feed (dist/rss.xml)
    feed_entries = (
        [
            {"date": w["date"], "title": w["title"], "link": site_url + w["url"], "description": w["excerpt"]}
            for w in writings
        ]
        + [
            {
                "date": u["date"],
                "title": f"Semestra {u['version']}: {u['title']}",
                "link": site_url + u["url"],
                "description": u["highlights"],
            }
            for u in updates
        ]
        + [
            {
                "date": u["date"],
                "title": f"Paradeiser {u['version']}: {u['title']}",
                "link": site_url + u["url"],
                "description": u["highlights"],
            }
            for u in paradeiser_updates
        ]
        + [
            {
                "date": u["date"],
                "title": f"Muninn {u['version']}: {u['title']}",
                "link": site_url + u["url"],
                "description": u["highlights"],
            }
            for u in muninn_updates
        ]
    )
    feed_entries.sort(key=lambda item: item["date"], reverse=True)

    permalink_attr = "true" if site_url else "false"
    rss_items = "\n".join(
        f"""  <item>
    <title>{html.escape(item['title'])}</title>
    <link>{html.escape(item['link'])}</link>
    <guid isPermaLink="{permalink_attr}">{html.escape(item['link'])}</guid>
    <pubDate>{rfc822(item['date'])}</pubDate>
    <description>{html.escape(item['description'])}</description>
  </item>"""
        for item in feed_entries
    )
    channel_links = (
        f"  <link>{html.escape(site_url)}/</link>\n"
        f'  <atom:link href="{html.escape(site_url)}/rss.xml" rel="self" type="application/rss+xml" />\n'
        if site_url
        else ""
    )
    last_build = (
        f"  <lastBuildDate>{rfc822(feed_entries[0]['date'])}</lastBuildDate>\n" if feed_entries else ""
    )

    (DIST / "rss.xml").write_text(
        f"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{html.escape(site['name'])}</title>
{channel_links}  <description>{html.escape(site['tagline'])}</description>
  <language>en</language>
{last_build}{rss_items}
</channel>
</rss>
""",
        encoding="utf-8",
    )

    # 8. robots.txt and sitemap.xml
    robots = "User-agent: *\nAllow: /\n"
    if site_url:
        sitemap_pages = [("/", None), ("/writing/", None)]
        sitemap_pages += [(w["url"], w["date"]) for w in writings]
        sitemap_pages += [
            ("/semestra/", updates[0]["date"] if updates else None),
            ("/paradeiser/", paradeiser_updates[0]["date"] if paradeiser_updates else None),
            ("/paradeiser/privacy/", None),
            ("/muninn/", muninn_updates[0]["date"] if muninn_updates else None),
            ("/muninn/privacy/", None),
            ("/about/", None),
        ]
        sitemap_urls = "\n".join(
            f"  <url><loc>{html.escape(site_url + path)}</loc>"
            + (f"<lastmod>{date.isoformat()}</lastmod>" if date else "")
            + "</url>"
            for path, date in sitemap_pages
        )
        (DIST / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{sitemap_urls}\n</urlset>\n",
            encoding="utf-8",
        )
        robots += f"Sitemap: {site_url}/sitemap.xml\n"
    (DIST / "robots.txt").write_text(robots, encoding="utf-8")

    # 9. GitHub Pages metadata (dist/.nojekyll and dist/CNAME)
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    if site_url:
        host = urllib.parse.urlsplit(site_url).hostname
        if host:
            (DIST / "CNAME").write_text(f"{host}\n", encoding="utf-8")

    print(f"Built {len(writings)} stories/essays and {len(updates)} Semestra updates into {DIST}")


if __name__ == "__main__":
    build()
