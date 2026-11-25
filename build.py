#!/usr/bin/env python3
"""
Zero-dependency static site generator for lukasgeyer.com: the start page, one page per app
(Semestra, Paradeiser, Muninn) with its changelog, the privacy policies, the imprint and the feeds.
Usage: python3 build.py
"""

from __future__ import annotations

import datetime
import email.utils
import hashlib
import html
import json
import pathlib
import re
import shutil
import struct
import urllib.parse

ROOT = pathlib.Path(__file__).parent
CONTENT = ROOT / "content"
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"

# The apps, in the order they appear in the navigation and on the start page.
APP_KEYS = ("semestra", "paradeiser", "muninn")
PRIVACY_PATHS = {
    "semestra": "/semestra/privacy-policy/",
    "paradeiser": "/paradeiser/privacy-policy/",
    "muninn": "/muninn/privacy/",
}

# Drawn in place of an app icon while an app has no "icon" in site.json.
PLACEHOLDER_MARK = """<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
  <rect x="4" y="6.5" width="13" height="11" rx="2.2" stroke="currentColor" stroke-width="1.5"/>
  <path d="M8.5 6.5V5.2C8.5 4.5 9 4 9.7 4H18.8C19.5 4 20 4.5 20 5.2V14.3C20 15 19.5 15.5 18.8 15.5H17" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="7.5" y1="11.5" x2="13.5" y2="11.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
</svg>"""

# The page may only load its own files: no third-party scripts, styles, fonts or frames.
CONTENT_SECURITY_POLICY = "default-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'"

SAFE_HREF = re.compile(r"^(https?://|mailto:|/|#)")
ORDERED_ITEM = re.compile(r"^\d+\.\s+")
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


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


def format_inline(text: str) -> str:
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
        return f"<a {link_attrs(html.unescape(url))}>{label}</a>"

    out = re.sub(r"`([^`]+)`", _stash_code, out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, out)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{code_spans[int(m.group(1))]}</code>", out)


def starts_block(line: str) -> bool:
    return not line or line.startswith(("## ", "### ", "- ")) or bool(ORDERED_ITEM.match(line))


def render_markdown(md_text: str) -> str:
    """The small Markdown subset of the changelogs (see the README). A changelog entry sits
    under its own title (an h3), so `##` and `###` both become an h4."""
    lines = [line.strip() for line in md_text.splitlines()]
    blocks: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        if not line:
            i += 1
        elif line.startswith(("## ", "### ")):
            blocks.append(f"<h4>{format_inline(line.split(' ', 1)[1])}</h4>")
            i += 1
        elif line.startswith("- "):
            items = []
            while i < n and lines[i].startswith("- "):
                items.append(f"<li>{format_inline(lines[i][2:])}</li>")
                i += 1
            blocks.append("<ul>\n" + "\n".join(items) + "\n</ul>")
        elif ORDERED_ITEM.match(line):
            items = []
            while i < n and ORDERED_ITEM.match(lines[i]):
                items.append(f"<li>{format_inline(ORDERED_ITEM.sub('', lines[i]))}</li>")
                i += 1
            blocks.append("<ol>\n" + "\n".join(items) + "\n</ol>")
        else:
            para_lines = [line]
            i += 1
            while i < n and not starts_block(lines[i]):
                para_lines.append(lines[i])
                i += 1
            blocks.append(f"<p>{format_inline(' '.join(para_lines))}</p>")

    return "\n".join(blocks)


# ---------------------------------------------------------------- Content

def load_updates(key: str) -> list[dict]:
    """Read an app's changelog entries (content/<app>/*.md), newest first. A bad date stops the build."""
    items = []
    for path in sorted((CONTENT / key).glob("*.md")):
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
                "version": "1.0",
                "platform": "iOS",
                "highlights": "",
                "status": "",
                **meta,
                "slug": path.stem,
                "title": meta.get("title", path.stem),
                "date": date,
                "url": f"/{key}/#{path.stem}",
                "body_html": render_markdown(body),
            }
        )
    items.sort(key=lambda x: x["date"], reverse=True)
    return items


def image_size(name: str) -> tuple[int, int]:
    """Width and height of a PNG or JPEG in assets/img/, read from the file itself, so that a
    replaced image gets the right width and height attributes without anyone typing numbers."""
    path = ASSETS / "img" / name
    if not path.is_file():
        raise SystemExit(f"site.json names the image {name!r}, but assets/img/{name} does not exist")
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return width, height
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return width, height
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise SystemExit(f"assets/img/{name}: only PNG and JPEG images are understood")


# ---------------------------------------------------------------- Small pieces

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


def is_live(status: str) -> bool:
    return status.lower().startswith("on the app store")


def chip(status: str) -> str:
    """The status chip: green for "On the App Store", grey for anything else."""
    if not status:
        return ""
    cls = "chip chip--live" if is_live(status) else "chip"
    return f'<span class="{cls}">{html.escape(status)}</span>'


def app_icon(key: str, app: dict, size: int, transition: bool = False) -> str:
    """The app's icon from site.json ("icon", a file in assets/img/). "icon_style": "artwork" sets
    a picture that is not a finished icon on a light tile; without "icon" a placeholder is drawn.
    `transition` names the icon so that it glides between the start page and the app's page."""
    cls = "icon" + (f" vt-icon-{key}" if transition else "")
    name = app.get("icon")
    if not name:
        return f'<span class="{cls} icon--mark">{PLACEHOLDER_MARK}</span>'
    img = f'<img src="/img/{html.escape(name)}" width="{size}" height="{size}" alt="" />'
    if app.get("icon_style") == "artwork":
        return f'<span class="{cls} icon--artwork">{img}</span>'
    return img.replace("<img ", f'<img class="{cls}" ', 1)


def device(shot: dict, lazy: bool = True) -> str:
    """A screenshot in a rounded, device-like frame drawn by the stylesheet."""
    width, height = image_size(shot["file"])
    loading = ' loading="lazy" decoding="async"' if lazy else ""
    return (
        f'<figure class="device"><div class="device-frame">'
        f'<img src="/img/{html.escape(shot["file"])}" width="{width}" height="{height}"{loading} '
        f'alt="{html.escape(shot["alt"])}" /></div></figure>'
    )


def accent_css(site: dict) -> str:
    """The apps' accent colours from site.json, written as the last rules of the stylesheet."""
    light, dark = [], []
    for key in APP_KEYS:
        accent = site[key].get("accent") or {}
        for mode in ("light", "dark"):
            if not HEX_COLOR.match(accent.get(mode, "")):
                raise SystemExit(f'site.json: {key} needs "accent": {{"light": "#RRGGBB", "dark": "#RRGGBB"}}')
        light.append(f".app-{key} {{ --accent: {accent['light']}; --on-accent: #fff; }}")
        dark.append(f"  .app-{key} {{ --accent: {accent['dark']}; --on-accent: #000; }}")
    glide = [f"  .vt-icon-{key} {{ view-transition-name: icon-{key}; }}" for key in APP_KEYS]
    return (
        "\n/* App accents, written by build.py from site.json. */\n"
        + "\n".join(light)
        + "\n@media (prefers-color-scheme: dark) {\n"
        + "\n".join(dark)
        + "\n}\n/* Each app's icon glides from the start page to its own page. */\n"
        + "@media (prefers-reduced-motion: no-preference) {\n"
        + "\n".join(glide)
        + "\n}\n"
    )


def favicon_svg(site: dict) -> str:
    """A neutral mark for the site: one dot per app, in the apps' accent colours."""
    places = ((16, 10.4), (9.8, 21), (22.2, 21))
    dots = "".join(
        f'<circle cx="{x}" cy="{y}" r="3.7" fill="{site[key]["accent"]["dark"]}"/>'
        for (x, y), key in zip(places, APP_KEYS)
    )
    return (
        '<svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">'
        f'<rect width="32" height="32" rx="7.2" fill="#1d1d1f"/>{dots}</svg>\n'
    )


# ---------------------------------------------------------------- Page shell

def page_layout(
    *,
    title: str,
    site: dict,
    path: str | None,
    content_html: str,
    app_key: str = "",
    description: str = "",
    asset_version: str = "",
) -> str:
    """Wrap page content in the shared shell. `path` is the page's URL path (e.g. "/semestra/");
    pass None for pages that should not be indexed (404). `app_key` gives the page its app's accent
    and marks the app in the navigation; the start page, About and the imprint stay neutral."""
    name = html.escape(site["name"])
    title_attr = html.escape(title)
    desc_attr = html.escape(description or site.get("tagline", ""))
    site_url = site.get("url", "").rstrip("/")

    head_meta = [
        f'<meta name="description" content="{desc_attr}" />',
        f'<meta property="og:title" content="{title_attr}" />',
        f'<meta property="og:description" content="{desc_attr}" />',
        '<meta property="og:type" content="website" />',
        f'<meta property="og:site_name" content="{name}" />',
        '<meta name="twitter:card" content="summary" />',
    ]
    if path is None:
        head_meta.append('<meta name="robots" content="noindex" />')
    elif site_url:
        page_url = html.escape(site_url + path)
        head_meta.append(f'<meta property="og:url" content="{page_url}" />')
        head_meta.append(f'<link rel="canonical" href="{page_url}" />')

    def nav_link(key: str) -> str:
        current = ' aria-current="page"' if app_key == key else ""
        return f'<a href="/{key}/"{current}>{html.escape(site[key]["name"])}</a>'

    def footer_list(label: str, links: list[tuple[str, str]]) -> str:
        items = "".join(f"<li><a {link_attrs(url)}>{html.escape(text)}</a></li>" for text, url in links)
        return f'<div class="footer-col"><p class="footer-title">{label}</p><ul>{items}</ul></div>'

    footer = (
        footer_list("Apps", [(site[key]["name"], f"/{key}/") for key in APP_KEYS])
        + footer_list(
            "Legal",
            [("Imprint", "/imprint/")]
            + [(f'{site[key]["name"]} Privacy', PRIVACY_PATHS[key]) for key in APP_KEYS],
        )
        + footer_list(
            "Contact",
            [("About", "/about/"), ("Email", f"mailto:{site['email']}")]
            + [(link["label"], link["url"]) for link in site.get("links", [])],
        )
    )
    body_class = f' class="app-{app_key}"' if app_key else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}" />
  <meta name="color-scheme" content="light dark" />
  <meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)" />
  <meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)" />
  <title>{title_attr}</title>
  {chr(10).join('  ' + tag for tag in head_meta).strip()}
  <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
  <link rel="stylesheet" href="/styles.css{asset_version}" />
  <link rel="alternate" type="application/rss+xml" title="{name} RSS" href="/rss.xml" />
  <script src="/site.js{asset_version}" defer></script>
</head>
<body{body_class}>
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="nav">
    <div class="nav-inner">
      <a href="/" class="nav-brand">{name}</a>
      <nav class="nav-links" aria-label="Apps">
        {''.join(nav_link(key) for key in APP_KEYS)}
      </nav>
    </div>
  </header>

  <main id="main">
  {content_html}
  </main>

  <footer class="footer">
    <div class="wrap">
      <nav class="footer-cols" aria-label="Footer">
        {footer}
      </nav>
      <p class="footer-note">&copy; {datetime.date.today().year} {name}</p>
    </div>
  </footer>
</body>
</html>
"""


# ---------------------------------------------------------------- Start page

def home_tile(site: dict, key: str, first: bool) -> str:
    """One app on the start page: icon, name, one line, its status and the way into its page."""
    app = site[key]
    name = html.escape(app["name"])
    shot = app.get("tile_shot")
    store = (
        f'<a class="more more--out" {link_attrs(app["app_store_url"])}>View on the App Store</a>'
        if app.get("app_store_url")
        else ""
    )
    visual = f'<div class="tile-visual">{device(shot, lazy=not first)}</div>' if shot else ""
    cls = "tile" + (" tile--wide" if first else "") + ("" if shot else " tile--plain")
    return f"""<article class="{cls} app-{key}" data-reveal>
  <div class="tile-text">
    {app_icon(key, app, 72, transition=True)}
    <h2 class="tile-name">{name}</h2>
    <p class="tile-line">{html.escape(app['subtitle'])}</p>
    <p>{chip(app.get('status', ''))}</p>
    <p class="tile-links"><a class="more tile-link" href="/{key}/">More about {name}</a>{store}</p>
  </div>
  {visual}
</article>"""


def home_page(site: dict, updates: dict[str, list[dict]]) -> str:
    latest = sorted(
        (dict(u, app=site[key]["name"]) for key in APP_KEYS for u in updates[key]),
        key=lambda u: u["date"],
        reverse=True,
    )[:5]
    update_rows = "".join(
        f"""<li><a href="{u['url']}" class="update">
  <span class="update-app">{html.escape(u['app'])} {html.escape(u['version'])}</span>
  <span class="update-title">{html.escape(u['title'])}</span>
  <span class="update-date">{time_tag(u['date'])}</span>
</a></li>"""
        for u in latest
    )
    sem, par = site["semestra"], site["paradeiser"]
    return f"""
    <section class="hero hero--home">
      <div class="wrap">
        <p class="eyebrow">{html.escape(site['kicker'])}</p>
        <h1 class="display">{html.escape(site['headline'])}</h1>
        <p class="lead">{html.escape(site['intro'])}</p>
      </div>
    </section>

    <section class="wrap tiles" aria-label="The apps">
      {''.join(home_tile(site, key, first=i == 0) for i, key in enumerate(APP_KEYS))}
    </section>

    <section class="section wrap together" aria-labelledby="together-title" data-reveal>
      <div class="together-marks" aria-hidden="true">{app_icon('semestra', sem, 72)}<span class="together-plus">+</span>{app_icon('paradeiser', par, 72)}</div>
      <p class="eyebrow">Better Together</p>
      <h2 class="headline" id="together-title"><span class="phrase">Semestra plans the block.</span> <span class="phrase">Paradeiser times it.</span></h2>
      <p class="lead">When a study block is coming up in Semestra, Paradeiser suggests focus and break times that fit it. What you study there counts as studied in your plan. The two apps only talk to each other on your device.</p>
    </section>

    <section class="section wrap" aria-labelledby="principles-title">
      <h2 class="sr-only" id="principles-title">Principles</h2>
      <div class="feature-grid feature-grid--4">
        <div class="feature" data-reveal><h3>No account</h3><p>Open the app and start. There is nothing to sign up for.</p></div>
        <div class="feature" data-reveal><h3>No ads, no tracking</h3><p>No analytics tools and no advertising, in any of the apps.</p></div>
        <div class="feature" data-reveal><h3>On your device</h3><p>Your data stays on your iPhone, or in your own iCloud if you turn sync on.</p></div>
        <div class="feature" data-reveal><h3>German and English</h3><p>Made in Graz, for students in Austria, Germany and Switzerland.</p></div>
      </div>
    </section>

    <section class="section wrap" aria-labelledby="updates-title">
      <h2 class="headline headline--small" id="updates-title" data-reveal>Latest Updates</h2>
      <ul class="updates" data-reveal>
        {update_rows}
      </ul>
    </section>
    """


# ---------------------------------------------------------------- App pages

def feature_sections(app: dict) -> str:
    """The app's features from site.json, in order. A feature with "shots" becomes a wide row with
    its screenshots; the features without are set next to each other as plain blocks. An app
    with no screenshots at all gets its blocks in larger type, two to a line."""
    features = app.get("features", [])
    parts: list[str] = []
    plain: list[str] = []
    rows = 0

    def flush() -> None:
        if plain:
            size = "large" if not any(f.get("shots") for f in features) else min(len(plain), 4)
            parts.append(f'<div class="feature-grid feature-grid--{size}">{"".join(plain)}</div>')
            plain.clear()

    for feature in features:
        text = f"<h3>{html.escape(feature['title'])}</h3><p>{html.escape(feature['text'])}</p>"
        shots = feature.get("shots")
        if not shots:
            plain.append(f'<div class="feature" data-reveal>{text}</div>')
            continue
        flush()
        cls = "feature-row" + (" feature-row--flip" if rows % 2 else "")
        media_cls = "feature-media" + (" feature-media--pair" if len(shots) > 1 else "")
        parts.append(
            f'<div class="{cls}" data-reveal><div class="feature-text">{text}</div>'
            f'<div class="{media_cls}">{"".join(device(s) for s in shots)}</div></div>'
        )
        rows += 1
    flush()
    return "\n".join(parts)


def changelog_section(updates: list[dict]) -> str:
    count = "1 Version" if len(updates) == 1 else f"{len(updates)} Versions"
    entries = "".join(
        f"""<article class="release" id="{u['slug']}" data-reveal>
  <div class="release-meta">
    <p class="release-version">Version {html.escape(u['version'])}</p>
    {f'<p>{chip(u["status"])}</p>' if u['status'] else ''}
    <p>{'Updated ' if u['status'] and not is_live(u['status']) else ''}{time_tag(u['date'])}</p>
    <p>{html.escape(u['platform'])}</p>
  </div>
  <div class="release-body">
    <h3 class="release-title">{html.escape(u['title'])}</h3>
    <div class="prose">
      {u['body_html']}
    </div>
  </div>
</article>"""
        for u in updates
    )
    return f"""
    <section class="section wrap" id="changelog" aria-labelledby="changelog-title">
      <div class="section-head">
        <h2 class="headline" id="changelog-title">Changelog</h2>
        <p class="section-note">{count}</p>
      </div>
      {entries}
    </section>"""


def app_page(site: dict, key: str, updates: list[dict]) -> str:
    """One product page: the hero, what the app does, the facts, then the changelog."""
    app = site[key]
    name = html.escape(app["name"])
    support = html.escape(app.get("support_email", site["email"]).strip())
    status = chip(app.get("status", ""))
    if app.get("app_store_url"):
        actions = (
            f'<a class="button" {link_attrs(app["app_store_url"])}>View on the App Store</a>'
            f'<a class="more more--down" href="#changelog">Changelog</a>'
        )
        note = f'<p class="hero-status">{status}</p>'
    else:
        # Not on the App Store: the status takes the place of a button.
        actions = f'{status}<a class="more more--down" href="#changelog">Changelog</a>'
        note = ""
    return f"""
    <section class="hero hero--app">
      <div class="wrap">
        {app_icon(key, app, 112, transition=True)}
        <h1 class="display">{name}</h1>
        <p class="hero-line">{html.escape(app['subtitle'])}</p>
        <p class="lead">{html.escape(app['summary'])}</p>
        <div class="hero-actions">{actions}</div>
        {note}
      </div>
    </section>

    <section class="section section--first wrap" aria-labelledby="features-title">
      <h2 class="headline" id="features-title" data-reveal>{html.escape(app['features_title'])}</h2>
      {feature_sections(app)}
    </section>

    <section class="section wrap" aria-labelledby="facts-title">
      <h2 class="sr-only" id="facts-title">{name} at a Glance</h2>
      <dl class="facts" data-reveal>
        <div><dt>Runs on</dt><dd>{html.escape(app['platforms'])}</dd></div>
        <div><dt>Price</dt><dd>{html.escape(app['pricing'])}</dd></div>
        <div><dt>Privacy</dt><dd>No account, no ads, no tracking. <a href="{PRIVACY_PATHS[key]}">Privacy Policy</a></dd></div>
        <div><dt>Support</dt><dd><a href="mailto:{support}">{support}</a></dd></div>
      </dl>
    </section>
    {changelog_section(updates)}
    """


# ---------------------------------------------------------------- About and 404

def about_page(site: dict) -> str:
    sem = site["semestra"]
    site_email = html.escape(site["email"])
    support_email = html.escape(sem.get("support_email", "").strip())
    github = next(
        (link["url"] for link in site.get("links", []) if link.get("label", "").lower() == "github" and link.get("url")),
        "",
    )
    support_item = (
        f'<div><dt>Semestra support</dt><dd><a href="mailto:{support_email}">{support_email}</a></dd></div>'
        if support_email
        else ""
    )
    github_item = f'<li><a class="more more--out" {link_attrs(github)}>GitHub</a></li>' if github else ""
    return f"""
    <section class="hero hero--page">
      <div class="wrap">
        <p class="eyebrow">About</p>
        <h1 class="display">Hello, I'm Lukas.</h1>
      </div>
    </section>

    <div class="wrap page-column">
      <div class="prose prose--large">
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

      <section class="about-contact" aria-labelledby="contact-title">
        <h2 class="headline headline--small" id="contact-title">Contact &amp; Links</h2>
        <dl class="facts facts--two">
          <div><dt>General &amp; Paradeiser</dt><dd><a href="mailto:{site_email}">{site_email}</a></dd></div>
          {support_item}
        </dl>
        <ul class="link-list">
          <li><a class="more more--out" {link_attrs(sem['app_store_url'])}>Semestra on the App Store</a></li>
          {github_item}
          <li><a class="more" href="/rss.xml">RSS Feed</a></li>
          <li><a class="more" href="/imprint/">Imprint</a></li>
        </ul>
      </section>
    </div>
    """


NOT_FOUND_PAGE = """
    <section class="hero hero--page">
      <div class="wrap">
        <p class="eyebrow">Error 404</p>
        <h1 class="display">This page has gone missing.</h1>
        <p class="lead">The link may be old or mistyped. Try the <a href="/">home page</a>, <a href="/semestra/">Semestra</a> or <a href="/paradeiser/">Paradeiser</a>.</p>
      </div>
    </section>
    """


# ---------------------------------------------------------------- Legal pages
#
# The privacy policies and the imprint are legal texts: change their wording only on purpose, in
# German and English together, and move the "Stand / Last updated" date when you do. Each page has
# one h1, the German title. The English title is therefore an h2 and the English sections are h3;
# the stylesheet sets both languages the same.

def semestra_privacy(support_email: str) -> str:
    return f"""
    <div class="legal">
      <div class="legal-bar">
        <a href="/semestra/">&larr; Back to Semestra</a>
        <nav class="lang-switch" aria-label="Language">
          <a href="#de" lang="de" hreflang="de">Deutsch</a>
          <a href="#en" hreflang="en">English</a>
        </nav>
      </div>

      <article id="de" lang="de">
        <header class="legal-header">
          <p class="eyebrow">
            <span>Datenschutzerklärung</span>
            <span>&middot;</span>
            <span>Semestra</span>
            <span>&middot;</span>
            <span>Stand: 24. November 2026</span>
          </p>
          <h1 class="legal-title">Datenschutzerklärung für Semestra</h1>
        </header>
        <div class="prose">
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
        <header class="legal-header">
          <p class="eyebrow">
            <span>Privacy Policy</span>
            <span>&middot;</span>
            <span>Semestra</span>
            <span>&middot;</span>
            <span>Last updated: 24 November 2026</span>
          </p>
          <h2 class="legal-title">Semestra Privacy Policy</h2>
        </header>
        <div class="prose">
          <div class="legal-summary">
            <p><strong>In short:</strong> Semestra needs no account, shows no ads, contains no analytics or tracking tools and runs no servers of its own. Your exams, study plan and progress stay on your device – or, if you turn on iCloud sync, in your own iCloud account. I, the developer, have no access to them.</p>
          </div>

          <h3>1. Controller</h3>
          <address class="legal-address">
            Lukas Geyer<br />
            Ghegagasse 13/32<br />
            8020 Graz, Austria<br />
            Email: <a href="mailto:{support_email}">{support_email}</a>
          </address>

          <h3>2. Data on your device</h3>
          <p>Everything you enter in Semestra – exams, topics, study sessions, grades, ECTS credits, imported calendars and your settings – is stored and processed locally on your device. When you add exams from text or a photo, the text is also read on your device. It is not sent to me or to any third party. Deleting the app deletes this data.</p>

          <h3>3. Access to your calendars</h3>
          <p>If you allow it, Semestra reads your calendars to find free time for studying and to detect exam dates, and adds your study blocks to a separate calendar. This happens only on your device. You can revoke access at any time in iOS Settings under <em>Privacy &amp; Security &rsaquo; Calendars</em>.</p>

          <h3>4. Calendar subscriptions and imported files</h3>
          <p>You can import calendar files (.ics) or subscribe to a calendar address, for example from your university. For a subscription, Semestra downloads the calendar directly from the address you entered. Like any request on the internet, this gives that server technical data such as your IP address. The operator of that server is responsible for this processing, and its privacy policy applies. I receive no data from this.</p>

          <h3>5. iCloud sync (optional)</h3>
          <p>With Semestra Plus you can sync your data across your devices via iCloud. The data is then stored in the private database of your iCloud account at Apple. Only you can access it, not me. <a href="https://www.apple.com/legal/privacy/" target="_blank" rel="noopener noreferrer">Apple's Privacy Policy</a> applies. You can turn sync off in Semestra's settings and delete the stored data in iOS Settings under <em>[Your Name] &rsaquo; iCloud &rsaquo; Manage Storage</em>.</p>

          <h3>6. Purchases and subscriptions</h3>
          <p>Purchases of Semestra Plus (a monthly or yearly subscription, or a one-time purchase) are handled entirely by Apple through the App Store. I receive no payment details and no data that identifies you personally. The app only checks on your device whether a subscription or the one-time purchase is active.</p>

          <h3>7. Notifications, widgets and Siri</h3>
          <p>Study reminders are scheduled as local notifications on your device. Widgets and Live Activities show data that stays on your device. If you use Siri or Shortcuts with Semestra, Apple processes your requests under Apple's Privacy Policy.</p>

          <h3>8. Export and sharing</h3>
          <p>When you export your study plan as a PDF or calendar file, you decide where the file goes. Semestra doesn't send anything on its own.</p>

          <h3>9. Link with Paradeiser (optional)</h3>
          <p>If <a href="/paradeiser/">Paradeiser</a>, my interval timer, is installed on the same device, the two apps exchange data: Semestra makes your upcoming study blocks available to Paradeiser (the exam's name, the topic, start and end), and Paradeiser reports back when and for how long you focused on them. This exchange happens only on your device, through a protected storage area the two apps share (an App Group). Nothing is sent to me or to any third party. You can turn the link off in Semestra's settings under <em>Paradeiser</em>. Without Paradeiser on the device, nobody reads this data.</p>

          <h3>10. Crash reports and statistics from Apple</h3>
          <p>If you agreed in iOS Settings to share analytics with app developers, Apple gives me anonymised crash reports and aggregated usage statistics (such as the number of installs). These don't let me identify you. You can turn this off under <em>Privacy &amp; Security &rsaquo; Analytics &amp; Improvements</em>.</p>

          <h3>11. This website</h3>
          <p>When you visit lukasgeyer.com (as well as semestra.at), the hosting provider GitHub, Inc. (USA) processes, through GitHub Pages, technically necessary data such as your IP address, the date and time and the page requested, in order to deliver and secure the website (Art. 6(1)(f) GDPR). GitHub may process this data in the USA; the transfer relies on the EU-U.S. Data Privacy Framework. See <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener noreferrer">GitHub's privacy statement</a>. The website uses no cookies and no analytics tools.</p>

          <h3>12. Your rights</h3>
          <p>Under the GDPR you have the right of access, rectification, erasure, restriction of processing, data portability and objection. Since I store no personal data about you, I can usually only confirm that there is none. Just write to the email address above.</p>
          <p>You also have the right to lodge a complaint with a supervisory authority. In Austria this is the <a href="https://www.dsb.gv.at" target="_blank" rel="noopener noreferrer">Austrian Data Protection Authority</a> (Datenschutzbehörde), Barichgasse 40–42, 1030 Vienna.</p>

          <h3>13. Changes</h3>
          <p>If Semestra changes, I will update this privacy policy. The version published here always applies. See the <a href="/imprint/#en">legal notice</a> for provider details.</p>
        </div>
      </article>
    </div>
    """


def paradeiser_privacy(paradeiser_email: str) -> str:
    return f"""
    <div class="legal">
      <div class="legal-bar">
        <a href="/paradeiser/">&larr; Back to Paradeiser</a>
        <nav class="lang-switch" aria-label="Language">
          <a href="#de" lang="de" hreflang="de">Deutsch</a>
          <a href="#en" hreflang="en">English</a>
        </nav>
      </div>

      <article id="de" lang="de">
        <header class="legal-header">
          <p class="eyebrow">
            <span>Datenschutzerklärung</span>
            <span>&middot;</span>
            <span>Paradeiser</span>
            <span>&middot;</span>
            <span>Stand: 24. November 2026</span>
          </p>
          <h1 class="legal-title">Datenschutzerklärung für Paradeiser</h1>
        </header>
        <div class="prose">
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
        <header class="legal-header">
          <p class="eyebrow">
            <span>Privacy Policy</span>
            <span>&middot;</span>
            <span>Paradeiser</span>
            <span>&middot;</span>
            <span>Last updated: 24 November 2026</span>
          </p>
          <h2 class="legal-title">Paradeiser Privacy Policy</h2>
        </header>
        <div class="prose">
          <div class="legal-summary">
            <p><strong>In short:</strong> Paradeiser needs no account, shows no ads, contains no analytics or tracking tools and runs no servers of its own. Your focus sessions, presets, tags, milestones and settings stay on your device. I, the developer, have no access to them.</p>
          </div>

          <h3>1. Controller</h3>
          <address class="legal-address">
            Lukas Geyer<br />
            Ghegagasse 13/32<br />
            8020 Graz, Austria<br />
            Email: <a href="mailto:{paradeiser_email}">{paradeiser_email}</a>
          </address>

          <h3>2. Data on your device</h3>
          <p>Everything you create and record in Paradeiser – custom schedules and presets, focus tags, completed focus sessions, daily goals, streaks, milestones, unlocked tomato varieties and your settings – is stored and processed locally on your device using Apple's SwiftData and UserDefaults frameworks. It is not sent to me or to any third party. Deleting the app deletes this data.</p>

          <h3>3. Apple Calendar (optional)</h3>
          <p>If you turn on Calendar sync with Paradeiser Plus and grant permission, Paradeiser saves your completed focus sessions as events in the calendar you select. This happens strictly on your device. You can revoke access at any time in iOS Settings under <em>Privacy &amp; Security &rsaquo; Calendars</em>.</p>

          <h3>4. Apple Health (optional)</h3>
          <p>If you turn on Apple Health sync and grant write permission, Paradeiser records completed focus sessions locally on your device as Mindful Minutes in Apple Health. Paradeiser never reads Health data and never shares Health data with me or any third party. You can revoke permission at any time in the Health app or iOS Settings.</p>

          <h3>5. Link with Semestra (optional)</h3>
          <p>If <a href="/semestra/">Semestra</a>, my study planner, is installed on the same device, the two apps exchange data: Semestra makes your upcoming study blocks available to Paradeiser (the exam's name, the topic, start and end) so that Paradeiser can suggest focus and break times that fit them, and Paradeiser reports back when and for how long you focused on them. This exchange happens only on your device, through a protected storage area the two apps share (an App Group). Nothing is sent to me or to any third party. You can turn the link off in Paradeiser's settings under <em>Integrations</em>.</p>

          <h3>6. Photos and sticker sharing (optional)</h3>
          <p>When you save a Paradeiser sticker to your Photo Library, Paradeiser requests add-only permission solely to write the PNG image and cannot read your existing photos. When you copy or share a sticker or weekly recap, you decide where it goes. Paradeiser never sends anything on its own.</p>

          <h3>7. Purchases and subscriptions</h3>
          <p>Purchases of Paradeiser Plus (monthly, yearly or lifetime) are handled entirely by Apple through the App Store (StoreKit). I receive no payment details and no data that identifies you personally. The app only checks on your device whether an entitlement is active.</p>

          <h3>8. Notifications and Live Activities</h3>
          <p>Phase completion alerts are scheduled as local notifications on your device. Lock Screen and Dynamic Island Live Activities display timer state that stays entirely on your device.</p>

          <h3>9. Crash reports and statistics from Apple</h3>
          <p>If you agreed in iOS Settings to share analytics with app developers, Apple gives me anonymised crash reports and aggregated usage statistics (such as the number of installs). These don't let me identify you. You can turn this off under <em>Privacy &amp; Security &rsaquo; Analytics &amp; Improvements</em>.</p>

          <h3>10. This website</h3>
          <p>When you visit lukasgeyer.com, the hosting provider GitHub, Inc. (USA) processes, through GitHub Pages, technically necessary data such as your IP address, the date and time and the page requested, in order to deliver and secure the website (Art. 6(1)(f) GDPR). GitHub may process this data in the USA; the transfer relies on the EU-U.S. Data Privacy Framework. See <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener noreferrer">GitHub's privacy statement</a>. The website uses no cookies and no analytics tools.</p>

          <h3>11. Your rights</h3>
          <p>Under the GDPR you have the right of access, rectification, erasure, restriction of processing, data portability and objection. Since I store no personal data about you, I can usually only confirm that there is none. Just write to the email address above.</p>
          <p>You also have the right to lodge a complaint with a supervisory authority. In Austria this is the <a href="https://www.dsb.gv.at" target="_blank" rel="noopener noreferrer">Austrian Data Protection Authority</a> (Datenschutzbehörde), Barichgasse 40–42, 1030 Vienna.</p>

          <h3>12. Changes</h3>
          <p>If Paradeiser changes, I will update this privacy policy. The version published here always applies. See the <a href="/imprint/#en">legal notice</a> for provider details.</p>
        </div>
      </article>
    </div>
    """


def muninn_privacy(muninn_email: str) -> str:
    return f"""
    <div class="legal">
      <div class="legal-bar">
        <a href="/muninn/">&larr; Back to Muninn</a>
        <nav class="lang-switch" aria-label="Language">
          <a href="#de" lang="de" hreflang="de">Deutsch</a>
          <a href="#en" hreflang="en">English</a>
        </nav>
      </div>

      <article id="de" lang="de">
        <header class="legal-header">
          <p class="eyebrow">
            <span>Datenschutzerklärung</span>
            <span>&middot;</span>
            <span>Muninn</span>
            <span>&middot;</span>
            <span>Stand: 25. November 2026</span>
          </p>
          <h1 class="legal-title">Datenschutzerklärung für Muninn</h1>
        </header>
        <div class="prose">
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
        <header class="legal-header">
          <p class="eyebrow">
            <span>Privacy Policy</span>
            <span>&middot;</span>
            <span>Muninn</span>
            <span>&middot;</span>
            <span>Last updated: 25 November 2026</span>
          </p>
          <h2 class="legal-title">Muninn Privacy Policy</h2>
        </header>
        <div class="prose">
          <div class="legal-summary">
            <p><strong>In short:</strong> Muninn needs no account, shows no ads, contains no analytics or tracking tools and currently runs no servers of its own. Your decks, cards, images and review history stay on your device. I, the developer, have no access to them.</p>
          </div>

          <h3>1. Controller</h3>
          <address class="legal-address">
            Lukas Geyer<br />
            Ghegagasse 13/32<br />
            8020 Graz, Austria<br />
            Email: <a href="mailto:{muninn_email}">{muninn_email}</a>
          </address>

          <h3>2. Data on your device</h3>
          <p>Everything you create, import and record while studying in Muninn – decks, cards with their text, images and sounds, tags, your review history with ratings and times, and your settings – is stored and processed locally on your device. This data is not sent to me or to third parties. If you delete the app, this data is deleted too.</p>
          <p>If you have turned on iCloud Backup or a backup to a computer for your device, Apple backs up the app's data along with that of your other apps. <a href="https://www.apple.com/legal/privacy/" target="_blank" rel="noopener noreferrer">Apple's Privacy Policy</a> applies to that.</p>

          <h3>3. Importing and exporting decks</h3>
          <p>When you import a deck (for example an Anki file), Muninn reads the file you chose on your device. When you export a deck, Muninn creates a file and hands it to your device's share sheet; where it goes is your decision. Muninn sends nothing by itself.</p>

          <h3>4. Photos and files (optional)</h3>
          <p>When you add an image to a card, you choose it from your photos or files through Apple's picker. Muninn receives only the images you choose and has no access to the rest of your library. The chosen image is stored in Muninn on your device.</p>

          <h3>5. Sync (planned)</h3>
          <p>Syncing between your own devices is planned as an option you turn on yourself. Before it becomes available, this page will say how it works and where data is stored. Until then nothing leaves your device.</p>

          <h3>6. Crash reports and statistics from Apple</h3>
          <p>If you agreed in iOS Settings to share analytics with app developers, Apple gives me anonymised crash reports and aggregated usage statistics (such as the number of installs). These don't let me identify you. You can turn this off under <em>Privacy &amp; Security &rsaquo; Analytics &amp; Improvements</em>. If you use a test version through TestFlight, Apple's terms for TestFlight apply to it as well.</p>

          <h3>7. This website</h3>
          <p>When you visit lukasgeyer.com, the hosting provider GitHub, Inc. (USA) processes, through GitHub Pages, technically necessary data such as your IP address, the date and time and the page requested, in order to deliver and secure the website (Art. 6(1)(f) GDPR). GitHub may process this data in the USA; the transfer relies on the EU-U.S. Data Privacy Framework. See <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener noreferrer">GitHub's privacy statement</a>. The website uses no cookies and no analytics tools.</p>

          <h3>8. Your rights</h3>
          <p>Under the GDPR you have the right of access, rectification, erasure, restriction of processing, data portability and objection. As I store no personal data about you, I can usually only confirm that there is none. Feel free to write to the email address above.</p>
          <p>You can also lodge a complaint with a supervisory authority. In Austria this is the <a href="https://www.dsb.gv.at" target="_blank" rel="noopener noreferrer">Austrian Data Protection Authority</a>, Barichgasse 40–42, 1030 Vienna.</p>

          <h3>9. Changes</h3>
          <p>If Muninn changes, I will update this privacy policy. The version published here always applies. See the <a href="/imprint/#en">legal notice</a> for provider details.</p>
        </div>
      </article>
    </div>
    """


def imprint(support_email: str, site_email: str) -> str:
    return f"""
    <div class="legal">
      <div class="legal-bar">
        <a href="/">&larr; Home</a>
        <nav class="lang-switch" aria-label="Language">
          <a href="#de" lang="de" hreflang="de">Deutsch</a>
          <a href="#en" hreflang="en">English</a>
        </nav>
      </div>

      <article id="de" lang="de">
        <header class="legal-header">
          <p class="eyebrow">
            <span>Impressum</span>
            <span>&middot;</span>
            <span>lukasgeyer.com &middot; Semestra &middot; Paradeiser &middot; Muninn</span>
          </p>
          <h1 class="legal-title">Impressum</h1>
          <p class="legal-subtitle">Informationen gemäß &sect;&nbsp;5 ECG und Offenlegung gemäß &sect;&nbsp;25 MedienG</p>
        </header>
        <div class="prose">
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
        <header class="legal-header">
          <p class="eyebrow">
            <span>Legal Notice</span>
            <span>&middot;</span>
            <span>lukasgeyer.com &middot; Semestra &middot; Paradeiser &middot; Muninn</span>
          </p>
          <h2 class="legal-title">Legal Notice</h2>
          <p class="legal-subtitle">Information under &sect;&nbsp;5 ECG and disclosure under &sect;&nbsp;25 MedienG (Austrian law)</p>
        </header>
        <div class="prose">
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

          <h3>Copyright</h3>
          <p>The content of this website – text, images and the apps shown – is protected by copyright. Any use beyond private reading needs my permission.</p>

          <h3>Liability for links</h3>
          <p>This website contains links to third-party websites. Their operators alone are responsible for their content. If I become aware of any legal violations on linked pages, I will remove the link immediately.</p>

          <h3>Privacy</h3>
          <p>How the apps and this website handle data is described in the privacy policies for <a href="/semestra/privacy-policy/#en">Semestra</a>, <a href="/paradeiser/privacy-policy/#en">Paradeiser</a> and <a href="/muninn/privacy/">Muninn</a>.</p>
          <p class="legal-updated">Last updated: 24 November 2026</p>
        </div>
      </article>
    </div>
    """


# ---------------------------------------------------------------- Feeds

def rss_feed(site: dict, updates: dict[str, list[dict]]) -> str:
    """The feed of app updates: one item per changelog entry, newest first."""
    site_url = site.get("url", "").rstrip("/")
    entries = sorted(
        (
            {
                "date": u["date"],
                "title": f"{site[key]['name']} {u['version']}: {u['title']}",
                "link": site_url + u["url"],
                "description": u["highlights"],
            }
            for key in APP_KEYS
            for u in updates[key]
        ),
        key=lambda item: item["date"],
        reverse=True,
    )
    permalink_attr = "true" if site_url else "false"
    items = "\n".join(
        f"""  <item>
    <title>{html.escape(item['title'])}</title>
    <link>{html.escape(item['link'])}</link>
    <guid isPermaLink="{permalink_attr}">{html.escape(item['link'])}</guid>
    <pubDate>{rfc822(item['date'])}</pubDate>
    <description>{html.escape(item['description'])}</description>
  </item>"""
        for item in entries
    )
    channel_links = (
        f"  <link>{html.escape(site_url)}/</link>\n"
        f'  <atom:link href="{html.escape(site_url)}/rss.xml" rel="self" type="application/rss+xml" />\n'
        if site_url
        else ""
    )
    last_build = f"  <lastBuildDate>{rfc822(entries[0]['date'])}</lastBuildDate>\n" if entries else ""
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{html.escape(site['name'])}</title>
{channel_links}  <description>{html.escape(site['tagline'])}</description>
  <language>en</language>
{last_build}{items}
</channel>
</rss>
"""


def sitemap(site_url: str, updates: dict[str, list[dict]]) -> str:
    pages: list[tuple[str, datetime.date | None]] = [("/", None)]
    for key in APP_KEYS:
        pages.append((f"/{key}/", updates[key][0]["date"] if updates[key] else None))
        pages.append((PRIVACY_PATHS[key], None))
    pages += [("/imprint/", None), ("/about/", None)]
    urls = "\n".join(
        f"  <url><loc>{html.escape(site_url + path)}</loc>"
        + (f"<lastmod>{date.isoformat()}</lastmod>" if date else "")
        + "</url>"
        for path, date in pages
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n</urlset>\n"
    )


# ---------------------------------------------------------------- Build

def build() -> None:
    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    site_url = site.get("url", "").rstrip("/")
    updates = {key: load_updates(key) for key in APP_KEYS}
    site_email = html.escape(site["email"])
    emails = {key: html.escape(site[key].get("support_email", site["email"]).strip()) for key in APP_KEYS}

    shutil.rmtree(DIST, ignore_errors=True)
    shutil.copytree(ASSETS, DIST)  # everything in assets/ is published as-is
    with (DIST / "styles.css").open("a", encoding="utf-8") as stylesheet:
        stylesheet.write(accent_css(site))
    (DIST / "favicon.svg").write_text(favicon_svg(site), encoding="utf-8")

    # Browsers keep stylesheets and scripts for a while. The address changes with the content, so
    # a new design never meets an old stylesheet.
    digest = hashlib.sha256((DIST / "styles.css").read_bytes() + (DIST / "site.js").read_bytes())
    asset_version = f"?v={digest.hexdigest()[:10]}"

    def write_page(file: str, **kwargs) -> None:
        target = DIST / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page_layout(site=site, asset_version=asset_version, **kwargs), encoding="utf-8")

    # 1. Start page
    write_page(
        "index.html",
        title=f"{site['name']} – {site['kicker']}",
        path="/",
        content_html=home_page(site, updates),
        description=f"{site['headline']} {site['intro']}",
    )

    # 2. One page per app, with its changelog
    for key in APP_KEYS:
        write_page(
            f"{key}/index.html",
            title=f"{site[key]['name']} – {site['name']}",
            path=f"/{key}/",
            app_key=key,
            content_html=app_page(site, key, updates[key]),
            description=site[key]["summary"],
        )

    # 3. Privacy policies
    write_page(
        "semestra/privacy-policy/index.html",
        title=f"Semestra Privacy Policy – {site['name']}",
        path="/semestra/privacy-policy/",
        app_key="semestra",
        content_html=semestra_privacy(emails["semestra"]),
        description="Datenschutzerklärung der App Semestra / Privacy policy of the Semestra app.",
    )
    write_page(
        "paradeiser/privacy-policy/index.html",
        title=f"Paradeiser Privacy Policy – {site['name']}",
        path="/paradeiser/privacy-policy/",
        app_key="paradeiser",
        content_html=paradeiser_privacy(emails["paradeiser"]),
        description="Datenschutzerklärung der App Paradeiser / Privacy policy of the Paradeiser app.",
    )
    write_page(
        "muninn/privacy/index.html",
        title=f"Muninn Privacy Policy – {site['name']}",
        path="/muninn/privacy/",
        app_key="muninn",
        content_html=muninn_privacy(emails["muninn"]),
        description="Datenschutzerklärung der App Muninn / Privacy policy of the Muninn app.",
    )

    # /paradeiser/privacy/ is an older address of the policy: it forwards to the current one.
    (DIST / "paradeiser" / "privacy").mkdir(parents=True, exist_ok=True)
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

    # 4. About, imprint and the not-found page (GitHub Pages serves 404.html for unknown addresses)
    write_page(
        "about/index.html",
        title=f"About – {site['name']}",
        path="/about/",
        content_html=about_page(site),
        description="About Lukas Geyer and the apps Semestra, Paradeiser and Muninn.",
    )
    write_page(
        "imprint/index.html",
        title=f"Imprint – {site['name']}",
        path="/imprint/",
        content_html=imprint(emails["semestra"], site_email),
        description="Impressum / Legal Notice for lukasgeyer.com and the apps Semestra, Paradeiser and Muninn.",
    )
    write_page("404.html", title=f"Page not found – {site['name']}", path=None, content_html=NOT_FOUND_PAGE)

    # 5. RSS feed, sitemap and robots.txt
    (DIST / "rss.xml").write_text(rss_feed(site, updates), encoding="utf-8")
    robots = "User-agent: *\nAllow: /\n"
    if site_url:
        (DIST / "sitemap.xml").write_text(sitemap(site_url, updates), encoding="utf-8")
        robots += f"Sitemap: {site_url}/sitemap.xml\n"
    (DIST / "robots.txt").write_text(robots, encoding="utf-8")

    # 6. GitHub Pages metadata (.nojekyll and CNAME)
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    if site_url:
        host = urllib.parse.urlsplit(site_url).hostname
        if host:
            (DIST / "CNAME").write_text(f"{host}\n", encoding="utf-8")

    counts = ", ".join(f"{len(updates[key])} {site[key]['name']}" for key in APP_KEYS)
    print(f"Built the site with changelog entries for {counts} into {DIST}")


if __name__ == "__main__":
    build()
