"""Build the static Jake site from its design assets and repository documentation."""
from __future__ import annotations

import argparse
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlparse

import markdown

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "website"
DOCS = [
    ("docs/INSTALL.md", "install", "Installation", "System dependencies, setup, and first-run checks.", "Start here"),
    ("docs/CONTROLS.md", "controls", "Daily controls", "Voice, keyboard, models, and reasoning settings.", "Start here"),
    ("docs/MODELS.md", "models", "Speech models", "Prepare local speech models and verify downloads.", "Start here"),
    ("docs/FAQ.md", "faq", "Questions & answers", "Platform support, privacy, and project status.", "Start here"),
    ("docs/PRIVACY.md", "privacy", "Privacy", "Where your voice and requests go.", "Your controls"),
    ("SECURITY.md", "security", "Security", "Permission profiles, approvals, and trust boundaries.", "Your controls"),
    ("docs/ARCHITECTURE.md", "architecture", "Architecture", "The components behind the companion.", "Build with us"),
    ("docs/PROTOCOL.md", "protocol", "Protocol", "The local Codex integration contract.", "Build with us"),
    ("docs/PERFORMANCE.md", "performance", "Performance", "Measurements, resource use, and limitations.", "Build with us"),
    ("docs/TESTING.md", "testing", "Testing", "Run checks and validate the native desktop.", "Build with us"),
    ("docs/IMPLEMENTATION.md", "implementation", "Implementation status", "What is implemented and what still needs validation.", "Build with us"),
    ("CONTRIBUTING.md", "contributing", "Contributing", "Help improve the project.", "Build with us"),
    ("docs/WEBSITE.md", "website", "Website & deployment", "Build the documentation and publish with GitHub Pages.", "Build with us"),
    ("CHANGELOG.md", "changelog", "Changelog", "What has changed in Jake.", "Project"),
    ("LICENSE", "license", "License", "MIT-licensed source, with separate model licenses.", "Project"),
]


def build(destination: Path, base: str, repository: str) -> None:
    parsed = urlparse(base)
    if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("The base URL must be a complete HTTP(S) URL without a query or fragment")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repository must be owner/name")
    base = base.rstrip("/")
    prefix = parsed.path.rstrip("/") + "/"
    repo = "https://github.com/" + repository
    destination.mkdir(parents=True, exist_ok=True)
    assets = destination / "assets"
    assets.mkdir(exist_ok=True)
    for path in (WEB / "assets").iterdir():
        if path.is_file() and path.suffix != ".glsl":
            shutil.copyfile(path, assets / path.name)
    for path in (ROOT / "docs/assets").iterdir():
        if path.is_file():
            shutil.copyfile(path, assets / path.name)
    routes = {(ROOT / source).resolve(): prefix + "docs/" + slug + "/" for source, slug, *_ in DOCS}
    routes[ROOT / "README.md"] = prefix
    index = []
    urls = []
    layout = (WEB / "layout.html").read_text()

    def link(value: str, source: Path) -> str:
        parsed_link = urlparse(html.unescape(value))
        if parsed_link.scheme or parsed_link.netloc or not parsed_link.path or parsed_link.path.startswith("/"):
            return value
        target = (source.parent / unquote(parsed_link.path)).resolve()
        if target in routes:
            result = routes[target]
        elif target.parent == ROOT / "docs/assets":
            result = prefix + "assets/" + target.name
        elif target.is_relative_to(ROOT):
            result = repo + "/blob/main/" + target.relative_to(ROOT).as_posix()
        else:
            raise ValueError("Documentation link leaves repository: " + value)
        if parsed_link.fragment:
            result += "#" + parsed_link.fragment
        return html.escape(result, quote=True)

    def substitute(value: str, fields: dict[str, str]) -> str:
        return re.sub(r"\{\{([a-z_]+)\}\}", lambda m: fields.get(m[1], m[0]), value)

    def write(route: str, title: str, description: str, content: str, page_class: str = "") -> None:
        values = {"root": prefix, "base": base, "repo": repo, "title": html.escape(title),
                  "description": html.escape(description, quote=True), "canonical": base + "/" + route,
                  "content": content, "page_class": page_class}
        content = substitute(content, values)
        values["content"] = content
        output = substitute(layout, values)
        if re.search(r"\{\{[a-z_]+\}\}", output):
            raise ValueError("Unresolved template field in " + route)
        target = destination / route / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output)
        urls.append(base + "/" + route)

    def navigation(current: str) -> str:
        links = ['<a href="' + prefix + 'docs/"' + (' aria-current="page"' if not current else '') + '>Overview</a>']
        group = ""
        for _, slug, title, _, section in DOCS:
            if group != section:
                links.append('<span class="sidebar-group">' + section.upper() + '</span>')
                group = section
            links.append('<a href="' + prefix + 'docs/' + slug + '/"' + (' aria-current="page"' if current == slug else '') + '>' + html.escape(title) + '</a>')
        return '<aside class="doc-sidebar"><details open><summary>DOCUMENTATION</summary><nav aria-label="Documentation">' + ''.join(links) + '</nav></details></aside>'

    home = (WEB / "home.html").read_text().replace("{{shader}}", (WEB / "assets/orb.glsl").read_text())
    write("", "Jake AI — A voice companion for your Linux desktop", "Meet Jake, an open-source Linux voice companion for Codex. Local speech processing, spoken replies, and visible human controls.", home)
    for source_name, slug, title, description, _ in DOCS:
        source = ROOT / source_name
        raw = source.read_text()
        if source_name == "LICENSE":
            raw = "# License\n\n```text\n" + raw + "\n```\n"
        rendered = markdown.markdown(raw, extensions=["fenced_code", "tables", "toc", "sane_lists"])
        rendered = re.sub(r'(href|src)="([^"]+)"', lambda m: m[1] + '="' + link(m[2], source) + '"', rendered)
        content = '<div class="doc-layout">' + navigation(slug) + '<article class="doc-content"><p class="eyebrow">JAKE AI / DOCUMENTATION</p><div class="prose">' + rendered + '</div><div class="doc-meta"><a href="' + repo + '/blob/main/' + source_name + '">View source ↗</a><a href="' + repo + '/issues">Suggest an improvement ↗</a></div></article></div>'
        write("docs/" + slug + "/", title + " — Jake AI", description, content, "doc-page")
        plain = re.sub(r"<[^>]+>", " ", rendered)
        index.append({"title": title, "description": description, "text": re.sub(r"\s+", " ", html.unescape(plain)), "url": prefix + "docs/" + slug + "/"})
    cards = ''.join('<a href="' + prefix + 'docs/' + slug + '/"><h2>' + html.escape(title) + ' ↗</h2><p>' + html.escape(description) + '</p></a>' for _, slug, title, description, _ in DOCS)
    overview = '<div class="doc-layout">' + navigation("") + '<article class="doc-content"><p class="eyebrow">A GOOD PLACE TO BEGIN</p><div class="prose"><h1>A companion you<br>can understand.</h1><p>Everything you need to install, use, and contribute to Jake. Documentation is built directly from the repository, so it evolves with the code.</p><blockquote><p>Jake is a development proposal. Native desktop/audio and live Codex validation remain in progress. See the implementation status before relying on it for daily work.</p></blockquote></div><div class="doc-card-grid">' + cards + '</div></article></div>'
    write("docs/", "Documentation — Jake AI", "Installation, speech models, daily controls, privacy, architecture, and contribution guides for Jake AI.", overview, "doc-page")
    write("404/", "Page not found — Jake AI", "Find your way back to Jake AI.", '<section class="not-found"><p class="eyebrow">A SMALL DETOUR</p><h1>404</h1><p>This page has wandered off. Let’s get you back to a familiar place.</p><a class="button primary" href="' + prefix + '">Back to Jake ↗</a></section>')
    shutil.copyfile(destination / "404/index.html", destination / "404.html")
    (destination / "search.json").write_text(json.dumps(index, ensure_ascii=False))
    (destination / ".nojekyll").write_text("")
    (destination / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: " + base + "/sitemap.xml\n")
    (destination / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join('<url><loc>' + html.escape(url) + '</loc></url>' for url in urls if not url.endswith('/404/')) + '</urlset>')
    validate(destination, prefix)
    print(f"Built {len(urls)} pages in {destination}. Internal links and assets verified.")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        for key in ("href", "src"):
            if key in attrs:
                self.links.append(attrs[key])


def validate(destination: Path, prefix: str) -> None:
    parsed_pages = {}
    for path in destination.rglob("*.html"):
        parser = Links()
        parser.feed(path.read_text())
        parsed_pages[path.resolve()] = parser
    errors = []
    for path, parser in parsed_pages.items():
        for value in parser.links:
            url = urlparse(value)
            if url.scheme or url.netloc:
                continue
            if url.path.startswith(prefix):
                target = destination / unquote(url.path[len(prefix):])
            elif not url.path:
                target = path
            elif url.path.startswith("/"):
                errors.append(f"{path.name}: path outside site prefix: {value}")
                continue
            else:
                target = path.parent / unquote(url.path)
            if target.is_dir():
                target /= "index.html"
            target = target.resolve()
            if not target.is_file():
                errors.append(f"{path.name}: missing {value}")
            elif url.fragment and target in parsed_pages and unquote(url.fragment) not in parsed_pages[target].ids:
                errors.append(f"{path.name}: missing fragment {value}")
    if errors:
        raise ValueError("Broken site links:\n" + "\n".join(errors))


def main() -> None:
    repository = os.environ.get("GITHUB_REPOSITORY", "ridjan-xhika/JKI")
    owner, name = repository.split("/", 1)
    fallback = "https://" + owner + ".github.io" + ("" if name.lower() == owner.lower() + ".github.io" else "/" + name)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    parser.add_argument("--base-url", default=os.environ.get("PAGES_BASE_URL") or fallback)
    parser.add_argument("--repository", default=repository)
    args = parser.parse_args()
    build(args.output, args.base_url, args.repository)


if __name__ == "__main__":
    main()
