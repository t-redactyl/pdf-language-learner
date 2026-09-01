from pdf_language_learner.web_import import extract_web_document


def test_un_dia_monolingue_uses_timeline_transcript_audio_and_spanish() -> None:
    page = """
        <html lang="en"><head>
          <meta property="og:title" content="S1E2 - Mis mascotas los armadillos">
        </head><body>
          <audio><source
            src="https://chtbl.com/track/example/armadillos.mp3"
            type="audio/mpeg">
          </audio>
          <div class="timeline">
            <div class="tag_block">
              <div class="transcript_tag_body">
                <strong>Rodrigo:</strong> Hola, soy Rodrigo y te doy la bienvenida
                a <em>Un día en español</em> – monolingüe.
              </div>
            </div>
            <div class="tag_block">
              <iframe src="https://maps.example/embed"></iframe>
            </div>
            <div class="tag_block">
              <div class="transcript_tag_body">
                ¿Conoces Tabasco? Hoy visitamos a Julio y a su familia, junto
                con dos mascotas muy originales: Chato y Chebo.
              </div>
            </div>
          </div>
        </body></html>
    """

    document = extract_web_document(
        page,
        "https://player.timelinenotation.com/undiamonolingue/19902",
    )

    assert document.title == "S1E2 - Mis mascotas los armadillos"
    assert document.audio_url == "https://chtbl.com/track/example/armadillos.mp3"
    assert document.video_url is None
    assert document.source_language == "Spanish"
    assert document.transcript == [
        (
            "Rodrigo: Hola, soy Rodrigo y te doy la bienvenida a "
            "Un día en español – monolingüe."
        ),
        (
            "¿Conoces Tabasco? Hoy visitamos a Julio y a su familia, junto "
            "con dos mascotas muy originales: Chato y Chebo."
        ),
    ]


def test_aventura_uses_timeline_transcript_and_spanish() -> None:
    page = """
        <html lang="en"><body>
          <div class="timeline">
            <div class="transcript_tag_body">
              <strong>Narradora:</strong> Esta es una aventura en español con un
              transcript completo que los estudiantes pueden leer mientras
              escuchan el episodio.
            </div>
          </div>
        </body></html>
    """

    document = extract_web_document(
        page,
        "https://player.timelinenotation.com/aventura/24489",
    )

    assert document.source_language == "Spanish"
    assert document.transcript == [
        (
            "Narradora: Esta es una aventura en español con un transcript "
            "completo que los estudiantes pueden leer mientras escuchan el episodio."
        )
    ]


def test_dw_video_thema_uses_embedded_lesson_title_and_manuscript() -> None:
    page = r'''
        <html lang="de"><head><script>
        window.__APOLLO_STATE__ = {
          "Lesson:78510779": {
            "__typename": "Lesson",
            "id": 78510779,
            "name": "Wohnen im ehemaligen Gef\u00e4ngnis",
            "hlsVideoSrc": "https://hlsvod.dw.com/video.mp4.csmil/master.m3u8",
            "manuscript": "<p><strong>Wohnen im ehemaligen Gef\u00e4ngnis</strong></p>\n\n<p>Ein Jugendgef\u00e4ngnis wird in 24 <span class=\"editable placeholder\">bezahlbare</span> Studentenapartments <span class=\"editable placeholder\">umgebaut</span>. Das Geb\u00e4ude wird mit <span class=\"editable placeholder\">Stiftungs</span>geldern saniert.</p>\n\n<p>SPRECHERIN:<br />Hier folgt der vollst\u00e4ndige ausw\u00e4hlbare Manuskripttext des Video-Themas.</p>"
          }
        };
        </script></head><body></body></html>
    '''

    document = extract_web_document(
        page,
        "https://learngerman.dw.com/de/wohnen-im-ehemaligen-gef%C3%A4ngnis/l-78510779",
    )

    assert document.title == "Wohnen im ehemaligen Gefängnis"
    assert document.source_language == "German"
    assert document.audio_url is None
    assert document.video_url == "https://hlsvod.dw.com/video.mp4.csmil/master.m3u8"
    assert document.transcript == [
        "Wohnen im ehemaligen Gefängnis",
        (
            "Ein Jugendgefängnis wird in 24 bezahlbare Studentenapartments "
            "umgebaut. Das Gebäude wird mit Stiftungsgeldern saniert."
        ),
        (
            "SPRECHERIN: Hier folgt der vollständige auswählbare "
            "Manuskripttext des Video-Themas."
        ),
    ]


def test_dw_slow_news_uses_matching_article_text_and_slow_audio() -> None:
    page = r'''
        <html lang="de"><head><script>
        window.__APOLLO_STATE__ = {
          "translations": {"text": "Unrelated interface copy that must not be imported."},
          "Audio:78555767": {
            "name": "29.08.2026 – Langsam Gesprochene Nachrichten",
            "mp3Src": "https://media.example/langsamenachrichten/slow.mp3"
          },
          "Audio:78555783": {
            "name": "29.08.2026 – Langsam Gesprochene Nachrichten",
            "mp3Src": "https://media.example/nachrichten_live/original.mp3"
          },
          "Article:78555460": {
            "__typename": "Article",
            "id": 78555460,
            "text": "<h2>Isl\u00e4nder stimmen \u00fcber EU-Kurs ab</h2><p>In einem Referendum entscheiden die B\u00fcrger, ob die Verhandlungen mit der Europ\u00e4ischen Union wieder aufgenommen werden sollen.</p><h2>Weitere Meldung</h2><p>Dies ist ein weiterer ausreichend langer Nachrichtenabsatz f\u00fcr den ausw\u00e4hlbaren Transkripttext.</p>",
            "name": "29.08.2026 – Langsam Gesprochene Nachrichten"
          }
        };
        </script></head><body></body></html>
    '''

    document = extract_web_document(
        page,
        "https://learngerman.dw.com/de/29082026-langsam-gesprochene-nachrichten/a-78555460",
    )

    assert document.title == "29.08.2026 – Langsam Gesprochene Nachrichten"
    assert document.audio_url == "https://media.example/langsamenachrichten/slow.mp3"
    assert document.video_url is None
    assert document.transcript == [
        "Isländer stimmen über EU-Kurs ab",
        (
            "In einem Referendum entscheiden die Bürger, ob die Verhandlungen "
            "mit der Europäischen Union wieder aufgenommen werden sollen."
        ),
        "Weitere Meldung",
        (
            "Dies ist ein weiterer ausreichend langer Nachrichtenabsatz für den "
            "auswählbaren Transkripttext."
        ),
    ]
