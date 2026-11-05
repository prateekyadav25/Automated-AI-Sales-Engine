"""Read brand facts from fetched HTML. Deterministic. No model and no browser.

Every finding keeps the markup or sentence it came from. A page that says
nothing produces nothing. Claims are always returned for human review.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

SOCIAL_HOSTS = {
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "x.com": "x",
    "twitter.com": "x",
    "youtube.com": "youtube",
    "tiktok.com": "tiktok",
}
CRAWL_HINTS = (
    "about", "service", "product", "solution", "pricing", "plan", "contact", "location",
    "industr", "platform", "feature", "company", "offer", "who-we", "what-we",
)
OFFER_PAGE_HINTS = ("service", "product", "solution", "offer", "platform", "feature", "pricing", "plan")
SKIP_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".mp4", ".mov", ".xml", ".css", ".js", ".ico")
CLAIM_PATTERN = re.compile(
    r"(\b\d[\d,.]*\s?(?:%|\+|x\b|[a-z]{3,}\b))|\b(?:award|awarded|certified|certification|"
    r"iso\s?\d{3,5}|#1|number one|leading|best|top-rated|trusted by|guarantee[sd]?|fastest|largest|only)\b",
    re.IGNORECASE,
)
GENERIC_HEADINGS = {
    "our services", "services", "our products", "products", "solutions", "our solutions", "contact us", "contact",
    "about us", "about", "why choose us", "get in touch", "testimonials", "faq", "faqs", "blog", "news", "home",
    "our team", "team", "careers", "pricing", "features", "learn more", "read more", "follow us",
}
STOPWORDS = set(
    """a about above after again all also am an and any are as at be because been before being below between both but by
    can could did do does doing down during each few for from further had has have having he her here hers him his how i if in
    into is it its itself just me more most my no nor not now of off on once only or other our ours out over own same she should
    so some such than that the their theirs them then there these they this those through to too under until up very was we
    were what when where which while who whom why will with you your yours us get got may might must one two new use using
    make made like well also need help helps work works way ways every many much really great""".split()
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_WS = re.compile(r"\s+")


@dataclass
class Finding:
    category: str
    statement: str
    value: str = ""
    evidence: str = ""
    confidence: int = 70


@dataclass
class PageExtract:
    url: str
    title: str = ""
    description: str = ""
    text: str = ""
    headings: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    logo_urls: list[str] = field(default_factory=list)


class _Parser(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.anchors: list[tuple[str, str]] = []
        self.icons: list[tuple[str, str]] = []
        self.logo_imgs: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self.jsonld: list[str] = []
        self.styles: list[str] = []
        self.text: list[str] = []
        self._skip = 0
        self._in_title = False
        self._jsonld: list[str] | None = None
        self._style: list[str] | None = None
        self._anchor: list | None = None
        self._heading: list | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if values.get("style"):
            self.styles.append(values["style"])
        if tag == "meta":
            key = (values.get("name") or values.get("property") or values.get("itemprop") or "").strip().lower()
            content = values.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
            return
        if tag == "link":
            rel = values.get("rel", "").lower()
            href = values.get("href", "").strip()
            if href and ("icon" in rel or "apple-touch-icon" in rel):
                self.icons.append((rel, href))
            if href and rel == "canonical":
                self.meta.setdefault("canonical", href)
            return
        if tag == "img":
            marker = " ".join(values.get(name, "") for name in ("class", "id", "alt", "src")).lower()
            if "logo" in marker and values.get("src"):
                self.logo_imgs.append(values["src"].strip())
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "script" and "ld+json" in values.get("type", "").lower():
            self._jsonld = []
            return
        if tag == "style":
            self._style = []
            return
        if tag in self._SKIP:
            self._skip += 1
            return
        if tag == "a":
            self._anchor = [values.get("href", "").strip(), []]
        if tag in {"h1", "h2", "h3"}:
            self._heading = [int(tag[1]), []]

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._jsonld is not None:
            self.jsonld.append("".join(self._jsonld))
            self._jsonld = None
        elif tag == "style" and self._style is not None:
            self.styles.append("".join(self._style))
            self._style = None
        elif tag in self._SKIP and self._skip > 0:
            self._skip -= 1
        elif tag == "a" and self._anchor is not None:
            self.anchors.append((self._anchor[0], _clean(" ".join(self._anchor[1]))))
            self._anchor = None
        elif tag in {"h1", "h2", "h3"} and self._heading is not None:
            text = _clean(" ".join(self._heading[1]))
            if text:
                self.headings.append((self._heading[0], text))
            self._heading = None
        if tag in {"p", "li", "div", "section", "br", "h1", "h2", "h3", "h4", "td"}:
            self.text.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._jsonld is not None:
            self._jsonld.append(data)
            return
        if self._style is not None:
            self._style.append(data)
            return
        if self._skip:
            return
        if self._anchor is not None:
            self._anchor[1].append(data)
        if self._heading is not None:
            self._heading[1].append(data)
        self.text.append(data)


def _clean(value: str) -> str:
    return _WS.sub(" ", value or "").strip()


def site_host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    path = parts.path or "/"
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))


def _walk_jsonld(node, found: list[dict]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_jsonld(item, found)
        return
    if not isinstance(node, dict):
        return
    if "@type" in node:
        found.append(node)
    for key in ("@graph", "mainEntity", "itemListElement", "hasOfferCatalog", "makesOffer", "itemOffered", "offers"):
        if key in node:
            _walk_jsonld(node[key], found)


def _types(node: dict) -> set[str]:
    raw = node.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return {str(item).lower() for item in values if item}


def _text_of(value) -> str:
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, dict):
        return _clean(str(value.get("name") or value.get("url") or value.get("@id") or ""))
    return ""


def _address(value) -> str:
    if isinstance(value, str):
        return _clean(value)
    if not isinstance(value, dict):
        return ""
    parts = [value.get(key) for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")]
    return ", ".join(_text_of(part) for part in parts if _text_of(part))


def _social_platform(url: str) -> str:
    host = site_host(url)
    for domain, platform in SOCIAL_HOSTS.items():
        if host == domain or host.endswith(f".{domain}"):
            return platform
    return ""


def _short(text: str, limit: int = 300) -> str:
    cleaned = _clean(text)
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def _brand_colors(meta: dict[str, str], styles: list[str]) -> list[Finding]:
    found: list[Finding] = []
    for key, confidence in (("theme-color", 90), ("msapplication-tilecolor", 80)):
        value = meta.get(key, "").strip()
        if _HEX.fullmatch(value):
            found.append(Finding("color", f"Brand colour {expand_hex(value)} is declared in the {key} tag.", expand_hex(value), f'<meta name="{key}" content="{value}">', confidence))
    counts: Counter[str] = Counter()
    for style in styles:
        for match in _HEX.findall(style):
            color = expand_hex(match)
            if not _is_neutral(color):
                counts[color] += 1
    for color, count in counts.most_common(4):
        if count >= 2 and all(item.value != color for item in found):
            found.append(Finding("color", f"Colour {color} appears {count} times in the page styles.", color, f"{count} style declarations", 60))
    return found


def expand_hex(value: str) -> str:
    raw = value.strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return f"#{raw.lower()}"


def _is_neutral(color: str) -> bool:
    red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
    return max(red, green, blue) - min(red, green, blue) < 18


def sentences(text: str) -> list[str]:
    rows: list[str] = []
    for block in (text or "").split("\n"):
        for part in _SENTENCE.split(_clean(block)):
            part = part.strip()
            if part:
                rows.append(part)
    return rows


def extract_page(url: str, html: str) -> PageExtract:
    parser = _Parser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:  # noqa: BLE001 - a malformed page yields what was parsed so far
        pass
    meta = parser.meta
    page = PageExtract(url=url, title=_clean(parser.title))
    page.description = _clean(meta.get("description") or meta.get("og:description") or "")
    page.text = "\n".join(_clean(part) for part in "".join(parser.text).split("\n") if _clean(part))
    page.headings = [text for _level, text in parser.headings]
    host = site_host(url)
    links: list[str] = []
    for href, _label in parser.anchors:
        absolute = normalize_url(urljoin(url, href)) if href and not href.startswith(("mailto:", "tel:", "javascript:", "#")) else ""
        if absolute and site_host(absolute) == host and not absolute.lower().endswith(SKIP_EXTENSIONS) and absolute not in links:
            links.append(absolute)
    page.links = links
    findings = page.findings
    nodes: list[dict] = []
    for block in parser.jsonld:
        try:
            _walk_jsonld(json.loads(block), nodes)
        except ValueError:
            continue
    for node in nodes:
        kinds = _types(node)
        name = _text_of(node.get("name"))
        evidence = _short(json.dumps({key: node.get(key) for key in ("@type", "name") if key in node}, default=str), 200)
        if kinds & {"organization", "corporation", "localbusiness", "professionalservice", "store", "brand"}:
            if name:
                findings.append(Finding("company_name", name, name, evidence, 90))
            description = _text_of(node.get("description"))
            if description:
                findings.append(Finding("description", description, "", _short(description), 85))
            logo = _text_of(node.get("logo"))
            if logo:
                page.logo_urls.append(urljoin(url, logo))
            same_as = node.get("sameAs") or []
            for item in same_as if isinstance(same_as, list) else [same_as]:
                link = _text_of(item)
                platform = _social_platform(link)
                if platform:
                    findings.append(Finding("social_profile", f"{platform.title()} profile: {link}", link, "schema.org sameAs", 90))
            for key in ("telephone", "email"):
                value = _text_of(node.get(key))
                if value:
                    findings.append(Finding("contact", f"{key.title()}: {value}", value, f"schema.org {key}", 90))
            address = _address(node.get("address"))
            if address:
                findings.append(Finding("location", address, address, "schema.org address", 90))
            served = node.get("areaServed")
            for item in served if isinstance(served, list) else [served]:
                area = _text_of(item)
                if area:
                    findings.append(Finding("location", f"Serves {area}", area, "schema.org areaServed", 80))
        if kinds & {"product", "softwareapplication"} and name:
            detail = _text_of(node.get("description"))
            findings.append(Finding("product", name if not detail else f"{name}: {detail}", name, evidence, 85))
        if kinds & {"service"} and (name or _text_of(node.get("serviceType"))):
            label = name or _text_of(node.get("serviceType"))
            detail = _text_of(node.get("description"))
            findings.append(Finding("service", label if not detail else f"{label}: {detail}", label, evidence, 85))
        if kinds & {"postaladdress"}:
            address = _address(node)
            if address:
                findings.append(Finding("location", address, address, "schema.org PostalAddress", 85))
    site_name = _clean(meta.get("og:site_name") or meta.get("application-name") or "")
    if site_name:
        findings.append(Finding("company_name", site_name, site_name, "og:site_name", 85))
    if page.description:
        findings.append(Finding("description", page.description, "", "meta description", 80))
    for href, label in parser.anchors:
        if href.startswith("mailto:"):
            email = href[7:].split("?", 1)[0].strip()
            if "@" in email:
                findings.append(Finding("contact", f"Email: {email}", email, _short(label or href, 120), 80))
        elif href.startswith("tel:"):
            phone = href[4:].strip()
            if sum(ch.isdigit() for ch in phone) >= 7:
                findings.append(Finding("contact", f"Telephone: {phone}", phone, _short(label or href, 120), 80))
        else:
            absolute = urljoin(url, href)
            platform = _social_platform(absolute)
            if platform and urlsplit(absolute).path.strip("/"):
                findings.append(Finding("social_profile", f"{platform.title()} profile: {absolute}", absolute, "linked from the site", 80))
    for src in parser.logo_imgs:
        page.logo_urls.append(urljoin(url, src))
    for rel, href in parser.icons:
        if "apple-touch-icon" in rel:
            page.logo_urls.append(urljoin(url, href))
    path = urlsplit(url).path.lower()
    if any(hint in path for hint in OFFER_PAGE_HINTS):
        for level, heading in parser.headings:
            words = heading.split()
            if level == 1 or not (2 <= len(words) <= 8) or heading.casefold() in GENERIC_HEADINGS or heading.endswith("?"):
                continue
            category = "product" if "product" in path or "platform" in path else "service"
            findings.append(Finding(category, heading, heading, f"h{level} on {path}", 60))
    for sentence in sentences(page.text):
        if 25 <= len(sentence) <= 260 and CLAIM_PATTERN.search(sentence):
            findings.append(Finding("claim", sentence, "", sentence, 70))
    findings.extend(_brand_colors(meta, parser.styles))
    return page


def crawl_candidates(home: PageExtract, limit: int) -> list[str]:
    def rank(url: str) -> tuple[int, int]:
        path = urlsplit(url).path.lower()
        hinted = 0 if any(hint in path for hint in CRAWL_HINTS) else 1
        return hinted, len(path)

    ordered = sorted((link for link in home.links if link != home.url), key=rank)
    return ordered[:limit]


def robots_disallows(robots: str, path: str, agent: str = "salesenginebrandreader") -> bool:
    """True when a group for this agent, or for *, disallows the path."""
    groups: list[tuple[set[str], list[str], list[str]]] = []
    agents: set[str] = set()
    rules: list[str] = []
    allows: list[str] = []
    reading_agents = False
    for raw in (robots or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not reading_agents and (agents or rules or allows):
                groups.append((agents, rules, allows))
                agents, rules, allows = set(), [], []
            agents.add(value.lower())
            reading_agents = True
            continue
        reading_agents = False
        if key == "disallow":
            rules.append(value)
        elif key == "allow":
            allows.append(value)
    if agents:
        groups.append((agents, rules, allows))
    chosen = [group for group in groups if agent in group[0]] or [group for group in groups if "*" in group[0]]
    for _agents, disallow, allow in chosen:
        blocked = max((len(rule) for rule in disallow if rule and path.startswith(rule)), default=-1)
        permitted = max((len(rule) for rule in allow if rule and path.startswith(rule)), default=-1)
        if blocked > permitted:
            return True
    return False


def keyphrases(texts: list[str], limit: int = 8) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for text in texts:
        words = [word for word in re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", text.lower()) if word not in STOPWORDS]
        counts.update(words)
        counts.update(f"{left} {right}" for left, right in zip(words, words[1:], strict=False) if left != right)
    chosen: list[tuple[str, int]] = []
    for phrase, count in counts.most_common(80):
        if count < 3:
            break
        if any(phrase in kept or kept in phrase for kept, _ in chosen):
            continue
        chosen.append((phrase, count))
        if len(chosen) >= limit:
            break
    return chosen


def voice_profile(texts: list[str]) -> dict:
    rows = [row for text in texts for row in sentences(text) if len(row.split()) >= 4]
    if not rows:
        return {"sentences": 0}
    words = [len(row.split()) for row in rows]
    second = sum(1 for row in rows if re.search(r"\byou(r|rs)?\b", row, re.I))
    first = sum(1 for row in rows if re.search(r"\b(we|our|us)\b", row, re.I))
    exclaim = sum(1 for row in rows if row.endswith("!"))
    questions = sum(1 for row in rows if row.endswith("?"))
    syllables = sum(_syllables(word) for row in rows for word in row.split())
    total_words = sum(words)
    flesch = 206.835 - 1.015 * (total_words / len(rows)) - 84.6 * (syllables / max(total_words, 1))
    return {
        "sentences": len(rows),
        "average_sentence_words": round(total_words / len(rows), 1),
        "second_person_share": round(second / len(rows), 2),
        "first_person_plural_share": round(first / len(rows), 2),
        "exclamation_share": round(exclaim / len(rows), 2),
        "question_share": round(questions / len(rows), 2),
        "reading_ease": round(flesch, 1),
    }


def _syllables(word: str) -> int:
    letters = re.sub(r"[^a-z]", "", word.lower())
    if not letters:
        return 0
    groups = re.findall(r"[aeiouy]+", letters)
    count = len(groups)
    if letters.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def hashtags(captions: list[str], limit: int = 8) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter(tag.lower() for caption in captions for tag in re.findall(r"#([A-Za-z0-9_]{2,40})", caption or ""))
    return [(tag, count) for tag, count in counts.most_common(limit) if count >= 2]
