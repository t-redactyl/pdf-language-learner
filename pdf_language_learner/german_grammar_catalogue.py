"""Static catalogue of grammar topics used to drive topic selection and
spaced-repetition scheduling for the grammar revision feature.

This module intentionally stores only *structured metadata* — a stable key,
source book, CEFR level, category, title, and one illustrative example
phrase — and never a full rule explanation. Explanations and exercises are
generated on demand by an LLM call that is seeded with this metadata, the
same way vocabulary translations and connector glosses are generated
elsewhere in the app rather than stored verbatim. This keeps the catalogue
small, avoids duplicating content the model already produces well, and lets
explanations be tailored (e.g. to a learner's known error patterns) instead
of being a fixed string.

Keys are stable slugs and must not be renamed once scheduling data
(`grammar_reviews` rows) references them.
"""

from __future__ import annotations

from enum import StrEnum

from pdf_language_learner.grammar_topics import (
    GrammarLanguage,
    GrammarLevel,
    GrammarTopic,
    ordered_grammar_topics,
)


class GrammarBook(StrEnum):
    A1_B1 = "a1_b1"
    B2_C1 = "b2_c1"


def german_grammar_topic(**values) -> GrammarTopic:
    return GrammarTopic(language=GrammarLanguage.GERMAN, **values)


# ---------------------------------------------------------------------------
# A1-B1 review topics (Grammatik Aktiv A1-B1), selected by the learner as
# personal revision targets rather than a full table of contents.
# ---------------------------------------------------------------------------

_A1_B1_TOPICS: tuple[GrammarTopic, ...] = (
    german_grammar_topic(
        key="a1b1_nebensaetze_weil_wenn_dass",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Nebensätze",
        title="Nebensätze mit weil, wenn, dass",
        example="…weil ich Deutsch lernen möchte",
    ),
    german_grammar_topic(
        key="a1b1_hauptsaetze_verbinden_position_1",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Wortpositionen im Satz",
        title="Hauptsätze verbinden, Position 1: deshalb, sonst, dann, danach",
        example="Deshalb, sonst, dann, danach",
    ),
    german_grammar_topic(
        key="a1b1_nominativ_akkusativ_dativ_adjektivdeklination",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Nomen, Artikel und Adjektive",
        title="Nominativ, Akkusativ und Dativ; Adjektivdeklination",
        example="Ein netter Mann / Am ersten Mai",
    ),
    german_grammar_topic(
        key="a1b1_relativsaetze_1",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Nebensätze",
        title="Relativsätze 1",
        example="Das ist der Mann, der…",
    ),
    german_grammar_topic(
        key="a1b1_akkusativ_dativ_verben",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Nomen, Artikel und Adjektive",
        title="Akkusativ, Dativ, Verben mit Akkusativ und Dativ",
        example="Ich sehe ihn. / Ich helfe ihm.",
    ),
    german_grammar_topic(
        key="a1b1_praeteritum_perfekt",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Bildung der Zeiten",
        title="Präteritum und Perfekt: ich war, ich hatte / Was hast du gestern gemacht?",
        example="Ich war, ich hatte / Was hast du gestern gemacht?",
    ),
    german_grammar_topic(
        key="a1b1_temporale_nebensaetze",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Nebensätze",
        title="Temporale Nebensätze: wenn / als",
        example="Ich gehe, wenn… / Ich ging, als…",
    ),
    german_grammar_topic(
        key="a1b1_finalsaetze",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Nebensätze",
        title="Finalsätze: um…zu und damit",
        example="Um…zu und damit",
    ),
    german_grammar_topic(
        key="a1b1_nomen_plural",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Nomen, Artikel und Adjektive",
        title="Nomen: Plural",
        example="Die Männer, die Frauen, die Babys",
    ),
    german_grammar_topic(
        key="a1b1_hauptsaetze_verbinden_position_0",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Wortpositionen im Satz",
        title="Hauptsätze verbinden, Position 0: und, aber, oder, denn",
        example="Und, aber, oder, denn",
    ),
    german_grammar_topic(
        key="a1b1_doppelkonnektoren",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Besondere Wörter und Wortverbindungen",
        title="Doppelkonnektoren: entweder…oder, weder…noch",
        example="Entweder…oder, weder…noch",
    ),
    german_grammar_topic(
        key="a1b1_praepositionaladverbien_pronomen",
        book=GrammarBook.A1_B1,
        level=GrammarLevel.A1_B1,
        category="Besondere Wörter und Wortverbindungen",
        title="Präpositionaladverbien und -pronomen",
        example="Daneben, danach, dafür…",
    ),
)


# ---------------------------------------------------------------------------
# Grammatik Aktiv B2/C1 — full table of contents, spanning the book's own
# B1, B2, B2/C1, and C1 sections. Category strings match the book's own
# grouping headers so topics can be browsed or interleaved by category.
# ---------------------------------------------------------------------------

_B2_C1_TOPICS: tuple[GrammarTopic, ...] = (
    # --- B1 (bridge/review chapter in this book) ---
    german_grammar_topic(
        key="b2c1_wortpositionen_informationen_direkt_zum_verb",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B1,
        category="Wortpositionen im Satz",
        title="Informationen direkt zum Verb",
        example="Er hat gestern drei Stunden lang Tennis gespielt",
    ),
    # --- B2: Wortpositionen im Satz ---
    german_grammar_topic(
        key="b2c1_verbposition_satzverbindungen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Wortpositionen im Satz",
        title="Verbposition in Satzverbindungen",
        example="Ich gehe ins Schwimmbad, obwohl ich arbeiten müsste",
    ),
    german_grammar_topic(
        key="b2c1_position_dativ_akkusativobjekt",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Wortpositionen im Satz",
        title="Position von Dativ- und Akkusativobjekt",
        example="Der Kellner holt der Dame den Kaffee und bringt ihn ihr",
    ),
    german_grammar_topic(
        key="b2c1_position_der_angaben",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Wortpositionen im Satz",
        title="Position der Angaben im Satz",
        example="wann – warum – wie – wo",
    ),
    german_grammar_topic(
        key="b2c1_position_von_nicht",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Wortpositionen im Satz",
        title="Position von nicht",
        example="Das habe ich nicht gesagt",
    ),
    # --- B2: Konjunktiv 2 ---
    german_grammar_topic(
        key="b2c1_konjunktiv2_gegenwart_formen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Konjunktiv 2",
        title="Konjunktiv 2 der Gegenwart: Formen",
        example="Wenn ich einen Zauberstab hätte, würde ich …",
    ),
    german_grammar_topic(
        key="b2c1_hoeflichkeit_vorschlaege_ratschlaege_vorwuerfe",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Konjunktiv 2",
        title="Höflichkeit, Vorschläge, Ratschläge und Vorwürfe",
        example="Würden Sie bitte das Fenster schließen?",
    ),
    # --- B2: Passiv ---
    german_grammar_topic(
        key="b2c1_alternativen_zum_passiv",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Passiv",
        title="Alternativen zum Passiv",
        example="Das Problem lässt sich lösen",
    ),
    # --- B2: Präpositionen ---
    german_grammar_topic(
        key="b2c1_wechselpraepositionen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Präpositionen",
        title="Wechselpräpositionen",
        example="Joggen Sie in den Park oder joggen Sie im Park?",
    ),
    german_grammar_topic(
        key="b2c1_oft_gebrauchte_lokale_praepositionen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Präpositionen",
        title="Oft gebrauchte lokale Präpositionen",
        example="wo – wohin – woher",
    ),
    german_grammar_topic(
        key="b2c1_weitere_lokale_praepositionen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Präpositionen",
        title="Weitere lokale Präpositionen",
        example="Innerhalb und außerhalb des Dorfes",
    ),
    german_grammar_topic(
        key="b2c1_wichtigste_temporale_praepositionen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Präpositionen",
        title="Die wichtigsten temporalen Präpositionen",
        example="Am Montag um 18 Uhr auf dem Heimweg",
    ),
    german_grammar_topic(
        key="b2c1_weitere_temporale_praepositionen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Präpositionen",
        title="Weitere temporale Präpositionen",
        example="Ab Montag und über die Feiertage",
    ),
    german_grammar_topic(
        key="b2c1_kausale_praepositionen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Präpositionen",
        title="Kausale Präpositionen",
        example="Vor Wut oder aufgrund eines Fehlers",
    ),
    # --- B2: Verben, Adjektive, Nomen und ihre Ergänzungen ---
    german_grammar_topic(
        key="b2c1_verben_nomen_adjektive_mit_praepositionen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Verben, Adjektive, Nomen und ihre Ergänzungen",
        title="Verben, Nomen und Adjektive mit Präpositionen",
        example="Es kommt darauf an, wann ihr kommt",
    ),
    german_grammar_topic(
        key="b2c1_feste_praepositionen_akkusativ",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Verben, Adjektive, Nomen und ihre Ergänzungen",
        title="Verben, Adjektive und Nomen mit festen Präpositionen mit Akkusativ",
        example="Danke für das Kompliment",
    ),
    german_grammar_topic(
        key="b2c1_feste_praepositionen_dativ",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Verben, Adjektive, Nomen und ihre Ergänzungen",
        title="Verben, Adjektive und Nomen mit festen Präpositionen mit Dativ",
        example="Ich träume von dir",
    ),
    # --- B2: Bildung der Zeiten ---
    german_grammar_topic(
        key="b2c1_bildung_der_vergangenheitszeiten",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Bildung der Zeiten",
        title="Bildung der Vergangenheitszeiten",
        example="Das Glas ist zerbrochen, aber wer hat es zerbrochen?",
    ),
    german_grammar_topic(
        key="b2c1_gebrauch_von_zeiten_der_vergangenheit",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Bildung der Zeiten",
        title="Gebrauch von Zeiten der Vergangenheit",
        example="Oh, das wusste ich nicht!",
    ),
    # --- B2: Modalverben, lassen und (un)trennbare Verben ---
    german_grammar_topic(
        key="b2c1_modalverben_grundbedeutung",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Modalverben, lassen und (un)trennbare Verben",
        title="Modalverben in der Grundbedeutung",
        example="Ich will, ich kann, ich muss",
    ),
    german_grammar_topic(
        key="b2c1_modalverben_vermutungen_gegenwart",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Modalverben, lassen und (un)trennbare Verben",
        title="Andere Bedeutung von Modalverben: Vermutungen über die Gegenwart",
        example="Er muss gleich da sein",
    ),
    german_grammar_topic(
        key="b2c1_das_verb_lassen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Modalverben, lassen und (un)trennbare Verben",
        title="Das Verb lassen",
        example="Leben und leben lassen",
    ),
    # --- B2: Nomen, Artikel und Pronomen ---
    german_grammar_topic(
        key="b2c1_genusregeln",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Nomen, Artikel und Pronomen",
        title="Genusregeln",
        example="Der, die oder das?",
    ),
    german_grammar_topic(
        key="b2c1_artikelgebrauch",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Nomen, Artikel und Pronomen",
        title="Artikelgebrauch",
        example="Handwerker, der Handwerker oder ein Handwerker?",
    ),
    german_grammar_topic(
        key="b2c1_n_deklination",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Nomen, Artikel und Pronomen",
        title="n-Deklination",
        example="An Herrn und Frau Schneider",
    ),
    german_grammar_topic(
        key="b2c1_drei_deklinationen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Nomen, Artikel und Pronomen",
        title="Drei Deklinationen",
        example="des Mannes, des Herrn, des Alten",
    ),
    german_grammar_topic(
        key="b2c1_indefinit_possessivpronomen_deklination",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Nomen, Artikel und Pronomen",
        title="Deklination der Indefinit- und Possessivpronomen",
        example="Bringst du mir welche mit?",
    ),
    german_grammar_topic(
        key="b2c1_indefinitpronomen_menschen_dinge",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Nomen, Artikel und Pronomen",
        title="Indefinitpronomen für Menschen und Dinge",
        example="Beide trinken beides",
    ),
    # --- B2: Adjektive ---
    german_grammar_topic(
        key="b2c1_adjektivdeklination",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Adjektive",
        title="Adjektivdeklination",
        example="Mit dem schnellen Auto steht man oft in einem langen Stau",
    ),
    german_grammar_topic(
        key="b2c1_partizip_1_2_als_adjektiv",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Adjektive",
        title="Partizip I und II als Adjektiv",
        example="Das malende und das gemalte Mädchen",
    ),
    # --- B2: Indirekte Rede ---
    german_grammar_topic(
        key="b2c1_indirekte_rede_konjunktiv_1",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Indirekte Rede",
        title="Indirekte Rede und Konjunktiv I",
        example="Er sagte, er sei fertig und komme gleich",
    ),
    german_grammar_topic(
        key="b2c1_indirekte_rede_vergangenheit",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Indirekte Rede",
        title="Indirekte Rede – Vergangenheit",
        example="Sie sagte, sie habe Glück gehabt und sei pünktlich gewesen",
    ),
    # --- B2: Nebensätze ---
    german_grammar_topic(
        key="b2c1_temporale_nebensaetze",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Nebensätze",
        title="Temporale Nebensätze",
        example="Seitdem die Katze kommt, wenn ich koche …",
    ),
    german_grammar_topic(
        key="b2c1_finale_modale_infinitiv_nebensaetze",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Nebensätze",
        title="Finale und modale Infinitiv- und Nebensätze",
        example="um … zu, damit, anstatt …, ohne …",
    ),
    german_grammar_topic(
        key="b2c1_relativpronomen_nom_akk_dat",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Nebensätze",
        title="Relativpronomen im Nominativ, Akkusativ und Dativ",
        example="…, denen wir die Idee für dieses Fest verdanken",
    ),
    # --- B2: Besondere Wörter und Wortverbindungen ---
    german_grammar_topic(
        key="b2c1_negationswoerter",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Besondere Wörter und Wortverbindungen",
        title="Negationswörter",
        example="nie, nirgends, nicht mehr",
    ),
    german_grammar_topic(
        key="b2c1_irgend",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Besondere Wörter und Wortverbindungen",
        title="Irgend…",
        example="Hat irgendjemand irgendetwas gesehen?",
    ),
    german_grammar_topic(
        key="b2c1_position_und_direktion",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Besondere Wörter und Wortverbindungen",
        title="Position und Direktion",
        example="rauf, runter, stehen, stellen, legen",
    ),
    german_grammar_topic(
        key="b2c1_es",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Besondere Wörter und Wortverbindungen",
        title="Es",
        example="Wann brauche ich es?",
    ),
    german_grammar_topic(
        key="b2c1_funktionsverbgefuege_1",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Besondere Wörter und Wortverbindungen",
        title="Funktionsverbgefüge 1",
        example="Wir müssen jetzt eine Entscheidung treffen",
    ),
    german_grammar_topic(
        key="b2c1_woerter_mit_da",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Besondere Wörter und Wortverbindungen",
        title="Wörter mit da-",
        example="Da ist Assenheim. Da habe ich lange gewohnt. Dabei wollte ich "
        "eigentlich nie in einem Dorf leben.",
    ),
    german_grammar_topic(
        key="b2c1_modalpartikeln",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Besondere Wörter und Wortverbindungen",
        title="Modalpartikeln",
        example="Im Kino waren wir doch gestern",
    ),
    # --- B2: Und noch mehr Wissenswertes ---
    german_grammar_topic(
        key="b2c1_kommaregeln",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2,
        category="Und noch mehr Wissenswertes",
        title="Kommaregeln",
        example="Er isst seine Katze auch???",
    ),
    # --- B2/C1: Wortpositionen im Satz ---
    german_grammar_topic(
        key="b2c1_verbposition_einfache_saetze",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Wortpositionen im Satz",
        title="Verbposition in einfachen Sätzen",
        example="Heute möchte ich ins Schwimmbad gehen",
    ),
    # --- B2/C1: Konjunktiv 2 ---
    german_grammar_topic(
        key="b2c1_konjunktiv2_vergangenheit_formen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Konjunktiv 2",
        title="Konjunktiv 2 der Vergangenheit: Formen",
        example="Wäre ich doch zu Hause geblieben!",
    ),
    german_grammar_topic(
        key="b2c1_wuensche_irreale_bedingungen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Konjunktiv 2",
        title="Wünsche, irreale Wünsche und irreale Bedingungen",
        example="Wenn ich doch Millionär wäre!",
    ),
    german_grammar_topic(
        key="b2c1_irreale_vergleiche_folgen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Konjunktiv 2",
        title="Irreale Vergleiche und irreale Folgen",
        example="Du siehst aus, als ob du müde wärst",
    ),
    # --- B2/C1: Passiv ---
    german_grammar_topic(
        key="b2c1_passiv_in_allen_zeiten",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Passiv",
        title="Passiv in allen Zeiten",
        example="Die Reisegruppe wird informiert",
    ),
    german_grammar_topic(
        key="b2c1_passiv_mit_modalverben",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Passiv",
        title="Passiv mit Modalverben in allen Zeiten",
        example="Das muss heute noch erledigt werden",
    ),
    # --- B2/C1: Präpositionen ---
    german_grammar_topic(
        key="b2c1_praepositionen_verschiedene_positionen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Präpositionen",
        title="Präpositionen mit verschiedenen Positionen",
        example="Davor, dahinter und um das Nomen herum",
    ),
    # --- B2/C1: Verben, Adjektive, Nomen und ihre Ergänzungen ---
    german_grammar_topic(
        key="b2c1_verben_nom_akk_dat",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Verben, Adjektive, Nomen und ihre Ergänzungen",
        title="Verben mit Nominativ, Akkusativ und Dativ",
        example="Ich frage dich und antworte dir",
    ),
    # --- B2/C1: Bildung der Zeiten ---
    german_grammar_topic(
        key="b2c1_besondere_perfektformen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Bildung der Zeiten",
        title="Besondere Perfektformen: Modalverben und sehen, hören, lassen",
        example="Ich habe gehen müssen",
    ),
    german_grammar_topic(
        key="b2c1_vermutung_zukunft_futur",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Bildung der Zeiten",
        title="Vermutung und Zukunft mit dem Futur",
        example="Er wird den Zug verpasst haben",
    ),
    # --- B2/C1: Modalverben, lassen und (un)trennbare Verben ---
    german_grammar_topic(
        key="b2c1_trennbare_untrennbare_verben_1",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Modalverben, lassen und (un)trennbare Verben",
        title="Trennbare und untrennbare Verben 1",
        example="mitkommen, ankommen, bekommen, entkommen",
    ),
    # --- B2/C1: Nomen, Artikel und Pronomen ---
    german_grammar_topic(
        key="b2c1_genitiv",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Nomen, Artikel und Pronomen",
        title="Genitiv",
        example="Deutschlands Süden",
    ),
    german_grammar_topic(
        key="b2c1_indefinitpronomen_menschen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Nomen, Artikel und Pronomen",
        title="Indefinitpronomen für Menschen",
        example="man, alle, jeder, jemand, niemand",
    ),
    # --- B2/C1: Adjektive ---
    german_grammar_topic(
        key="b2c1_komparation",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Adjektive",
        title="Komparation",
        example="Der ältere Mann genießt einen der schönsten Tage des Jahres",
    ),
    # --- B2/C1: Nebensätze ---
    german_grammar_topic(
        key="b2c1_kausale_konzessive_nebensaetze",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Nebensätze",
        title="Kausale und konzessive Nebensätze",
        example="weil, da, obwohl, wobei …",
    ),
    german_grammar_topic(
        key="b2c1_konsekutive_nebensaetze",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Nebensätze",
        title="Konsekutive Nebensätze",
        example="sodass, weshalb, dermaßen …, dass",
    ),
    german_grammar_topic(
        key="b2c1_konditionale_adversative_nebensaetze",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Nebensätze",
        title="Konditionale und adversative Nebensätze",
        example="wenn, falls, während, wohingegen …",
    ),
    german_grammar_topic(
        key="b2c1_modale_nebensaetze_methode",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Nebensätze",
        title="Modale Nebensätze (Methode)",
        example="indem, dadurch dass, wodurch …",
    ),
    german_grammar_topic(
        key="b2c1_infinitiv_mit_ohne_zu",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Nebensätze",
        title="Infinitiv mit und ohne zu",
        example="Wir wollen pünktlich kommen, aber fürchten, zu spät "
        "losgefahren zu sein",
    ),
    german_grammar_topic(
        key="b2c1_nebensatz_dass_infinitiv_zu",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Nebensätze",
        title="Nebensatz mit dass und Infinitiv mit zu",
        example="Ich hoffe, abzunehmen und dass auch mein Mann abnimmt",
    ),
    german_grammar_topic(
        key="b2c1_relativpronomen_genitiv",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Nebensätze",
        title="Relativpronomen im Genitiv",
        example="Die Frau, deren Hund …",
    ),
    german_grammar_topic(
        key="b2c1_relativpronomen_w_als",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Nebensätze",
        title="Relativpronomen mit w- und als",
        example="etwas, was …, nichts, worüber …",
    ),
    # --- B2/C1: Besondere Wörter und Wortverbindungen ---
    german_grammar_topic(
        key="b2c1_doppelkonnektoren",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.B2_C1,
        category="Besondere Wörter und Wortverbindungen",
        title="Doppelkonnektoren",
        example="entweder A oder B",
    ),
    # --- C1: Wortpositionen im Satz ---
    german_grammar_topic(
        key="b2c1_position_auch_fokuspartikeln",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Wortpositionen im Satz",
        title="Position von auch und Fokuspartikeln",
        example="Gehst du morgen auch ins Kino?",
    ),
    german_grammar_topic(
        key="b2c1_informationsverteilung_im_satz",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Wortpositionen im Satz",
        title="Informationsverteilung im Satz",
        example="Den Ring zeigt sie einem Freund",
    ),
    # --- C1: Passiv ---
    german_grammar_topic(
        key="b2c1_formen_mit_passivbedeutung",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Passiv",
        title="Formen mit Passivbedeutung",
        example="Die zu verkaufenden Bücher gehören ins Fenster gestellt",
    ),
    german_grammar_topic(
        key="b2c1_passivsaetze_ohne_subjekt",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Passiv",
        title="Passivsätze ohne Subjekt",
        example="Hier wird gelacht!",
    ),
    german_grammar_topic(
        key="b2c1_wann_ist_passiv_moeglich",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Passiv",
        title="Wann ist Passiv möglich, wann nicht?",
        example="Warum ist „Es wird geregnet“ falsch?",
    ),
    # --- C1: Präpositionen ---
    german_grammar_topic(
        key="b2c1_praepositionen_redewiedergabe_referenz",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Präpositionen",
        title="Präpositionen der Redewiedergabe und Referenz",
        example="laut, zufolge, hinsichtlich, entsprechend",
    ),
    german_grammar_topic(
        key="b2c1_sprechende_praepositionen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Präpositionen",
        title="„Sprechende“ Präpositionen",
        example="zuliebe, mittels, anhand …",
    ),
    german_grammar_topic(
        key="b2c1_bedeutungen_in_an_auf_ueber_unter_vor",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Präpositionen",
        title="Bedeutungen von in, an, auf, über, unter, vor",
        example="am Sonntag, am Strand, an die 100 Leute",
    ),
    german_grammar_topic(
        key="b2c1_bedeutungen_um_bei_von_nach_aus_mit_zu",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Präpositionen",
        title="Bedeutungen von um, bei, von, nach, aus, mit, zu",
        example="um das Haus, um 8 Uhr, um die Wette",
    ),
    # --- C1: Verben, Adjektive, Nomen und ihre Ergänzungen ---
    german_grammar_topic(
        key="b2c1_verben_mit_genitiv",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Verben, Adjektive, Nomen und ihre Ergänzungen",
        title="Verben mit Genitiv",
        example="Man verdächtigte ihn des Mordes",
    ),
    # --- C1: Bildung der Zeiten ---
    german_grammar_topic(
        key="b2c1_ueberblick_zeiten",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Bildung der Zeiten",
        title="Überblick über die Zeiten im Deutschen",
        example="Plusquamperfekt bis Futur 2",
    ),
    # --- C1: Modalverben, lassen und (un)trennbare Verben ---
    german_grammar_topic(
        key="b2c1_modalverben_vermutungen_vergangenheit",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Modalverben, lassen und (un)trennbare Verben",
        title="Andere Bedeutung von Modalverben: Vermutungen über die "
        "Vergangenheit",
        example="Sie muss wohl zu Fuß gegangen sein",
    ),
    german_grammar_topic(
        key="b2c1_trennbare_untrennbare_verben_2",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Modalverben, lassen und (un)trennbare Verben",
        title="Trennbare und untrennbare Verben 2",
        example="Er umfährt den Baum, aber er fährt die Mülltonne um",
    ),
    # --- C1: Adjektive ---
    german_grammar_topic(
        key="b2c1_artikelwoerter_adjektivdeklination",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Adjektive",
        title="Artikelwörter und Adjektivdeklination",
        example="Alle kleinen Kinder und viele große Kinder mögen Schokolade",
    ),
    # --- C1: Indirekte Rede ---
    german_grammar_topic(
        key="b2c1_wiedergabe_aufforderungen_geruechte_selbstaussagen",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Indirekte Rede",
        title="Wiedergabe von Aufforderungen, Gerüchten und Selbstaussagen",
        example="Er will das nie gesagt haben",
    ),
    # --- C1: Besondere Wörter und Wortverbindungen ---
    german_grammar_topic(
        key="b2c1_funktionsverbgefuege_2",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Besondere Wörter und Wortverbindungen",
        title="Funktionsverbgefüge 2",
        example="In Aufregung versetzen oder in Aufregung geraten?",
    ),
    # --- C1: Umformung von Sätzen ---
    german_grammar_topic(
        key="b2c1_nominalisierung",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Umformung von Sätzen",
        title="Nominalisierung",
        example="Durch Verwendung von Nomen entsteht Verdichtung",
    ),
    german_grammar_topic(
        key="b2c1_links_rechtsattribute",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Umformung von Sätzen",
        title="Links- und Rechtsattribute",
        example="Komplexe Sätze verstehen und umformen",
    ),
    german_grammar_topic(
        key="b2c1_praeposition_adverb_konnektor_1",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Umformung von Sätzen",
        title="Präposition – Adverb – Konnektor 1 (temporal)",
        example="temporal: vor, vorher, bevor, nach …",
    ),
    german_grammar_topic(
        key="b2c1_praeposition_adverb_konnektor_2",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Umformung von Sätzen",
        title="Präposition – Adverb – Konnektor 2 (kausal etc.)",
        example="kausal, konsekutiv, konzessiv, adversativ",
    ),
    german_grammar_topic(
        key="b2c1_praeposition_adverb_konnektor_3",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Umformung von Sätzen",
        title="Präposition – Adverb – Konnektor 3 (modal etc.)",
        example="modal, konditional, final",
    ),
    # --- C1: Und noch mehr Wissenswertes ---
    german_grammar_topic(
        key="b2c1_besondere_formen_muendliche_sprache",
        book=GrammarBook.B2_C1,
        level=GrammarLevel.C1,
        category="Und noch mehr Wissenswertes",
        title="Besondere Formen der mündlichen Sprache",
        example="Da kommste nich drauf",
    ),
)


GRAMMAR_TOPICS: tuple[GrammarTopic, ...] = ordered_grammar_topics(
    GrammarLanguage.GERMAN,
    _A1_B1_TOPICS + _B2_C1_TOPICS,
)
A1_B1_TOPICS: tuple[GrammarTopic, ...] = tuple(
    topic for topic in GRAMMAR_TOPICS if topic.book is GrammarBook.A1_B1
)
B2_C1_TOPICS: tuple[GrammarTopic, ...] = tuple(
    topic for topic in GRAMMAR_TOPICS if topic.book is GrammarBook.B2_C1
)


def grammar_topic_by_key(key: str) -> GrammarTopic | None:
    for topic in GRAMMAR_TOPICS:
        if topic.key == key:
            return topic
    return None


def grammar_topics_by_category(
    book: GrammarBook | None = None,
) -> dict[str, tuple[GrammarTopic, ...]]:
    """Group topics by their book category, preserving catalogue order.

    Passing a `book` restricts the result to that book; omitting it merges
    both books' topics into one category-keyed view, which is useful for a
    "browse all topics" screen.
    """

    ordered: dict[str, list[GrammarTopic]] = {}
    for topic in GRAMMAR_TOPICS:
        if book is not None and topic.book is not book:
            continue
        ordered.setdefault(topic.category, []).append(topic)
    return {category: tuple(topics) for category, topics in ordered.items()}
