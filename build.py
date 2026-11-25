#!/usr/bin/env python3
"""
Zero-dependency static site generator for lukasgeyer.com: the pages for Semestra, Paradeiser and
Muninn with their changelogs, the legal pages, and (when there is some) longform writing.
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
    release_label = "1 Version" if len(updates) == 1 else f"{len(updates)} Versions"
    changelog_blocks = "".join(
        f"""<article class="changelog-entry" id="{u['slug']}">
  <aside class="changelog-aside">
    <div class="changelog-version">Version {html.escape(u['version'])}</div>
    <div>{status_pill(u['status']) if u.get('status') else ''}</div>
    <div class="changelog-date">{'Updated ' if u.get('status', '').lower().startswith('in dev') else ''}{time_tag(u['date'])}</div>
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
        <span class="section-label">Changelog</span>
        <span class="section-label">{release_label}</span>
      </div>
      {changelog_blocks}
    </section>
    """


# ---------------------------------------------------------------- App pieces

APP_KEYS = ("semestra", "paradeiser", "muninn")

APP_SHOTS = {
    "semestra": [
        ("semestra-01-plan.jpg", "Semestra's plan: study blocks placed between lectures"),
        ("semestra-02-week.jpg", "Semestra's week view with lectures and study blocks"),
        ("semestra-05-statistics.jpg", "Semestra's statistics with progress, streak and milestones"),
    ],
    "paradeiser": [
        ("paradeiser-01-timer.jpg", "Paradeiser's timer with a focus interval under way"),
        ("paradeiser-02-statistics.jpg", "Paradeiser's statistics with the harvest basket"),
        ("paradeiser-04-market.jpg", "Paradeiser's Tomato Market with Rest Days"),
    ],
}


def app_mark(key: str) -> str:
    """The app's icon: the real artwork where there is one, a drawn mark otherwise."""
    if key == "semestra":
        return '<img class="app-icon" src="/img/semestra-icon.png" width="56" height="56" alt="" />'
    if key == "paradeiser":
        return (
            '<span class="app-icon app-icon--paradeiser">'
            '<img src="/img/paradeiser-tomato.png" width="44" height="44" alt="" /></span>'
        )
    return f'<span class="app-icon app-icon--muninn">{MUNINN_ICON}</span>'


def status_pill(text: str) -> str:
    live = text.lower().startswith("on the app store")
    cls = "status-pill status-pill--live" if live else "status-pill"
    return f'<span class="{cls}">{html.escape(text)}</span>'


def app_identity(app: dict, key: str, title_tag: str = "h2") -> str:
    return f"""<div class="app-identity">
          {app_mark(key)}
          <div>
            <{title_tag} class="app-name">{html.escape(app['name'])}</{title_tag}>
            <div class="app-sub">{html.escape(app['subtitle'])}</div>
          </div>
        </div>"""


def app_shots(key: str) -> str:
    shots = APP_SHOTS.get(key)
    if not shots:
        return ""
    figures = "".join(
        f'<figure class="shot"><img src="/img/{name}" width="598" height="1300" loading="lazy" alt="{html.escape(alt)}" /></figure>'
        for name, alt in shots
    )
    return f'<div class="shot-row" aria-label="Screenshots">{figures}</div>'


def feature_grid(label: str, features: list[tuple[str, str]]) -> str:
    items = "".join(
        f'<div class="feature-card"><h3>{title}</h3><p>{text}</p></div>' for title, text in features
    )
    return f"""
    <section class="feature-section" aria-label="{label}">
      <div class="section-bar"><span class="section-label">{label}</span></div>
      <div class="feature-grid">{items}</div>
    </section>"""


def app_page(*, app: dict, key: str, store_button: str, privacy_url: str, email: str,
             features_label: str, features: list[tuple[str, str]], updates: list[dict], extra: str = "") -> str:
    """One product page: identity and summary beside the screenshots, features, then the changelog."""
    shots = app_shots(key)
    hero_cls = "app-hero" if shots else "app-hero app-hero--single"
    return f"""
    <div class="app-page app-page--{key}">
    <section class="{hero_cls}">
      <div class="app-hero-text">
        {app_identity(app, key, title_tag="h1")}
        <div class="app-hero-status">{status_pill(app.get('status', ''))}</div>
        <p class="intro-copy">{html.escape(app['summary'])}</p>
        <div class="action-row">
          {store_button}
          <a href="#changelog" class="btn-outline">Changelog</a>
        </div>
        <dl class="app-facts">
          <div><dt>Runs on</dt><dd>{html.escape(app['platforms'])}</dd></div>
          <div><dt>Price</dt><dd>{html.escape(app['pricing'])}</dd></div>
          <div><dt>Support</dt><dd><a href="mailto:{email}">{email}</a></dd></div>
          <div><dt>Privacy</dt><dd><a href="{privacy_url}">Privacy Policy</a></dd></div>
        </dl>
      </div>
      {shots}
    </section>
    {feature_grid(features_label, features)}
    {extra}
    {render_changelog_section(updates)}
    </div>
    """


PRINCIPLES = """
    <section class="principles" aria-label="Principles">
      <div><h3>No account</h3><p>Open the app and start. There is nothing to sign up for.</p></div>
      <div><h3>No ads, no tracking</h3><p>No analytics tools and no advertising, in any of the apps.</p></div>
      <div><h3>On your device</h3><p>Your data stays on your iPhone, or in your own iCloud if you turn sync on.</p></div>
      <div><h3>German and English</h3><p>Made in Graz, for students in Austria, Germany and Switzerland.</p></div>
    </section>"""


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
    has_writing: bool = False,
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

    # The Writing section only shows while there is something in it.
    writing_nav = f'<a href="/writing/"{nav_attrs("writing")}>Writing</a>' if has_writing else ""

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
          <a href="/semestra/"{nav_attrs("semestra")}>Semestra</a>
          <a href="/paradeiser/"{nav_attrs("paradeiser")}>Paradeiser</a>
          <a href="/muninn/"{nav_attrs("muninn")}>Muninn</a>
          {writing_nav}
          <a href="/about/"{nav_attrs("about")}>About</a>
        </nav>
        <button class="theme-toggle" id="themeCycleBtn" type="button">Theme: Paper</button>
      </div>
    </header>

    <main id="main">
    {content_html}
    </main>

    <footer class="site-footer">
      <div class="footer-top">
        <span>&copy; {datetime.date.today().year} {name}</span>
        <div class="footer-links">
          <a href="mailto:{html.escape(site['email'])}">Email</a>
          {footer_links}
        </div>
      </div>
      <div class="footer-legal" aria-label="Legal">
        <a href="/imprint/">Imprint</a>
        <a href="/semestra/privacy-policy/">Semestra Privacy</a>
        <a href="/paradeiser/privacy-policy/">Paradeiser Privacy</a>
        <a href="/muninn/privacy/">Muninn Privacy</a>
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
    for folder in (
        *(["writing"] if writings else []),
        "semestra",
        "semestra/privacy-policy",
        "paradeiser",
        "paradeiser/privacy",
        "paradeiser/privacy-policy",
        "muninn",
        "muninn/privacy",
        "imprint",
        "about",
    ):
        (DIST / folder).mkdir(parents=True, exist_ok=True)
    (DIST / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8")

    def write_page(file: str, **kwargs) -> None:
        (DIST / file).write_text(page_layout(site=site, has_writing=bool(writings), **kwargs), encoding="utf-8")

    # 1. Home Page (dist/index.html)
    all_updates = sorted(
        [dict(u, app=site[key]["name"], app_key=key) for key, items in (
            ("semestra", updates), ("paradeiser", paradeiser_updates), ("muninn", muninn_updates)) for u in items],
        key=lambda u: u["date"], reverse=True,
    )
    update_rows = "".join(
        f"""<a href="{u['url']}" class="update-row">
  <span class="update-app update-app--{u['app_key']}">{html.escape(u['app'])} {html.escape(u['version'])}</span>
  <span class="update-title">{html.escape(u['title'])}</span>
  <span class="update-date">{time_tag(u['date'])}</span>
</a>"""
        for u in all_updates[:5]
    )

    def app_card(key: str) -> str:
        app = site[key]
        shots = APP_SHOTS.get(key)
        visual = (
            f'<div class="app-card-visual"><img src="/img/{shots[0][0]}" width="598" height="1300" loading="lazy" alt="{html.escape(shots[0][1])}" /></div>'
            if shots
            else f'<div class="app-card-visual app-card-visual--mark">{MUNINN_ICON}</div>'
        )
        return f"""<a href="/{key}/" class="app-card app-card--{key}">
  {visual}
  <div class="app-card-body">
    {app_identity(app, key)}
    {status_pill(app.get('status', ''))}
    <p class="app-card-summary">{html.escape(app['summary'])}</p>
    <span class="app-card-more">More about {html.escape(app['name'])} &rarr;</span>
  </div>
</a>"""

    writing_section = (
        f"""
    <section aria-label="Writing">
      <div class="section-bar">
        <span class="section-label">Recent Writing</span>
        {FILTER_TABS}
      </div>
      <div class="writing-list">
        {''.join(writing_row(w, w['excerpt']) for w in writings)}
      </div>
    </section>"""
        if writings
        else ""
    )

    home_content = f"""
    <section class="intro-band">
      <div class="kicker">{html.escape(site['kicker'])}</div>
      <h1 class="display-title">
        Calm, <em>private</em> apps that help you study.
      </h1>
      <p class="intro-copy">{html.escape(site['intro'])}</p>
    </section>

    <section aria-label="Apps">
      <div class="section-bar"><span class="section-label">The Apps</span></div>
      <div class="app-cards">
        {''.join(app_card(key) for key in APP_KEYS)}
      </div>
    </section>

    <section class="suite-band" aria-label="Semestra and Paradeiser together">
      <div>
        <div class="section-label">Better Together</div>
        <h2 class="suite-title">Semestra plans the block. Paradeiser times it.</h2>
        <p>When a study block is coming up in Semestra, Paradeiser suggests focus and break times that fit it. What you study there counts as studied in your plan. The two apps only talk to each other on your device.</p>
      </div>
      <div class="suite-marks" aria-hidden="true">{app_mark('semestra')}<span class="suite-plus">+</span>{app_mark('paradeiser')}</div>
    </section>
    {PRINCIPLES}

    <section aria-label="Latest updates">
      <div class="section-bar"><span class="section-label">Latest Updates</span></div>
      <div class="update-list">
        {update_rows}
      </div>
    </section>
    {writing_section}

    {render_newsletter(site)}
    """
    write_page(
        "index.html",
        title=f"{site['name']} — {site['kicker']}",
        path="/",
        active_nav="home",
        content_html=home_content,
        description=site["intro"],
    )

    # 2. Writing Archive (dist/writing/index.html), only while there is writing
    if writings:
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

    # 4. Semestra Product, Changelog & Privacy Policy Pages (dist/semestra/)
    support_email = html.escape(sem.get("support_email", "").strip())
    support_link = f'<a href="mailto:{support_email}">{support_email}</a>'
    semestra_html = app_page(
        app=sem,
        key="semestra",
        store_button=f'<a {link_attrs(sem["app_store_url"])} class="btn-solid">View on the App Store &#8599;</a>',
        privacy_url="/semestra/privacy-policy/",
        email=support_email,
        features_label="What Semestra Does",
        features=[
            ("Timetable in, plan out", "Subscribe to the calendar link from your university portal or import an .ics file. Semestra finds the free time in your week and plans your study blocks into it."),
            ("Exams, detected", "Exams in your timetable are recognised and added with one tap, each with its study hours, preparation time and priority."),
            ("A plan that keeps up", "When a lecture or an exam moves, the plan adjusts by itself. Finish, move or skip a block and it recalculates."),
            ("Always in view", "A reminder before each block, and the running block on the Lock Screen and in the Dynamic Island."),
            ("Works with your calendar", "Your appointments stay free, and study blocks can go into a calendar of their own."),
            ("Coming with 2.0", "A guided setup, a week view, registration deadlines, widgets, Semestra Plus and the link with Paradeiser. See the changelog below."),
        ],
        updates=updates,
    )
    write_page(
        "semestra/index.html",
        title=f"Semestra — {site['name']}",
        path="/semestra/",
        active_nav="semestra",
        content_html=semestra_html,
        description=sem["summary"],
    )

    semestra_privacy_html = f"""
    <div class="reader-container">
      <div class="reader-controls">
        <a href="/semestra/">&larr; Back to Semestra</a>
        <div class="legal-lang-links" aria-label="Language">
          <a href="#de">Deutsch</a>
          <a href="#en">English</a>
        </div>
      </div>

      <article id="de" lang="de">
        <header class="article-header">
          <div class="article-meta-line">
            <span class="kind-tag">Datenschutzerklärung</span>
            <span>&middot;</span>
            <span>Semestra</span>
            <span>&middot;</span>
            <span>Stand: 24. November 2026</span>
          </div>
          <h1 class="article-title">Datenschutzerklärung für Semestra</h1>
        </header>
        <div class="prose-body">
          <div class="legal-summary">
            <p><strong>Kurz gesagt:</strong> Semestra braucht kein Konto, enthält keine Werbung, keine Analyse- oder Tracking-Tools und betreibt keine eigenen Server. Deine Prüfungen, dein Lernplan und dein Fortschritt bleiben auf deinem Gerät – oder, wenn du die iCloud-Synchronisierung einschaltest, in deinem eigenen iCloud-Account. Ich als Entwickler habe keinen Zugriff darauf.</p>
          </div>

          <h2>1. Verantwortlicher</h2>
          <address class="legal-address">
            Lukas Geyer<br />
            Ghegagasse 13/32<br />
            8020 Graz, Österreich<br />
            E-Mail: <a href="mailto:{support_email}">{support_email}</a>
          </address>

          <h2>2. Daten auf deinem Gerät</h2>
          <p>Alles, was du in Semestra einträgst – Prüfungen, Themen, Lerneinheiten, Noten, ECTS, importierte Kalender und deine Einstellungen – wird lokal auf deinem Gerät gespeichert und dort verarbeitet. Auch wenn du Prüfungen aus einem Text oder Foto übernimmst, wird der Text auf deinem Gerät erkannt. Diese Daten werden nicht an mich oder an Dritte übertragen. Wenn du die App löschst, werden auch diese Daten gelöscht.</p>

          <h2>3. Zugriff auf deine Kalender</h2>
          <p>Wenn du es erlaubst, liest Semestra deine Kalender, um freie Zeit zum Lernen zu finden und Prüfungstermine zu erkennen, und trägt deine Lerneinheiten in einen eigenen Kalender ein. Das passiert ausschließlich auf deinem Gerät. Du kannst den Zugriff jederzeit in den iOS-Einstellungen unter <em>Datenschutz &amp; Sicherheit &rsaquo; Kalender</em> widerrufen.</p>

          <h2>4. Kalender-Abos und importierte Dateien</h2>
          <p>Du kannst Kalenderdateien (.ics) importieren oder eine Kalender-Adresse abonnieren, etwa von deiner Hochschule. Bei einem Abo lädt Semestra den Kalender direkt von der Adresse, die du angegeben hast. Dabei erhält der Server dieser Adresse – wie bei jedem Aufruf im Internet – technische Daten wie deine IP-Adresse. Für diese Verarbeitung ist der Betreiber des jeweiligen Servers verantwortlich; es gilt dessen Datenschutzerklärung. Ich erhalte dabei keine Daten.</p>

          <h2>5. iCloud-Synchronisierung (optional)</h2>
          <p>Mit Semestra Plus kannst du deine Daten über iCloud auf deinen Geräten synchronisieren. Die Daten werden dann in der privaten Datenbank deines iCloud-Accounts bei Apple gespeichert. Nur du hast darauf Zugriff, ich nicht. Es gilt die <a href="https://www.apple.com/at/legal/privacy/" target="_blank" rel="noopener noreferrer">Datenschutzrichtlinie von Apple</a>. Du kannst die Synchronisierung in den Einstellungen von Semestra ausschalten und die gespeicherten Daten in den iOS-Einstellungen unter <em>[Dein Name] &rsaquo; iCloud &rsaquo; Speicher verwalten</em> löschen.</p>

          <h2>6. Käufe und Abos</h2>
          <p>Käufe von Semestra Plus (Monats- oder Jahresabo oder Einmalkauf) werden vollständig von Apple über den App Store abgewickelt. Ich erhalte keine Zahlungsdaten und keine Daten, die dich persönlich identifizieren. Die App prüft auf deinem Gerät nur, ob ein aktives Abo oder ein Einmalkauf besteht.</p>

          <h2>7. Mitteilungen, Widgets und Siri</h2>
          <p>Erinnerungen an Lerneinheiten werden als lokale Mitteilungen auf deinem Gerät geplant. Widgets und Live-Aktivitäten zeigen Daten an, die auf deinem Gerät bleiben. Wenn du Siri oder Kurzbefehle mit Semestra verwendest, verarbeitet Apple deine Anfragen gemäß der Datenschutzrichtlinie von Apple.</p>

          <h2>8. Export und Teilen</h2>
          <p>Wenn du deinen Lernplan als PDF oder Kalenderdatei exportierst, entscheidest du selbst, wohin die Datei geht. Semestra versendet dabei nichts von sich aus.</p>

          <h2>9. Verbindung mit Paradeiser (optional)</h2>
          <p>Wenn auf demselben Gerät auch <a href="/paradeiser/">Paradeiser</a> installiert ist, mein Intervall-Timer, tauschen die beiden Apps Daten aus: Semestra stellt Paradeiser deine anstehenden Lernblöcke bereit (Name der Prüfung, Thema, Beginn und Ende), und Paradeiser meldet zurück, wann und wie lange du dafür fokussiert warst. Der Austausch läuft ausschließlich auf deinem Gerät, über einen gemeinsamen, geschützten Speicherbereich der beiden Apps (App Group). Es wird nichts an mich oder an Dritte übertragen. Du kannst die Verbindung in den Einstellungen von Semestra unter <em>Paradeiser</em> ausschalten. Ohne Paradeiser auf dem Gerät liest diese Daten niemand.</p>

          <h2>10. Absturzberichte und Statistiken von Apple</h2>
          <p>Wenn du in den iOS-Einstellungen zugestimmt hast, Analysedaten mit App-Entwicklern zu teilen, stellt Apple mir anonymisierte Absturzberichte und zusammengefasste Nutzungsstatistiken (z.&nbsp;B. Anzahl der Installationen) zur Verfügung. Daraus kann ich keine Rückschlüsse auf dich als Person ziehen. Du kannst das unter <em>Datenschutz &amp; Sicherheit &rsaquo; Analyse &amp; Verbesserungen</em> ausschalten.</p>

          <h2>11. Diese Website</h2>
          <p>Beim Aufruf von lukasgeyer.com (sowie semestra.at) verarbeitet der Hosting-Anbieter GitHub, Inc. (USA) über GitHub Pages technisch notwendige Daten wie deine IP-Adresse, Datum und Uhrzeit sowie die aufgerufene Seite, um die Website auszuliefern und abzusichern (Art. 6 Abs. 1 lit. f DSGVO). GitHub kann diese Daten in den USA verarbeiten; die Übermittlung stützt sich auf das EU-US Data Privacy Framework. Näheres in der <a href="https://docs.github.com/de/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener noreferrer">Datenschutzerklärung von GitHub</a>. Die Website verwendet keine Cookies und keine Analyse-Tools.</p>

          <h2>12. Deine Rechte</h2>
          <p>Du hast nach der DSGVO das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit und Widerspruch. Da ich keine personenbezogenen Daten über dich speichere, kann ich dir in der Regel nur bestätigen, dass keine vorhanden sind. Schreib mir dazu gern an die oben genannte E-Mail-Adresse.</p>
          <p>Außerdem kannst du dich bei der Aufsichtsbehörde beschweren. In Österreich ist das die <a href="https://www.dsb.gv.at" target="_blank" rel="noopener noreferrer">Österreichische Datenschutzbehörde</a>, Barichgasse 40–42, 1030 Wien.</p>

          <h2>13. Änderungen</h2>
          <p>Wenn sich Semestra ändert, passe ich diese Datenschutzerklärung an. Es gilt jeweils die hier veröffentlichte Fassung. Weitere Angaben findest du im <a href="/imprint/">Impressum</a>.</p>
        </div>
      </article>

      <hr class="legal-divider" />

      <article id="en" lang="en">
        <header class="article-header">
          <div class="article-meta-line">
            <span class="kind-tag">Privacy Policy</span>
            <span>&middot;</span>
            <span>Semestra</span>
            <span>&middot;</span>
            <span>Last updated: 24 November 2026</span>
          </div>
          <h1 class="article-title">Semestra Privacy Policy</h1>
        </header>
        <div class="prose-body">
          <div class="legal-summary">
            <p><strong>In short:</strong> Semestra needs no account, shows no ads, contains no analytics or tracking tools and runs no servers of its own. Your exams, study plan and progress stay on your device – or, if you turn on iCloud sync, in your own iCloud account. I, the developer, have no access to them.</p>
          </div>

          <h2>1. Controller</h2>
          <address class="legal-address">
            Lukas Geyer<br />
            Ghegagasse 13/32<br />
            8020 Graz, Austria<br />
            Email: <a href="mailto:{support_email}">{support_email}</a>
          </address>

          <h2>2. Data on your device</h2>
          <p>Everything you enter in Semestra – exams, topics, study sessions, grades, ECTS credits, imported calendars and your settings – is stored and processed locally on your device. When you add exams from text or a photo, the text is also read on your device. It is not sent to me or to any third party. Deleting the app deletes this data.</p>

          <h2>3. Access to your calendars</h2>
          <p>If you allow it, Semestra reads your calendars to find free time for studying and to detect exam dates, and adds your study blocks to a separate calendar. This happens only on your device. You can revoke access at any time in iOS Settings under <em>Privacy &amp; Security &rsaquo; Calendars</em>.</p>

          <h2>4. Calendar subscriptions and imported files</h2>
          <p>You can import calendar files (.ics) or subscribe to a calendar address, for example from your university. For a subscription, Semestra downloads the calendar directly from the address you entered. Like any request on the internet, this gives that server technical data such as your IP address. The operator of that server is responsible for this processing, and its privacy policy applies. I receive no data from this.</p>

          <h2>5. iCloud sync (optional)</h2>
          <p>With Semestra Plus you can sync your data across your devices via iCloud. The data is then stored in the private database of your iCloud account at Apple. Only you can access it, not me. <a href="https://www.apple.com/legal/privacy/" target="_blank" rel="noopener noreferrer">Apple's Privacy Policy</a> applies. You can turn sync off in Semestra's settings and delete the stored data in iOS Settings under <em>[Your Name] &rsaquo; iCloud &rsaquo; Manage Storage</em>.</p>

          <h2>6. Purchases and subscriptions</h2>
          <p>Purchases of Semestra Plus (a monthly or yearly subscription, or a one-time purchase) are handled entirely by Apple through the App Store. I receive no payment details and no data that identifies you personally. The app only checks on your device whether a subscription or the one-time purchase is active.</p>

          <h2>7. Notifications, widgets and Siri</h2>
          <p>Study reminders are scheduled as local notifications on your device. Widgets and Live Activities show data that stays on your device. If you use Siri or Shortcuts with Semestra, Apple processes your requests under Apple's Privacy Policy.</p>

          <h2>8. Export and sharing</h2>
          <p>When you export your study plan as a PDF or calendar file, you decide where the file goes. Semestra doesn't send anything on its own.</p>

          <h2>9. Link with Paradeiser (optional)</h2>
          <p>If <a href="/paradeiser/">Paradeiser</a>, my interval timer, is installed on the same device, the two apps exchange data: Semestra makes your upcoming study blocks available to Paradeiser (the exam's name, the topic, start and end), and Paradeiser reports back when and for how long you focused on them. This exchange happens only on your device, through a protected storage area the two apps share (an App Group). Nothing is sent to me or to any third party. You can turn the link off in Semestra's settings under <em>Paradeiser</em>. Without Paradeiser on the device, nobody reads this data.</p>

          <h2>10. Crash reports and statistics from Apple</h2>
          <p>If you agreed in iOS Settings to share analytics with app developers, Apple gives me anonymised crash reports and aggregated usage statistics (such as the number of installs). These don't let me identify you. You can turn this off under <em>Privacy &amp; Security &rsaquo; Analytics &amp; Improvements</em>.</p>

          <h2>11. This website</h2>
          <p>When you visit lukasgeyer.com (as well as semestra.at), the hosting provider GitHub, Inc. (USA) processes, through GitHub Pages, technically necessary data such as your IP address, the date and time and the page requested, in order to deliver and secure the website (Art. 6(1)(f) GDPR). GitHub may process this data in the USA; the transfer relies on the EU-U.S. Data Privacy Framework. See <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener noreferrer">GitHub's privacy statement</a>. The website uses no cookies and no analytics tools.</p>

          <h2>12. Your rights</h2>
          <p>Under the GDPR you have the right of access, rectification, erasure, restriction of processing, data portability and objection. Since I store no personal data about you, I can usually only confirm that there is none. Just write to the email address above.</p>
          <p>You also have the right to lodge a complaint with a supervisory authority. In Austria this is the <a href="https://www.dsb.gv.at" target="_blank" rel="noopener noreferrer">Austrian Data Protection Authority</a> (Datenschutzbehörde), Barichgasse 40–42, 1030 Vienna.</p>

          <h2>13. Changes</h2>
          <p>If Semestra changes, I will update this privacy policy. The version published here always applies. See the <a href="/imprint/#en">legal notice</a> for provider details.</p>
        </div>
      </article>
    </div>
    """
    write_page(
        "semestra/privacy-policy/index.html",
        title=f"Semestra Privacy Policy — {site['name']}",
        path="/semestra/privacy-policy/",
        active_nav="semestra",
        content_html=semestra_privacy_html,
        description="Datenschutzerklärung der App Semestra / Privacy policy of the Semestra app.",
    )

    # 4b. Paradeiser Product & Privacy Pages (dist/paradeiser/index.html & privacy)
    paradeiser = site["paradeiser"]
    paradeiser_email = html.escape(paradeiser.get("support_email", site["email"]).strip())
    paradeiser_html = app_page(
        app=paradeiser,
        key="paradeiser",
        store_button='<span class="btn-solid btn-disabled" aria-disabled="true">Coming to the App Store</span>',
        privacy_url="/paradeiser/privacy-policy/",
        email=paradeiser_email,
        features_label="What Paradeiser Does",
        features=[
            ("Your own intervals", "Any combination of focus blocks and breaks, such as three 45-minute blocks with 15-minute breaks, saved as presets you switch with one tap."),
            ("Keeps running", "The timer follows the clock, so it stays right when the app is closed or the iPhone is locked."),
            ("Lock Screen and Dynamic Island", "The running interval as a Live Activity, with buttons to pause, resume and skip."),
            ("Tomatoes and streaks", "With Paradeiser Plus, every focus round earns tomatoes, days in a row build a streak, and Rest Days protect it."),
            ("Statistics", "With Plus: focus time per day and week, focus tags, a daily goal, and logging to Apple Calendar and Apple Health."),
            ("Works with Semestra", "Paradeiser suggests focus and break times for your next study block, and the time counts as studied in your plan."),
        ],
        updates=paradeiser_updates,
    )
    write_page(
        "paradeiser/index.html",
        title=f"Paradeiser — {site['name']}",
        path="/paradeiser/",
        active_nav="paradeiser",
        content_html=paradeiser_html,
        description=paradeiser["summary"],
    )

    paradeiser_privacy_html = f"""
    <div class="reader-container">
      <div class="reader-controls">
        <a href="/paradeiser/">&larr; Back to Paradeiser</a>
        <div class="legal-lang-links" aria-label="Language">
          <a href="#de">Deutsch</a>
          <a href="#en">English</a>
        </div>
      </div>

      <article id="de" lang="de">
        <header class="article-header">
          <div class="article-meta-line">
            <span class="kind-tag">Datenschutzerklärung</span>
            <span>&middot;</span>
            <span>Paradeiser</span>
            <span>&middot;</span>
            <span>Stand: 24. November 2026</span>
          </div>
          <h1 class="article-title">Datenschutzerklärung für Paradeiser</h1>
        </header>
        <div class="prose-body">
          <div class="legal-summary">
            <p><strong>Kurz gesagt:</strong> Paradeiser braucht kein Konto, enthält keine Werbung, keine Analyse- oder Tracking-Tools und betreibt keine eigenen Server. Deine Fokus-Sitzungen, Presets, Tags, Meilensteine und Einstellungen bleiben auf deinem Gerät. Ich als Entwickler habe keinen Zugriff darauf.</p>
          </div>

          <h2>1. Verantwortlicher</h2>
          <address class="legal-address">
            Lukas Geyer<br />
            Ghegagasse 13/32<br />
            8020 Graz, Österreich<br />
            E-Mail: <a href="mailto:{paradeiser_email}">{paradeiser_email}</a>
          </address>

          <h2>2. Daten auf deinem Gerät</h2>
          <p>Alles, was du in Paradeiser anlegst und aufzeichnest – eigene Zeitpläne und Presets, Fokus-Tags, abgeschlossene Fokus-Sitzungen, dein Tagesziel, Serien, Meilensteine, freigeschaltete Paradeiser-Sorten und deine Einstellungen – wird lokal auf deinem Gerät (über SwiftData und UserDefaults) gespeichert und verarbeitet. Diese Daten werden nicht an mich oder an Dritte übertragen. Wenn du die App löschst, werden auch diese Daten gelöscht.</p>

          <h2>3. Apple Kalender (optional)</h2>
          <p>Wenn du die Kalender-Synchronisierung mit Paradeiser Plus einschaltest und den Zugriff erlaubst, trägt Paradeiser abgeschlossene Fokus-Sitzungen als Ereignisse in den von dir gewählten Kalender ein. Das passiert ausschließlich auf deinem Gerät. Du kannst den Zugriff jederzeit in den iOS-Einstellungen unter <em>Datenschutz &amp; Sicherheit &rsaquo; Kalender</em> widerrufen.</p>

          <h2>4. Apple Health (optional)</h2>
          <p>Wenn du die Apple-Health-Synchronisierung einschaltest und den Schreibzugriff erlaubst, speichert Paradeiser abgeschlossene Fokus-Sitzungen lokal auf deinem Gerät als Achtsamkeitsminuten (<em>Mindful Minutes</em>) in Apple Health. Paradeiser liest keine Gesundheitsdaten aus und gibt niemals Daten aus Apple Health an mich oder an Dritte weiter. Du kannst die Berechtigung jederzeit in der Health-App oder in den iOS-Einstellungen widerrufen.</p>

          <h2>5. Verbindung mit Semestra (optional)</h2>
          <p>Wenn auf demselben Gerät auch <a href="/semestra/">Semestra</a> installiert ist, mein Lernplaner, tauschen die beiden Apps Daten aus: Semestra stellt Paradeiser deine anstehenden Lernblöcke bereit (Name der Prüfung, Thema, Beginn und Ende), damit Paradeiser dafür passende Fokus- und Pausenzeiten vorschlagen kann, und Paradeiser meldet zurück, wann und wie lange du dafür fokussiert warst. Der Austausch läuft ausschließlich auf deinem Gerät, über einen gemeinsamen, geschützten Speicherbereich der beiden Apps (App Group). Es wird nichts an mich oder an Dritte übertragen. Du kannst die Verbindung in den Einstellungen von Paradeiser unter <em>Integrationen</em> ausschalten.</p>

          <h2>6. Fotos und Teilen von Stickern (optional)</h2>
          <p>Wenn du einen Paradeiser-Sticker in deinen Fotos speicherst, fragt Paradeiser ausschließlich nach der Berechtigung zum Hinzufügen neuer Bilder (<em>Nur Fotos hinzufügen</em>), ohne auf deine bestehenden Fotos zuzugreifen. Wenn du Sticker oder deinen Wochenrückblick kopierst oder teilst, entscheidest du selbst, wohin die Inhalte gehen. Paradeiser versendet dabei nichts von sich aus.</p>

          <h2>7. Käufe und Abos</h2>
          <p>Käufe von Paradeiser Plus (Monats-, Jahres- oder Lebenslang-Zugang) werden vollständig von Apple über den App Store (StoreKit) abgewickelt. Ich erhalte keine Zahlungsdaten und keine Daten, die dich persönlich identifizieren. Die App prüft auf deinem Gerät nur, ob ein aktiver Zugang besteht.</p>

          <h2>8. Mitteilungen und Live-Aktivitäten</h2>
          <p>Hinweise zum Abschluss von Fokus- oder Pausenphasen werden als lokale Mitteilungen auf deinem Gerät geplant. Live-Aktivitäten auf dem Sperrbildschirm und in der Dynamic Island zeigen Timer-Daten an, die vollständig auf deinem Gerät bleiben.</p>

          <h2>9. Absturzberichte und Statistiken von Apple</h2>
          <p>Wenn du in den iOS-Einstellungen zugestimmt hast, Analysedaten mit App-Entwicklern zu teilen, stellt Apple mir anonymisierte Absturzberichte und zusammengefasste Nutzungsstatistiken (z.&nbsp;B. Anzahl der Installationen) zur Verfügung. Daraus kann ich keine Rückschlüsse auf dich als Person ziehen. Du kannst das unter <em>Datenschutz &amp; Sicherheit &rsaquo; Analyse &amp; Verbesserungen</em> ausschalten.</p>

          <h2>10. Diese Website</h2>
          <p>Beim Aufruf von lukasgeyer.com verarbeitet der Hosting-Anbieter GitHub, Inc. (USA) über GitHub Pages technisch notwendige Daten wie deine IP-Adresse, Datum und Uhrzeit sowie die aufgerufene Seite, um die Website auszuliefern und abzusichern (Art. 6 Abs. 1 lit. f DSGVO). GitHub kann diese Daten in den USA verarbeiten; die Übermittlung stützt sich auf das EU-US Data Privacy Framework. Näheres in der <a href="https://docs.github.com/de/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener noreferrer">Datenschutzerklärung von GitHub</a>. Die Website verwendet keine Cookies und keine Analyse-Tools.</p>

          <h2>11. Deine Rechte</h2>
          <p>Du hast nach der DSGVO das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit und Widerspruch. Da ich keine personenbezogenen Daten über dich speichere, kann ich dir in der Regel nur bestätigen, dass keine vorhanden sind. Schreib mir dazu gern an die oben genannte E-Mail-Adresse.</p>
          <p>Außerdem kannst du dich bei der Aufsichtsbehörde beschweren. In Österreich ist das die <a href="https://www.dsb.gv.at" target="_blank" rel="noopener noreferrer">Österreichische Datenschutzbehörde</a>, Barichgasse 40–42, 1030 Wien.</p>

          <h2>12. Änderungen</h2>
          <p>Wenn sich Paradeiser ändert, passe ich diese Datenschutzerklärung an. Es gilt jeweils die hier veröffentlichte Fassung. Weitere Angaben findest du im <a href="/imprint/">Impressum</a>.</p>
        </div>
      </article>

      <hr class="legal-divider" />

      <article id="en" lang="en">
        <header class="article-header">
          <div class="article-meta-line">
            <span class="kind-tag">Privacy Policy</span>
            <span>&middot;</span>
            <span>Paradeiser</span>
            <span>&middot;</span>
            <span>Last updated: 24 November 2026</span>
          </div>
          <h1 class="article-title">Paradeiser Privacy Policy</h1>
        </header>
        <div class="prose-body">
          <div class="legal-summary">
            <p><strong>In short:</strong> Paradeiser needs no account, shows no ads, contains no analytics or tracking tools and runs no servers of its own. Your focus sessions, presets, tags, milestones and settings stay on your device. I, the developer, have no access to them.</p>
          </div>

          <h2>1. Controller</h2>
          <address class="legal-address">
            Lukas Geyer<br />
            Ghegagasse 13/32<br />
            8020 Graz, Austria<br />
            Email: <a href="mailto:{paradeiser_email}">{paradeiser_email}</a>
          </address>

          <h2>2. Data on your device</h2>
          <p>Everything you create and record in Paradeiser – custom schedules and presets, focus tags, completed focus sessions, daily goals, streaks, milestones, unlocked tomato varieties and your settings – is stored and processed locally on your device using Apple's SwiftData and UserDefaults frameworks. It is not sent to me or to any third party. Deleting the app deletes this data.</p>

          <h2>3. Apple Calendar (optional)</h2>
          <p>If you turn on Calendar sync with Paradeiser Plus and grant permission, Paradeiser saves your completed focus sessions as events in the calendar you select. This happens strictly on your device. You can revoke access at any time in iOS Settings under <em>Privacy &amp; Security &rsaquo; Calendars</em>.</p>

          <h2>4. Apple Health (optional)</h2>
          <p>If you turn on Apple Health sync and grant write permission, Paradeiser records completed focus sessions locally on your device as Mindful Minutes in Apple Health. Paradeiser never reads Health data and never shares Health data with me or any third party. You can revoke permission at any time in the Health app or iOS Settings.</p>

          <h2>5. Link with Semestra (optional)</h2>
          <p>If <a href="/semestra/">Semestra</a>, my study planner, is installed on the same device, the two apps exchange data: Semestra makes your upcoming study blocks available to Paradeiser (the exam's name, the topic, start and end) so that Paradeiser can suggest focus and break times that fit them, and Paradeiser reports back when and for how long you focused on them. This exchange happens only on your device, through a protected storage area the two apps share (an App Group). Nothing is sent to me or to any third party. You can turn the link off in Paradeiser's settings under <em>Integrations</em>.</p>

          <h2>6. Photos and sticker sharing (optional)</h2>
          <p>When you save a Paradeiser sticker to your Photo Library, Paradeiser requests add-only permission solely to write the PNG image and cannot read your existing photos. When you copy or share a sticker or weekly recap, you decide where it goes. Paradeiser never sends anything on its own.</p>

          <h2>7. Purchases and subscriptions</h2>
          <p>Purchases of Paradeiser Plus (monthly, yearly or lifetime) are handled entirely by Apple through the App Store (StoreKit). I receive no payment details and no data that identifies you personally. The app only checks on your device whether an entitlement is active.</p>

          <h2>8. Notifications and Live Activities</h2>
          <p>Phase completion alerts are scheduled as local notifications on your device. Lock Screen and Dynamic Island Live Activities display timer state that stays entirely on your device.</p>

          <h2>9. Crash reports and statistics from Apple</h2>
          <p>If you agreed in iOS Settings to share analytics with app developers, Apple gives me anonymised crash reports and aggregated usage statistics (such as the number of installs). These don't let me identify you. You can turn this off under <em>Privacy &amp; Security &rsaquo; Analytics &amp; Improvements</em>.</p>

          <h2>10. This website</h2>
          <p>When you visit lukasgeyer.com, the hosting provider GitHub, Inc. (USA) processes, through GitHub Pages, technically necessary data such as your IP address, the date and time and the page requested, in order to deliver and secure the website (Art. 6(1)(f) GDPR). GitHub may process this data in the USA; the transfer relies on the EU-U.S. Data Privacy Framework. See <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener noreferrer">GitHub's privacy statement</a>. The website uses no cookies and no analytics tools.</p>

          <h2>11. Your rights</h2>
          <p>Under the GDPR you have the right of access, rectification, erasure, restriction of processing, data portability and objection. Since I store no personal data about you, I can usually only confirm that there is none. Just write to the email address above.</p>
          <p>You also have the right to lodge a complaint with a supervisory authority. In Austria this is the <a href="https://www.dsb.gv.at" target="_blank" rel="noopener noreferrer">Austrian Data Protection Authority</a> (Datenschutzbehörde), Barichgasse 40–42, 1030 Vienna.</p>

          <h2>12. Changes</h2>
          <p>If Paradeiser changes, I will update this privacy policy. The version published here always applies. See the <a href="/imprint/#en">legal notice</a> for provider details.</p>
        </div>
      </article>
    </div>
    """
    write_page(
        "paradeiser/privacy-policy/index.html",
        title=f"Paradeiser Privacy Policy — {site['name']}",
        path="/paradeiser/privacy-policy/",
        active_nav="paradeiser",
        content_html=paradeiser_privacy_html,
        description="Datenschutzerklärung der App Paradeiser / Privacy policy of the Paradeiser app.",
    )

    # Keep /paradeiser/privacy/ redirecting cleanly to /paradeiser/privacy-policy/ for backwards compatibility.
    (DIST / "paradeiser" / "privacy" / "index.html").write_text(
        """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="robots" content="noindex" />
  <meta http-equiv="refresh" content="0; url=/paradeiser/privacy-policy/" />
  <link rel="canonical" href="https://lukasgeyer.com/paradeiser/privacy-policy/" />
  <title>Redirecting to Paradeiser Privacy Policy…</title>
</head>
<body>
  <p>Redirecting to <a href="/paradeiser/privacy-policy/">Paradeiser Privacy Policy</a>…</p>
</body>
</html>
""",
        encoding="utf-8",
    )

    # 4c. Muninn Product & Privacy Pages (dist/muninn/index.html & privacy)
    muninn = site["muninn"]
    muninn_email = html.escape(muninn.get("support_email", site["email"]).strip())
    muninn_html = app_page(
        app=muninn,
        key="muninn",
        store_button='<span class="btn-solid btn-disabled" aria-disabled="true">Not available yet</span>',
        privacy_url="/muninn/privacy/",
        email=muninn_email,
        features_label="The Plan for Muninn",
        features=[
            ("One shared core", "A single Rust core holds the collection model, the scheduling and the file format, so every platform behaves the same."),
            ("FSRS-7 scheduling", "A modern spaced-repetition scheduler tuned for long-term retention, without settings to babysit."),
            ("Anki decks welcome", "Existing Anki decks are to be imported into clean native card types, keeping their templates so they can go back to Anki unchanged."),
            ("Native apps", "No web wrappers: iOS and macOS first from one SwiftUI codebase, then Android, Windows and Linux."),
        ],
        updates=muninn_updates,
    )
    write_page(
        "muninn/index.html",
        title=f"Muninn — {site['name']}",
        path="/muninn/",
        active_nav="muninn",
        content_html=muninn_html,
        description=muninn["summary"],
    )

    muninn_privacy_html = f"""
    <div class="reader-container">
      <div class="reader-controls">
        <a href="/muninn/">&larr; Back to Muninn</a>
        <div class="legal-lang-links" aria-label="Language">
          <a href="#de">Deutsch</a>
          <a href="#en">English</a>
        </div>
      </div>

      <article id="de" lang="de">
        <header class="article-header">
          <div class="article-meta-line">
            <span class="kind-tag">Datenschutzerklärung</span>
            <span>&middot;</span>
            <span>Muninn</span>
            <span>&middot;</span>
            <span>Stand: 25. November 2026</span>
          </div>
          <h1 class="article-title">Datenschutzerklärung für Muninn</h1>
        </header>
        <div class="prose-body">
          <div class="legal-summary">
            <p><strong>Kurz gesagt:</strong> Muninn braucht kein Konto, enthält keine Werbung, keine Analyse- oder Tracking-Tools und betreibt derzeit keine eigenen Server. Deine Stapel, Karten, Bilder und dein Lernverlauf bleiben auf deinem Gerät. Ich als Entwickler habe keinen Zugriff darauf.</p>
          </div>

          <h2>1. Verantwortlicher</h2>
          <address class="legal-address">
            Lukas Geyer<br />
            Ghegagasse 13/32<br />
            8020 Graz, Österreich<br />
            E-Mail: <a href="mailto:{muninn_email}">{muninn_email}</a>
          </address>

          <h2>2. Daten auf deinem Gerät</h2>
          <p>Alles, was du in Muninn anlegst, importierst und beim Lernen aufzeichnest – Stapel, Karten mit ihren Texten, Bildern und Tönen, Schlagwörter, dein Lernverlauf mit Bewertungen und Zeiten sowie deine Einstellungen – wird lokal auf deinem Gerät gespeichert und verarbeitet. Diese Daten werden nicht an mich oder an Dritte übertragen. Wenn du die App löschst, werden auch diese Daten gelöscht.</p>
          <p>Wenn du auf deinem Gerät ein iCloud-Backup oder ein Backup auf einem Computer eingeschaltet hast, sichert Apple die Daten der App wie die anderer Apps mit. Dafür gilt die <a href="https://www.apple.com/at/legal/privacy/" target="_blank" rel="noopener noreferrer">Datenschutzrichtlinie von Apple</a>.</p>

          <h2>3. Import und Export von Stapeln</h2>
          <p>Wenn du einen Stapel importierst (zum Beispiel eine Anki-Datei), liest Muninn die von dir gewählte Datei auf deinem Gerät ein. Wenn du einen Stapel exportierst, erstellt Muninn eine Datei und übergibt sie an das Teilen-Menü deines Geräts; wohin sie geht, entscheidest du selbst. Muninn versendet dabei nichts von sich aus.</p>

          <h2>4. Fotos und Dateien (optional)</h2>
          <p>Wenn du einer Karte ein Bild hinzufügst, wählst du es über die Auswahl von Apple aus deinen Fotos oder Dateien. Muninn erhält nur die Bilder, die du auswählst, und keinen Zugriff auf deine übrige Mediathek. Das gewählte Bild wird in Muninn auf deinem Gerät gespeichert.</p>

          <h2>5. Synchronisierung (geplant)</h2>
          <p>Eine Synchronisierung zwischen deinen eigenen Geräten ist als Funktion geplant, die du selbst einschaltest. Bevor es sie gibt, steht hier, wie sie funktioniert und wo Daten gespeichert werden. Bis dahin verlässt nichts dein Gerät.</p>

          <h2>6. Absturzberichte und Statistiken von Apple</h2>
          <p>Wenn du in den iOS-Einstellungen zugestimmt hast, Analysedaten mit App-Entwicklern zu teilen, stellt Apple mir anonymisierte Absturzberichte und zusammengefasste Nutzungsstatistiken (z.&nbsp;B. Anzahl der Installationen) zur Verfügung. Daraus kann ich keine Rückschlüsse auf dich als Person ziehen. Du kannst das unter <em>Datenschutz &amp; Sicherheit &rsaquo; Analyse &amp; Verbesserungen</em> ausschalten. Wenn du eine Testversion über TestFlight nutzt, gelten dafür zusätzlich die Bedingungen von Apple für TestFlight.</p>

          <h2>7. Diese Website</h2>
          <p>Beim Aufruf von lukasgeyer.com verarbeitet der Hosting-Anbieter GitHub, Inc. (USA) über GitHub Pages technisch notwendige Daten wie deine IP-Adresse, Datum und Uhrzeit sowie die aufgerufene Seite, um die Website auszuliefern und abzusichern (Art. 6 Abs. 1 lit. f DSGVO). GitHub kann diese Daten in den USA verarbeiten; die Übermittlung stützt sich auf das EU-US Data Privacy Framework. Näheres in der <a href="https://docs.github.com/de/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener noreferrer">Datenschutzerklärung von GitHub</a>. Die Website verwendet keine Cookies und keine Analyse-Tools.</p>

          <h2>8. Deine Rechte</h2>
          <p>Du hast nach der DSGVO das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit und Widerspruch. Da ich keine personenbezogenen Daten über dich speichere, kann ich dir in der Regel nur bestätigen, dass keine vorhanden sind. Schreib mir dazu gern an die oben genannte E-Mail-Adresse.</p>
          <p>Außerdem kannst du dich bei der Aufsichtsbehörde beschweren. In Österreich ist das die <a href="https://www.dsb.gv.at" target="_blank" rel="noopener noreferrer">Österreichische Datenschutzbehörde</a>, Barichgasse 40–42, 1030 Wien.</p>

          <h2>9. Änderungen</h2>
          <p>Wenn sich Muninn ändert, passe ich diese Datenschutzerklärung an. Es gilt jeweils die hier veröffentlichte Fassung. Weitere Angaben findest du im <a href="/imprint/">Impressum</a>.</p>
        </div>
      </article>

      <hr class="legal-divider" />

      <article id="en" lang="en">
        <header class="article-header">
          <div class="article-meta-line">
            <span class="kind-tag">Privacy Policy</span>
            <span>&middot;</span>
            <span>Muninn</span>
            <span>&middot;</span>
            <span>Last updated: 25 November 2026</span>
          </div>
          <h1 class="article-title">Muninn Privacy Policy</h1>
        </header>
        <div class="prose-body">
          <div class="legal-summary">
            <p><strong>In short:</strong> Muninn needs no account, shows no ads, contains no analytics or tracking tools and currently runs no servers of its own. Your decks, cards, images and review history stay on your device. I, the developer, have no access to them.</p>
          </div>

          <h2>1. Controller</h2>
          <address class="legal-address">
            Lukas Geyer<br />
            Ghegagasse 13/32<br />
            8020 Graz, Austria<br />
            Email: <a href="mailto:{muninn_email}">{muninn_email}</a>
          </address>

          <h2>2. Data on your device</h2>
          <p>Everything you create, import and record while studying in Muninn – decks, cards with their text, images and sounds, tags, your review history with ratings and times, and your settings – is stored and processed locally on your device. This data is not sent to me or to third parties. If you delete the app, this data is deleted too.</p>
          <p>If you have turned on iCloud Backup or a backup to a computer for your device, Apple backs up the app's data along with that of your other apps. <a href="https://www.apple.com/legal/privacy/" target="_blank" rel="noopener noreferrer">Apple's Privacy Policy</a> applies to that.</p>

          <h2>3. Importing and exporting decks</h2>
          <p>When you import a deck (for example an Anki file), Muninn reads the file you chose on your device. When you export a deck, Muninn creates a file and hands it to your device's share sheet; where it goes is your decision. Muninn sends nothing by itself.</p>

          <h2>4. Photos and files (optional)</h2>
          <p>When you add an image to a card, you choose it from your photos or files through Apple's picker. Muninn receives only the images you choose and has no access to the rest of your library. The chosen image is stored in Muninn on your device.</p>

          <h2>5. Sync (planned)</h2>
          <p>Syncing between your own devices is planned as an option you turn on yourself. Before it becomes available, this page will say how it works and where data is stored. Until then nothing leaves your device.</p>

          <h2>6. Crash reports and statistics from Apple</h2>
          <p>If you agreed in iOS Settings to share analytics with app developers, Apple gives me anonymised crash reports and aggregated usage statistics (such as the number of installs). These don't let me identify you. You can turn this off under <em>Privacy &amp; Security &rsaquo; Analytics &amp; Improvements</em>. If you use a test version through TestFlight, Apple's terms for TestFlight apply to it as well.</p>

          <h2>7. This website</h2>
          <p>When you visit lukasgeyer.com, the hosting provider GitHub, Inc. (USA) processes, through GitHub Pages, technically necessary data such as your IP address, the date and time and the page requested, in order to deliver and secure the website (Art. 6(1)(f) GDPR). GitHub may process this data in the USA; the transfer relies on the EU-U.S. Data Privacy Framework. See <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener noreferrer">GitHub's privacy statement</a>. The website uses no cookies and no analytics tools.</p>

          <h2>8. Your rights</h2>
          <p>Under the GDPR you have the right of access, rectification, erasure, restriction of processing, data portability and objection. As I store no personal data about you, I can usually only confirm that there is none. Feel free to write to the email address above.</p>
          <p>You can also lodge a complaint with a supervisory authority. In Austria this is the <a href="https://www.dsb.gv.at" target="_blank" rel="noopener noreferrer">Austrian Data Protection Authority</a>, Barichgasse 40–42, 1030 Vienna.</p>

          <h2>9. Changes</h2>
          <p>If Muninn changes, I will update this privacy policy. The version published here always applies. See the <a href="/imprint/#en">legal notice</a> for provider details.</p>
        </div>
      </article>
    </div>
    """
    write_page(
        "muninn/privacy/index.html",
        title=f"Muninn Privacy Policy — {site['name']}",
        path="/muninn/privacy/",
        active_nav="muninn",
        content_html=muninn_privacy_html,
        description="Datenschutzerklärung der App Muninn / Privacy policy of the Muninn app.",
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
      <div class="kicker">About</div>
      <h1 class="display-title">Hello, I'm <em>Lukas</em>.</h1>
    </section>

    <div class="about-grid">
      <div class="prose-body">
        <p>
          I study in Graz and build the apps I wanted for my own semesters:
          <a href="/semestra/"><strong>Semestra</strong></a>, a study planner,
          <a href="/paradeiser/"><strong>Paradeiser</strong></a>, an interval timer, and
          <a href="/muninn/"><strong>Muninn</strong></a>, a flashcard app that is still in its early days.
        </p>
        <p>
          They share a few rules. They need no account, show no ads and contain no tracking.
          Your data stays on your device. And they should feel calm: an app for studying
          shouldn't be one more thing that asks for your attention.
        </p>
        <p>
          This website is built the same way: plain pages, no cookies, no analytics.
          If you have feedback on one of the apps, I'd love to hear from you.
        </p>
      </div>

      <aside class="about-aside">
        <h2>Contact &amp; Links</h2>
        <ul>
          <li><span class="aside-note">General &amp; Paradeiser</span><a href="mailto:{site_email}">{site_email}</a></li>
          {support_aside_html}
          <li><a {link_attrs(sem['app_store_url'])}>Semestra on the App Store &#8599;</a></li>
          {github_aside_html}
          <li><a href="/rss.xml">RSS Feed</a></li>
          <li><a href="/imprint/">Imprint</a></li>
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
        description="About Lukas Geyer and the apps Semestra, Paradeiser and Muninn.",
    )

    # 5b. Shared Imprint / Legal Notice Page (dist/imprint/index.html) for Semestra & Paradeiser
    imprint_html = f"""
    <div class="reader-container">
      <div class="reader-controls">
        <a href="/">&larr; Home</a>
        <div class="legal-lang-links" aria-label="Language">
          <a href="#de">Deutsch</a>
          <a href="#en">English</a>
        </div>
      </div>

      <article id="de" lang="de">
        <header class="article-header">
          <div class="article-meta-line">
            <span class="kind-tag">Impressum</span>
            <span>&middot;</span>
            <span>lukasgeyer.com &middot; Semestra &middot; Paradeiser &middot; Muninn</span>
          </div>
          <h1 class="article-title">Impressum</h1>
          <p class="article-subtitle">Informationen gemäß &sect;&nbsp;5 ECG und Offenlegung gemäß &sect;&nbsp;25 MedienG</p>
        </header>
        <div class="prose-body">
          <dl class="legal-dl">
            <dt>Medieninhaber und Diensteanbieter</dt>
            <dd>
              <address>
                Lukas Geyer<br />
                Ghegagasse 13/32<br />
                8020 Graz, Österreich
              </address>
            </dd>

            <dt>Kontakt</dt>
            <dd>
              Semestra: <a href="mailto:{support_email}">{support_email}</a><br />
              Paradeiser, Muninn &amp; Allgemein: <a href="mailto:{site_email}">{site_email}</a>
            </dd>

            <dt>Unternehmensgegenstand</dt>
            <dd>Entwicklung und Vertrieb von Apps für iPhone und iPad (Semestra, Paradeiser; Muninn in Entwicklung)</dd>

            <dt>Grundlegende Richtung der Website</dt>
            <dd>Informationen über die Apps Semestra, Paradeiser und Muninn, ihre Änderungsprotokolle, Support und rechtliche Hinweise</dd>
          </dl>

          <h2>Urheberrecht</h2>
          <p>Die Inhalte dieser Website – Texte, Bilder und die abgebildeten Apps – sind urheberrechtlich geschützt. Eine Verwendung über das private Lesen hinaus braucht meine Zustimmung.</p>

          <h2>Haftung für Links</h2>
          <p>Diese Website enthält Links zu Websites Dritter. Für deren Inhalte sind ausschließlich deren Betreiber verantwortlich. Sollten mir Rechtsverletzungen auf verlinkten Seiten bekannt werden, entferne ich den Link umgehend.</p>

          <h2>Datenschutz</h2>
          <p>Wie die Apps und diese Website mit Daten umgehen, steht in den jeweiligen Datenschutzerklärungen für <a href="/semestra/privacy-policy/#de">Semestra</a>, <a href="/paradeiser/privacy-policy/#de">Paradeiser</a> und <a href="/muninn/privacy/">Muninn</a>.</p>
          <p class="legal-updated">Stand: 24. November 2026</p>
        </div>
      </article>

      <hr class="legal-divider" />

      <article id="en" lang="en">
        <header class="article-header">
          <div class="article-meta-line">
            <span class="kind-tag">Legal Notice</span>
            <span>&middot;</span>
            <span>lukasgeyer.com &middot; Semestra &middot; Paradeiser &middot; Muninn</span>
          </div>
          <h1 class="article-title">Legal Notice</h1>
          <p class="article-subtitle">Information under &sect;&nbsp;5 ECG and disclosure under &sect;&nbsp;25 MedienG (Austrian law)</p>
        </header>
        <div class="prose-body">
          <dl class="legal-dl">
            <dt>Owner and service provider</dt>
            <dd>
              <address>
                Lukas Geyer<br />
                Ghegagasse 13/32<br />
                8020 Graz, Austria
              </address>
            </dd>

            <dt>Contact</dt>
            <dd>
              Semestra: <a href="mailto:{support_email}">{support_email}</a><br />
              Paradeiser, Muninn &amp; General: <a href="mailto:{site_email}">{site_email}</a>
            </dd>

            <dt>Business purpose</dt>
            <dd>Development and distribution of apps for iPhone and iPad (Semestra, Paradeiser; Muninn in development)</dd>

            <dt>Purpose of this website</dt>
            <dd>Information about the apps Semestra, Paradeiser and Muninn, their changelogs, support and legal notices</dd>
          </dl>

          <h2>Copyright</h2>
          <p>The content of this website – text, images and the apps shown – is protected by copyright. Any use beyond private reading needs my permission.</p>

          <h2>Liability for links</h2>
          <p>This website contains links to third-party websites. Their operators alone are responsible for their content. If I become aware of any legal violations on linked pages, I will remove the link immediately.</p>

          <h2>Privacy</h2>
          <p>How the apps and this website handle data is described in the privacy policies for <a href="/semestra/privacy-policy/#en">Semestra</a>, <a href="/paradeiser/privacy-policy/#en">Paradeiser</a> and <a href="/muninn/privacy/">Muninn</a>.</p>
          <p class="legal-updated">Last updated: 24 November 2026</p>
        </div>
      </article>
    </div>
    """
    write_page(
        "imprint/index.html",
        title=f"Imprint — {site['name']}",
        path="/imprint/",
        active_nav="",
        content_html=imprint_html,
        description="Impressum / Legal Notice for lukasgeyer.com and the apps Semestra, Paradeiser and Muninn.",
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
      <p class="intro-copy">The link may be old or mistyped. Try the <a href="/">home page</a>, <a href="/semestra/">Semestra</a> or <a href="/paradeiser/">Paradeiser</a>.</p>
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
        sitemap_pages = [("/", None)] + ([("/writing/", None)] if writings else [])
        sitemap_pages += [(w["url"], w["date"]) for w in writings]
        sitemap_pages += [
            ("/semestra/", updates[0]["date"] if updates else None),
            ("/semestra/privacy-policy/", None),
            ("/paradeiser/", paradeiser_updates[0]["date"] if paradeiser_updates else None),
            ("/paradeiser/privacy-policy/", None),
            ("/muninn/", muninn_updates[0]["date"] if muninn_updates else None),
            ("/muninn/privacy/", None),
            ("/imprint/", None),
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

    print(
        f"Built {len(updates)} Semestra, {len(paradeiser_updates)} Paradeiser and {len(muninn_updates)} Muninn "
        f"changelog entries and {len(writings)} stories/essays into {DIST}"
    )


if __name__ == "__main__":
    build()
