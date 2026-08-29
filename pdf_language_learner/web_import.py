"""Fetch audio/article pages and turn them into safe, plain transcript data."""

from __future__ import annotations

import html as html_module
import ipaddress
import json
import re
import socket
import xml.etree.ElementTree as ElementTree
from io import BytesIO
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader
from pypdf.errors import PdfReadError


MAX_HTML_BYTES = 5_000_000
MAX_PDF_BYTES = 15_000_000
MAX_REDIRECTS = 5
USER_AGENT = "Margin language reader/0.1 (+local educational use)"
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".ogg", ".wav", ".opus")
VIDEO_EXTENSIONS = (".mp4", ".webm", ".m3u8")
LANGUAGE_NAMES = {
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
}
FAZ_CHILDREN_FEED = "https://wie-erklaere-ich-es-meinem-kind.podigee.io/feed/mp3"


class WebImportError(ValueError):
    """A page cannot safely be fetched or does not contain usable HTML."""


@dataclass(frozen=True)
class WebDocument:
    url: str
    title: str
    transcript: list[str]
    audio_url: str | None
    video_url: str | None
    source_language: str | None


def validate_public_url(value: str) -> str:
    """Accept only public HTTP(S) destinations, including every redirect hop."""

    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WebImportError("Enter a complete public http:// or https:// URL")
    if parsed.username or parsed.password:
        raise WebImportError("URLs containing credentials are not supported")

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, UnicodeError, ValueError) as exc:
        raise WebImportError(f"The page host could not be resolved: {exc}") from exc
    if not addresses:
        raise WebImportError("The page host did not resolve to an address")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise WebImportError("Only pages on the public internet can be imported")

    # Fragments are browser-local and should not make otherwise identical
    # documents acquire different history/storage keys.
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def fetch_web_document(value: str) -> WebDocument:
    url = validate_public_url(value)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
    }
    try:
        with httpx.Client(headers=headers, timeout=20, follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                response = client.get(url)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise WebImportError("The page returned an invalid redirect")
                    url = validate_public_url(urljoin(url, location))
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").casefold()
                if "html" not in content_type and "xhtml" not in content_type:
                    raise WebImportError("The URL does not point to an HTML page")
                if len(response.content) > MAX_HTML_BYTES:
                    raise WebImportError("The page is too large to import")
                page_url = str(response.url)
                page_html = response.text
                document = extract_web_document(page_html, page_url)
                transcript_pdf = _transcript_pdf_url(
                    BeautifulSoup(page_html, "html.parser"), page_url
                )
                if transcript_pdf:
                    pdf_transcript = _transcript_from_pdf_url(
                        client, transcript_pdf, referer=page_url
                    )
                    if pdf_transcript:
                        document = replace(document, transcript=pdf_transcript)
                if document.audio_url is None and _is_faz_children_page(document.url):
                    audio_url = _faz_audio_from_public_feed(client, document.title)
                    if audio_url:
                        document = replace(document, audio_url=audio_url)
                return document
    except WebImportError:
        raise
    except httpx.HTTPError as exc:
        raise WebImportError(f"The page could not be downloaded: {exc}") from exc
    raise WebImportError("The page redirected too many times")


def extract_web_document(html: str, url: str) -> WebDocument:
    soup = BeautifulSoup(html, "html.parser")
    title = _page_title(soup)
    if title == "Imported transcript":
        title = _embedded_lesson_title(html, url) or title
    transcript = _embedded_transcript(html)
    if not transcript:
        transcript = _dom_transcript(soup, url)
    audio_url = _audio_url(soup, html, url)
    video_url = _video_url(soup, html, url)
    language = (soup.html.get("lang", "") if soup.html else "").split("-")[0].casefold()
    return WebDocument(
        url=url,
        title=title,
        transcript=transcript,
        audio_url=audio_url,
        video_url=video_url,
        source_language=LANGUAGE_NAMES.get(language),
    )


def _page_title(soup: BeautifulSoup) -> str:
    meta = soup.select_one('meta[property="og:title"], meta[name="twitter:title"]')
    value = meta.get("content", "") if meta else ""
    if not value:
        heading = soup.find("h1")
        value = heading.get_text(" ", strip=True) if heading else ""
    if not value and soup.title:
        value = soup.title.get_text(" ", strip=True)
    return _clean_text(value) or "Imported transcript"


def _embedded_lesson_title(source: str, url: str) -> str | None:
    """Read the current DW lesson name when its server shell has no title."""

    host = (urlsplit(url).hostname or "").casefold()
    lesson_id = re.search(r"/l-(\d+)(?:/|$)", urlsplit(url).path)
    if not host.endswith("learngerman.dw.com") or not lesson_id:
        return None
    match = re.search(
        rf'"Lesson:{lesson_id.group(1)}"\s*:\s*\{{.*?'
        r'"name"\s*:\s*"((?:\\.|[^"\\])*)"',
        source,
        re.DOTALL,
    )
    if not match:
        return None
    try:
        return _clean_text(json.loads(f'"{match.group(1)}"')) or None
    except json.JSONDecodeError:
        return None


def _embedded_transcript(source: str) -> list[str]:
    # DW lesson pages expose the complete selectable manuscript as an escaped
    # HTML string in their Apollo state. The same fallback also covers sites
    # that use the conventional articleBody or transcript JSON fields.
    for field in ("manuscript", "transcript", "articleBody"):
        match = re.search(
            rf'"{field}"\s*:\s*"((?:\\.|[^"\\])*)"', source, re.DOTALL
        )
        if not match:
            continue
        try:
            value = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            continue
        paragraphs = _html_paragraphs(value)
        if len(" ".join(paragraphs)) >= 80:
            return paragraphs
    return []


def _dom_transcript(soup: BeautifulSoup, url: str) -> list[str]:
    host = (urlsplit(url).hostname or "").casefold()
    selectors = []
    if host.endswith("deutsch-to-go.de"):
        selectors.extend((".entry-content", ".post-content", ".content"))
    selectors.extend(
        (
            '[itemprop="articleBody"]',
            "main article",
            "article",
            "main",
        )
    )
    candidates: list[list[str]] = []
    seen_nodes: set[int] = set()
    for selector in selectors:
        for node in soup.select(selector):
            if id(node) in seen_nodes:
                continue
            seen_nodes.add(id(node))
            clone = BeautifulSoup(str(node), "html.parser")
            for unwanted in clone.select(
                "script,style,noscript,nav,form,button,aside,footer,header,"
                ".advertisement,.ad,.social,.share,.related,.comments"
            ):
                unwanted.decompose()
            paragraphs = _block_paragraphs(clone)
            if len(" ".join(paragraphs)) >= 80:
                candidates.append(paragraphs)
    return max(candidates, key=lambda values: len(" ".join(values)), default=[])


def _html_paragraphs(value: str) -> list[str]:
    fragment = BeautifulSoup(html_module.unescape(value), "html.parser")
    paragraphs = _block_paragraphs(fragment)
    if paragraphs:
        return paragraphs
    text = _clean_text(fragment.get_text(" ", strip=True))
    return [text] if text else []


def _block_paragraphs(node: BeautifulSoup | Tag) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for block in node.select("p, h2, h3, blockquote, li"):
        # A separator passed to get_text() also lands on both sides of DW's
        # inline glossary spans, turning words such as "Stiftungsgeldern" into
        # "Stiftungs geldern". Only explicit line breaks need a separator.
        for line_break in block.select("br"):
            line_break.replace_with(" ")
        value = _clean_text(block.get_text("", strip=False))
        canonical = value.casefold()
        if len(value) < 2 or canonical in seen or _looks_like_interface_text(value):
            continue
        seen.add(canonical)
        values.append(value)
    return values


def _looks_like_interface_text(value: str) -> bool:
    lowered = value.casefold()
    labels = (
        "cookie",
        "datenschutz",
        "newsletter",
        "teilen",
        "anmelden",
        "registrieren",
        "privacy",
        "subscribe",
        "advertisement",
    )
    return len(value) < 180 and any(label in lowered for label in labels)


def _audio_url(soup: BeautifulSoup, source: str, base_url: str) -> str | None:
    candidates: list[str] = []
    for node in soup.select(
        "audio[src], audio source[src], meta[property='og:audio'], "
        "meta[property='og:audio:secure_url']"
    ):
        candidates.append(node.get("src") or node.get("content") or "")
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if _is_audio_path(href):
            candidates.append(href)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            _collect_audio_values(json.loads(script.string or ""), candidates)
        except (json.JSONDecodeError, TypeError):
            pass
    for key in ("mp3Src", "contentUrl", "encodingUrl"):
        for match in re.finditer(
            rf'"{key}"\s*:\s*"((?:\\.|[^"\\])*)"', source
        ):
            try:
                candidates.append(json.loads(f'"{match.group(1)}"'))
            except json.JSONDecodeError:
                pass

    for candidate in candidates:
        resolved = urljoin(base_url, html_module.unescape(candidate.strip()))
        parsed = urlsplit(resolved)
        if parsed.scheme in {"http", "https"} and _is_audio_path(resolved):
            return resolved
    return None


def _video_url(soup: BeautifulSoup, source: str, base_url: str) -> str | None:
    candidates = [
        node.get("src", "")
        for node in soup.select("video[src], video source[src]")
    ]
    for key in ("hlsVideoSrc", "videoUrl"):
        for match in re.finditer(rf'"{key}"\s*:\s*"((?:\\.|[^"\\])*)"', source):
            try:
                candidates.append(json.loads(f'"{match.group(1)}"'))
            except json.JSONDecodeError:
                pass
    for candidate in candidates:
        resolved = urljoin(base_url, html_module.unescape(candidate.strip()))
        parsed = urlsplit(resolved)
        if parsed.scheme in {"http", "https"} and parsed.path.casefold().endswith(
            VIDEO_EXTENSIONS
        ):
            return resolved
    return None


def _transcript_pdf_url(soup: BeautifulSoup, base_url: str) -> str | None:
    """Choose a linked transcript PDF without mistaking exercises for one."""

    candidates: list[tuple[int, str]] = []
    positive = ("transcript", "transkript", "manuscript", "manuskript", "hörtext")
    negative = (
        "arbeitsblatt",
        "worksheet",
        "lösung",
        "loesung",
        "answer",
        "quiz",
        "übung",
        "uebung",
        "vokabel",
        "grammar",
        "grammatik",
    )
    host = (urlsplit(base_url).hostname or "").casefold()
    for link in soup.select("a[href]"):
        href = html_module.unescape(link.get("href", "").strip())
        resolved = urljoin(base_url, href)
        parsed = urlsplit(resolved)
        if parsed.scheme not in {"http", "https"} or not parsed.path.casefold().endswith(".pdf"):
            continue
        label = " ".join(
            (
                link.get_text(" ", strip=True),
                link.get("title", ""),
                link.get("aria-label", ""),
                parsed.path.rsplit("/", 1)[-1],
            )
        ).casefold()
        score = sum(4 for marker in positive if marker in label)
        score -= sum(8 for marker in negative if marker in label)
        # Deutsch-to-go consistently labels the listening text "Text (PDF)"
        # and names it HV_Text_..., while its other PDFs are exercises.
        if host.endswith("deutsch-to-go.de") and (
            "text (pdf)" in label or "hv_text_" in label
        ):
            score += 10
        candidates.append((score, resolved))
    if not candidates:
        return None
    score, url = max(candidates, key=lambda candidate: candidate[0])
    return url if score > 0 else None


def _transcript_from_pdf_url(
    client: httpx.Client, url: str, *, referer: str
) -> list[str]:
    try:
        url = validate_public_url(url)
        for _ in range(MAX_REDIRECTS + 1):
            response = client.get(
                url,
                headers={"Accept": "application/pdf", "Referer": referer},
            )
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return []
                url = validate_public_url(urljoin(url, location))
                continue
            if response.is_error or len(response.content) > MAX_PDF_BYTES:
                return []
            content_type = response.headers.get("content-type", "").casefold()
            if "pdf" not in content_type and not response.content.startswith(b"%PDF"):
                return []
            return _pdf_paragraphs(response.content)
    except (httpx.HTTPError, WebImportError):
        return []
    return []


def _pdf_paragraphs(source: bytes) -> list[str]:
    values: list[str] = []
    try:
        reader = PdfReader(BytesIO(source), strict=False)
        for page in reader.pages:
            text = (page.extract_text() or "").replace("\r", "\n")
            # Rejoin words hyphenated only because they crossed a PDF line.
            text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
            blocks = re.split(r"\n\s*\n+", text)
            for block in blocks:
                value = _clean_text(re.sub(r"\s*\n\s*", " ", block))
                if value:
                    values.append(value)
    except (PdfReadError, OSError, ValueError):
        return []
    return values


def _collect_audio_values(value: object, candidates: list[str]) -> None:
    if isinstance(value, dict):
        is_audio = str(value.get("@type", "")).casefold() == "audioobject"
        for key, child in value.items():
            if isinstance(child, str) and (
                key in {"mp3Src", "encodingUrl"}
                or (key == "contentUrl" and (is_audio or _is_audio_path(child)))
            ):
                candidates.append(child)
            else:
                _collect_audio_values(child, candidates)
    elif isinstance(value, list):
        for child in value:
            _collect_audio_values(child, candidates)


def _is_audio_path(value: str) -> bool:
    return urlsplit(value).path.casefold().endswith(AUDIO_EXTENSIONS)


def _is_faz_children_page(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        (parsed.hostname or "").casefold().endswith("faz.net")
        and "/wie-erklaere-ich-s-meinem-kind/" in parsed.path
    )


def _faz_audio_from_public_feed(client: httpx.Client, title: str) -> str | None:
    try:
        response = client.get(validate_public_url(FAZ_CHILDREN_FEED))
        if response.is_redirect or response.is_error or len(response.content) > MAX_HTML_BYTES:
            return None
        return _audio_from_rss(response.content, title)
    except (httpx.HTTPError, WebImportError):
        # The article and transcript remain useful if the optional feed lookup
        # happens to be unavailable.
        return None


def _audio_from_rss(source: bytes, page_title: str) -> str | None:
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError:
        return None
    wanted = _canonical_episode_title(page_title)
    for item in root.iter("item"):
        title_node = item.find("title")
        candidate = _canonical_episode_title(title_node.text or "") if title_node is not None else ""
        if not wanted or not candidate or wanted not in candidate and candidate not in wanted:
            continue
        enclosure = item.find("enclosure")
        value = enclosure.get("url", "") if enclosure is not None else ""
        if urlsplit(value).scheme in {"http", "https"} and _is_audio_path(value):
            return value
    return None


def _canonical_episode_title(value: str) -> str:
    value = re.sub(r"^\s*#\d+\s*:\s*", "", value)
    value = re.sub(r"^\s*Kindern erklärt\s*:\s*", "", value, flags=re.IGNORECASE)
    return _clean_text(value).casefold()


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_module.unescape(value)).strip()
