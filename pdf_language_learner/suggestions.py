"""Discover the next listening suggestions for the reader landing page."""

from __future__ import annotations

import html as html_module
import json
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup


USER_AGENT = "Margin language reader/0.1 (+local educational use)"
MAX_CATALOGUE_BYTES = 5_000_000


@dataclass(frozen=True)
class Series:
    key: str
    name: str
    language: str
    cefr: str
    landing_url: str


@dataclass(frozen=True)
class SuggestedEpisode:
    key: str
    series: str
    language: str
    cefr: str
    title: str
    url: str
    season: int | None = None
    episode: int | None = None
    is_bonus: bool = False


# Deliberately ordered by CEFR level. This is also the display order.
DW_SERIES = (
    Series(
        key="dw-top-thema",
        name="DW Top-Thema",
        language="German",
        cefr="B1",
        landing_url="https://learngerman.dw.com/de/top-thema/s-55861562",
    ),
    Series(
        key="dw-video-thema",
        name="DW Video-Thema",
        language="German",
        cefr="B2",
        landing_url="https://learngerman.dw.com/de/video-thema/s-55861568",
    ),
    Series(
        key="dw-alltagsdeutsch",
        name="DW Alltagsdeutsch",
        language="German",
        cefr="C1",
        landing_url="https://learngerman.dw.com/de/alltagsdeutsch/s-56744441",
    ),
)


def _spanish(
    season: int,
    episode: int,
    title: str,
    player_id: int,
    *,
    bonus: bool = False,
) -> SuggestedEpisode:
    slug = "undiamonolingue2" if season == 2 else "undiamonolingue"
    kind = "bonus" if bonus else "episode"
    return SuggestedEpisode(
        key=f"un-dia-s{season}e{episode}-{kind}",
        series="Un Día en Español",
        language="Spanish",
        cefr="A1",
        title=title,
        url=f"https://player.timelinenotation.com/{slug}/{player_id}",
        season=season,
        episode=episode,
        is_bonus=bonus,
    )


# The podcast is complete, so keeping its resolved destinations in source control
# avoids a runtime dependency on Bitly. Entries are in listening order.
UN_DIA_EPISODES = (
    _spanish(1, 1, "S1E1 - Surf en Puerto Escondido", 19863),
    _spanish(1, 2, "S1E2 - Mis mascotas los armadillos", 19902),
    _spanish(1, 3, "S1E3 - Clases de español en Pensilvania", 19891),
    _spanish(1, 4, "S1E4 - La primera vez que conocí a mi hermana", 19897),
    _spanish(1, 5, "S1E5 - Propuesta de matrimonio en la Torre CN", 19914),
    _spanish(1, 6, "S1E6 - Falsa boda en Montevideo", 19923),
    _spanish(1, 7, "S1E7 - Coger el subte en Buenos Aires", 19930),
    _spanish(1, 8, "S1E8 - La (no) despedida de mamá", 19941),
    _spanish(1, 9, "S1E9 - Conocer a la familia… ¡en español!", 20521),
    _spanish(1, 10, "S1E10 - El gran negocio de las empanadas", 22452),
    _spanish(1, 11, "S1E11 - El viaje a la Isla de los monos", 22460),
    _spanish(1, 12, "S1E12 - Bailando salsa en Brooklyn", 22521),
    _spanish(1, 13, "S1E13 - El trabajo de mis sueños en la tele", 22527),
    _spanish(2, 1, "S2E1 - Atrapados por la lluvia", 22752),
    _spanish(2, 1, "S2E1 - Bonus: Entrevista con Gissell", 22756, bonus=True),
    _spanish(2, 2, "S2E2 - El día que se cayó el Sabino", 22760),
    _spanish(2, 2, "S2E2 - Bonus: Entrevista con Ignacio", 22761, bonus=True),
    _spanish(2, 3, "S2E3 - Una pijamada paranormal", 22918),
    _spanish(2, 3, "S2E3 - Bonus: Entrevista con Sofía", 22919, bonus=True),
    _spanish(2, 4, "S2E4 - Un tour para los sentidos", 22950),
    _spanish(2, 4, "S2E4 - Bonus: Entrevista con Francisco", 22951, bonus=True),
    _spanish(2, 5, "S2E5 - El amor en los tiempos del corona", 22959),
    _spanish(2, 5, "S2E5 - Bonus: Entrevista con Minette", 22960, bonus=True),
    _spanish(2, 6, "S2E6 - Mi amiga Chelo", 22978),
    _spanish(2, 6, "S2E6 - Bonus: Entrevista con Laura", 22979, bonus=True),
    _spanish(2, 7, "S2E7 - La leyenda de Juan Noj", 22980),
    _spanish(2, 7, "S2E7 - Bonus: Entrevista con Lionel", 22981, bonus=True),
    _spanish(2, 8, "S2E8 - Un espartano de verdad", 23002),
    _spanish(2, 8, "S2E8 - Bonus: Entrevista con Ángel", 23003, bonus=True),
    _spanish(2, 9, "S2E9 - La muerte no era una playa", 23009),
    _spanish(2, 9, "S2E9 - Bonus: Entrevista con Silvia", 23010, bonus=True),
    _spanish(2, 10, "S2E10 - Nueva vida al otro lado del Atlántico", 23011),
    _spanish(2, 10, "S2E10 - Bonus: Entrevista con Michelle", 23012, bonus=True),
)


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    path = quote(
        unquote(parsed.path or "/"),
        safe="/:@-._~!$&'()*+,;=",
    )
    return urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, "")
    )


def suggestion_identity(value: str) -> str:
    """Match DW redirect/canonical variants by their stable lesson identifier."""

    normalized = canonical_url(value)
    parsed = urlsplit(normalized)
    if (parsed.hostname or "").casefold().endswith("learngerman.dw.com"):
        content_id = re.search(r"/l-(\d+)(?:/|$)", parsed.path)
        if content_id:
            return f"https://learngerman.dw.com/de/l-{content_id.group(1)}"
    return normalized


def fetch_catalogue_page(url: str) -> str:
    response = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        timeout=20,
        follow_redirects=True,
    )
    response.raise_for_status()
    if len(response.content) > MAX_CATALOGUE_BYTES:
        raise ValueError("Suggestion catalogue page is too large")
    return response.text


def dw_landing_episodes(source: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(source, "html.parser")
    values: list[tuple[str, str]] = []
    seen: set[str] = set()
    for link in soup.select('a[data-tracking-name="format-block-teaser"][href]'):
        url = urljoin(base_url, link.get("href", ""))
        if not re.search(r"/l-\d+(?:/|$)", urlsplit(url).path):
            continue
        url = canonical_url(url)
        if url in seen:
            continue
        title = link.get("title", "").strip()
        if not title:
            heading = link.find(["h2", "h3"])
            title = heading.get_text(" ", strip=True) if heading else ""
        if not title:
            continue
        seen.add(url)
        values.append((html_module.unescape(title), url))
    return values


def dw_archive_urls(source: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(source, "html.parser")
    archives: list[tuple[int, str]] = []
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        title = f"{link.get('title', '')} {link.get_text(' ', strip=True)} {href}"
        match = re.search(r"archiv[^0-9]*(20\d{2})|(?:20\d{2})[^0-9]*archiv", title, re.I)
        if not match:
            continue
        year_match = re.search(r"20\d{2}", title)
        if year_match:
            archives.append((int(year_match.group()), canonical_url(urljoin(base_url, href))))
    return [url for _, url in sorted(set(archives), reverse=True)]


def dw_archive_episodes(source: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r'"ExternalLink:\d+"\s*:\s*\{"__typename":"ExternalLink".*?'
        r'"name":"((?:\\.|[^"\\])*)".*?'
        r'"url":"(https://learngerman\.dw\.com/de/(?:[^"\\]*/)?l-\d+)"',
        re.DOTALL,
    )
    values: list[tuple[str, str]] = []
    seen: set[str] = set()
    for encoded_title, url in pattern.findall(source):
        try:
            title = json.loads(f'"{encoded_title}"')
        except json.JSONDecodeError:
            continue
        url = canonical_url(url)
        if url in seen:
            continue
        seen.add(url)
        values.append((html_module.unescape(title).strip(), url))
    # DW archive state is oldest-first; suggestions need newest-first.
    return list(reversed(values))


def next_dw_episode(
    series: Series,
    listened_urls: set[str],
    fetch_page: Callable[[str], str] = fetch_catalogue_page,
) -> SuggestedEpisode | None:
    listened_identities = {suggestion_identity(url) for url in listened_urls}
    landing = fetch_page(series.landing_url)
    candidates = dw_landing_episodes(landing, series.landing_url)
    archives = dw_archive_urls(landing, series.landing_url)
    seen: set[str] = set()

    def unlistened(entries: list[tuple[str, str]]) -> SuggestedEpisode | None:
        for title, url in entries:
            normalized = suggestion_identity(url)
            if normalized in seen:
                continue
            seen.add(normalized)
            if normalized not in listened_identities:
                return SuggestedEpisode(
                    key=series.key,
                    series=series.name,
                    language=series.language,
                    cefr=series.cefr,
                    title=title,
                    url=url,
                )
        return None

    suggestion = unlistened(candidates)
    if suggestion is not None:
        return suggestion
    for archive_url in archives:
        suggestion = unlistened(dw_archive_episodes(fetch_page(archive_url)))
        if suggestion is not None:
            return suggestion
    return None


def next_un_dia_episode(listened_urls: set[str]) -> SuggestedEpisode | None:
    listened_identities = {suggestion_identity(url) for url in listened_urls}
    for episode in UN_DIA_EPISODES:
        # The existing listening baseline supplied for this app begins at S1E13.
        if episode.season == 1 and (episode.episode or 0) <= 12:
            continue
        if suggestion_identity(episode.url) not in listened_identities:
            return episode
    return None


def suggestions_for(
    listened_urls: set[str],
    fetch_page: Callable[[str], str] = fetch_catalogue_page,
) -> list[SuggestedEpisode]:
    listened = {suggestion_identity(url) for url in listened_urls}
    suggestions: list[SuggestedEpisode] = []
    for series in DW_SERIES:
        try:
            suggestion = next_dw_episode(series, listened, fetch_page)
        except (httpx.HTTPError, ValueError):
            # One temporarily unavailable publisher feed should not suppress the
            # other language or series suggestions.
            continue
        if suggestion is not None:
            suggestions.append(suggestion)
    spanish = next_un_dia_episode(listened)
    if spanish is not None:
        suggestions.append(spanish)
    return suggestions
