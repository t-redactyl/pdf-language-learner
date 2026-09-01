import sqlite3

from fastapi.testclient import TestClient

from pdf_language_learner.app import app
from pdf_language_learner.suggestions import (
    DW_SERIES,
    SuggestedEpisode,
    UN_DIA_EPISODES,
    dw_archive_episodes,
    dw_archive_urls,
    dw_landing_episodes,
    next_dw_episode,
    next_un_dia_episode,
    suggestion_identity,
)


client = TestClient(app)


def test_german_series_are_ordered_by_cefr_level() -> None:
    assert [(series.name, series.cefr) for series in DW_SERIES] == [
        ("DW Top-Thema", "B1"),
        ("DW Video-Thema", "B2"),
        ("DW Alltagsdeutsch", "C1"),
    ]


def test_dw_identity_matches_redirect_and_unicode_url_variants() -> None:
    assert suggestion_identity(
        "https://learngerman.dw.com/de/stadtbäume-im-trockenstress/l-78532414"
    ) == suggestion_identity(
        "https://learngerman.dw.com/de/stadtb%C3%A4ume-im-trockenstress/l-78532414"
    ) == suggestion_identity("https://learngerman.dw.com/de/l-78532414")


def test_un_dia_catalogue_has_every_non_trailer_player_and_starts_at_s1e13() -> None:
    assert len(UN_DIA_EPISODES) == 33
    assert all(episode.cefr == "A1" for episode in UN_DIA_EPISODES)
    assert next_un_dia_episode(set()).title.startswith("S1E13 -")

    s1e13 = next_un_dia_episode(set())
    following = next_un_dia_episode({s1e13.url})

    assert s1e13.url.endswith("/undiamonolingue/22527")
    assert following.title == "S2E1 - Atrapados por la lluvia"
    assert following.url.endswith("/undiamonolingue2/22752")


def test_dw_landing_parser_keeps_publisher_order_and_finds_archives() -> None:
    source = """
      <a data-tracking-name="format-block-teaser" title="Newest"
         href="/de/newest/l-300"></a>
      <a data-tracking-name="format-block-teaser" title="Older"
         href="/de/older/l-200"></a>
      <a title="Top-Thema – Archiv 2025" href="/de/archive/a-10">Archive</a>
      <a title="Top-Thema – Archiv 2026" href="/de/archive/a-11">Archive</a>
    """

    assert dw_landing_episodes(source, "https://learngerman.dw.com/de/show") == [
        ("Newest", "https://learngerman.dw.com/de/newest/l-300"),
        ("Older", "https://learngerman.dw.com/de/older/l-200"),
    ]
    assert dw_archive_urls(source, "https://learngerman.dw.com/de/show") == [
        "https://learngerman.dw.com/de/archive/a-11",
        "https://learngerman.dw.com/de/archive/a-10",
    ]


def test_dw_archive_parser_returns_latest_episode_first() -> None:
    source = r'''<script>window.__APOLLO_STATE__ = {
      "ExternalLink:1":{"__typename":"ExternalLink","id":1,
        "name":"Older \u00dcpisode","url":"https://learngerman.dw.com/de/l-100"},
      "ExternalLink:2":{"__typename":"ExternalLink","id":2,
        "name":"Newest episode","url":"https://learngerman.dw.com/de/l-200"}
    };</script>'''

    assert dw_archive_episodes(source) == [
        ("Newest episode", "https://learngerman.dw.com/de/l-200"),
        ("Older Üpisode", "https://learngerman.dw.com/de/l-100"),
    ]


def test_dw_selection_falls_back_to_newest_archive_when_landing_is_exhausted() -> None:
    series = DW_SERIES[0]
    current_url = "https://learngerman.dw.com/de/current/l-300"
    archive_url = "https://learngerman.dw.com/de/archive/a-11"
    landing = f'''
      <a data-tracking-name="format-block-teaser" title="Current" href="{current_url}"></a>
      <a title="Archive 2026" href="{archive_url}">Archiv 2026</a>
    '''
    archive = r'''<script>window.__APOLLO_STATE__ = {
      "ExternalLink:1":{"__typename":"ExternalLink","name":"Archived",
        "url":"https://learngerman.dw.com/de/l-200"}
    };</script>'''

    suggestion = next_dw_episode(
        series,
        {current_url},
        lambda url: landing if url == series.landing_url else archive,
    )

    assert suggestion.title == "Archived"
    assert suggestion.url == "https://learngerman.dw.com/de/l-200"


def test_listening_history_drives_the_suggestions_api(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "margin.db"
    listened_url = "https://player.timelinenotation.com/undiamonolingue/22527"
    captured = []
    monkeypatch.setattr("pdf_language_learner.app.DATABASE_PATH", database_path)
    monkeypatch.setattr(
        "pdf_language_learner.app.suggestions_for",
        lambda listened: captured.append(listened) or [
            SuggestedEpisode(
                key="un-dia-s2e1-episode",
                series="Un Día en Español",
                language="Spanish",
                cefr="A1",
                title="S2E1 - Atrapados por la lluvia",
                url="https://player.timelinenotation.com/undiamonolingue2/22752",
                season=2,
                episode=1,
            )
        ],
    )

    response = client.post(
        "/api/listening-history",
        json={"url": f"{listened_url}#finished", "title": "S1E13"},
    )
    suggestions = client.get("/api/suggestions")

    assert response.status_code == 204
    assert captured == [{listened_url}]
    assert suggestions.json()[0]["cefr"] == "A1"
    assert suggestions.json()[0]["season"] == 2
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT url, title FROM listening_history"
        ).fetchone() == (listened_url, "S1E13")
