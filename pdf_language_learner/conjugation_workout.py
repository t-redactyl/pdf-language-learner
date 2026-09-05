"""Deterministic verb-form inventory and scheduling for conjugation workouts.

The grammar catalogues describe topics, not individual recall targets.  This
module expands the topics that explicitly teach verb morphology into small,
stable items that can be scheduled independently.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable

from pdf_language_learner.grammar_topics import GrammarLanguage, GrammarTopic
from pdf_language_learner.revision import ScheduleState


WORKOUT_LIMIT = 20
CONJUGATION_INTERVAL_DAYS = (1, 3, 7, 14, 30, 60, 120)


@dataclass(frozen=True)
class ConjugationItem:
    key: str
    language: GrammarLanguage
    topic_key: str
    lemma: str
    form: str
    person: str
    answers: tuple[str, ...]
    note: str = ""

    @property
    def reference_answer(self) -> str:
        return self.answers[0]


def _slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _items(
    language: GrammarLanguage,
    topic_key: str,
    lemma: str,
    form: str,
    persons: Iterable[str],
    answers: Iterable[str | tuple[str, ...]],
    *,
    note: str = "",
) -> list[ConjugationItem]:
    result = []
    for person, answer in zip(persons, answers, strict=True):
        accepted = (answer,) if isinstance(answer, str) else answer
        key = ":".join((_slug(topic_key), _slug(form), _slug(lemma), _slug(person)))
        result.append(
            ConjugationItem(
                key=key,
                language=language,
                topic_key=topic_key,
                lemma=lemma,
                form=form,
                person=person,
                answers=accepted,
                note=note,
            )
        )
    return result


ES_PERSONS = ("yo", "tú", "él / ella / usted", "nosotros/as", "vosotros/as", "ellos / ellas / ustedes")
DE_PERSONS = ("ich", "du", "er / sie / es", "wir", "ihr", "sie / Sie")


def _spanish_items() -> list[ConjugationItem]:
    es = GrammarLanguage.SPANISH
    items: list[ConjugationItem] = []

    def paradigm(topic: str, lemma: str, form: str, answers: tuple[str, ...], note: str = "") -> None:
        items.extend(_items(es, topic, lemma, form, ES_PERSONS, answers, note=note))

    paradigm("es_a1_u1_regular_ar_verbs", "estudiar", "presente", ("estudio", "estudias", "estudia", "estudiamos", "estudiáis", "estudian"))
    paradigm("es_a1_u2_regular_er_ir_verbs", "aprender", "presente", ("aprendo", "aprendes", "aprende", "aprendemos", "aprendéis", "aprenden"))
    paradigm("es_a1_u2_regular_er_ir_verbs", "vivir", "presente", ("vivo", "vives", "vive", "vivimos", "vivís", "viven"))
    paradigm("es_a1_u2_verbs_tener_ser", "tener", "presente", ("tengo", "tienes", "tiene", "tenemos", "tenéis", "tienen"))
    paradigm("es_a1_u2_verbs_tener_ser", "ser", "presente", ("soy", "eres", "es", "somos", "sois", "son"))
    for lemma, forms in {
        "querer": ("quiero", "quieres", "quiere", "queremos", "queréis", "quieren"),
        "preferir": ("prefiero", "prefieres", "prefiere", "preferimos", "preferís", "prefieren"),
        "poder": ("puedo", "puedes", "puede", "podemos", "podéis", "pueden"),
        "probar": ("pruebo", "pruebas", "prueba", "probamos", "probáis", "prueban"),
    }.items():
        paradigm("es_a1_u5_irregular_verbs_querer_poder", lemma, "presente", forms)
    for lemma, forms in {
        "ir": ("voy", "vas", "va", "vamos", "vais", "van"),
        "estar": ("estoy", "estás", "está", "estamos", "estáis", "están"),
        "seguir": ("sigo", "sigues", "sigue", "seguimos", "seguís", "siguen"),
    }.items():
        paradigm("es_a1_u6_verbs_ir_estar_seguir", lemma, "presente", forms)
    items.extend(_items(es, "es_a1_u7_irregular_first_person_verbs", "hacer / poner / salir / traer / decir / venir", "presente irregular (yo)", ("hacer", "poner", "salir", "traer", "decir", "venir"), ("hago", "pongo", "salgo", "traigo", "digo", "vengo")))
    paradigm("es_a1_u7_perfect_tense", "comer", "pretérito perfecto", ("he comido", "has comido", "ha comido", "hemos comido", "habéis comido", "han comido"), "Include the auxiliary haber and the participle.")
    items.extend(_items(es, "es_a1_u7_irregular_participles", "hacer / decir / poner / ver", "participio irregular", ("hacer", "decir", "poner", "ver"), ("hecho", "dicho", "puesto", "visto")))
    paradigm("es_a1_u9_reflexive_verbs", "levantarse", "presente reflexivo", ("me levanto", "te levantas", "se levanta", "nos levantamos", "os levantáis", "se levantan"), "Include the reflexive pronoun.")
    items.extend(_items(es, "es_a1_u9_gerund", "hablar / comer / escribir", "gerundio", ("hablar", "comer", "escribir"), ("hablando", "comiendo", "escribiendo")))
    items.extend(_items(es, "es_a1_u9_irregular_gerunds", "decir / venir / dormir", "gerundio irregular", ("decir", "venir", "dormir"), ("diciendo", "viniendo", "durmiendo")))
    for lemma, forms in {
        "saber": ("sé", "sabes", "sabe", "sabemos", "sabéis", "saben"),
        "poder": ("puedo", "puedes", "puede", "podemos", "podéis", "pueden"),
    }.items():
        paradigm("es_a1_u10_saber_and_poder", lemma, "presente", forms)
    paradigm("es_a1_u10_near_future_ir_a_infinitive", "trabajar", "futuro próximo (ir a + infinitivo)", ("voy a trabajar", "vas a trabajar", "va a trabajar", "vamos a trabajar", "vais a trabajar", "van a trabajar"), "Include the form of ir, a, and the infinitive.")
    for lemma, forms in {
        "trabajar": ("trabajé", "trabajaste", "trabajó", "trabajamos", "trabajasteis", "trabajaron"),
        "aprender": ("aprendí", "aprendiste", "aprendió", "aprendimos", "aprendisteis", "aprendieron"),
        "vivir": ("viví", "viviste", "vivió", "vivimos", "vivisteis", "vivieron"),
        "ir / ser": ("fui", "fuiste", "fue", "fuimos", "fuisteis", "fueron"),
    }.items():
        paradigm("es_a1_u11_indefinido", lemma, "pretérito indefinido", forms)
    paradigm("es_a2_u1_preterite_irregular_forms", "tener", "pretérito indefinido irregular", ("tuve", "tuviste", "tuvo", "tuvimos", "tuvisteis", "tuvieron"))
    for lemma, forms in {
        "buscar": ("buscaba", "buscabas", "buscaba", "buscábamos", "buscabais", "buscaban"),
        "hacer": ("hacía", "hacías", "hacía", "hacíamos", "hacíais", "hacían"),
    }.items():
        paradigm("es_a2_u3_imperfect_tense", lemma, "pretérito imperfecto", forms)
    items.extend(_items(es, "es_a2_u3_imperfect_tense", "haber", "pretérito imperfecto impersonal", ("forma impersonal",), ("había",)))
    items.extend(_items(es, "es_a2_u6_affirmative_imperative", "pasar", "imperativo afirmativo", ("tú", "usted", "ustedes"), ("pasa", "pase", "pasen")))
    items.extend(_items(es, "es_a2_u6_affirmative_imperative", "beber", "imperativo afirmativo", ("tú", "usted", "ustedes"), ("bebe", "beba", "beban")))
    items.extend(_items(es, "es_a2_u6_affirmative_imperative", "abrir", "imperativo afirmativo", ("tú", "usted", "ustedes"), ("abre", "abra", "abran")))
    items.extend(_items(es, "es_a2_u6_affirmative_imperative", "ponerse", "imperativo afirmativo", ("tú",), ("ponte",), note="Include the attached reflexive pronoun."))
    for lemma, forms in {
        "tomar": ("no tomes", "no tome", "no tomen"),
        "beber": ("no bebas", "no beba", "no beban"),
        "pedir": ("no pidas", "no pida", "no pidan"),
        "decir": ("no digas", "no diga", "no digan"),
    }.items():
        items.extend(_items(es, "es_a2_u7_negative_imperative", lemma, "imperativo negativo", ("tú", "usted", "ustedes"), forms, note="Include no."))
    paradigm("es_a2_u9_future_tense", "hablar", "futuro simple", ("hablaré", "hablarás", "hablará", "hablaremos", "hablaréis", "hablarán"))
    items.extend(_items(es, "es_a2_u9_future_tense", "estar", "futuro simple", ("ellos / ellas / ustedes",), ("estarán",)))
    paradigm("es_a2_u10_conditional", "poder", "condicional simple", ("podría", "podrías", "podría", "podríamos", "podríais", "podrían"))
    items.extend(_items(es, "es_a2_u10_conditional", "encantar", "condicional simple", ("él / ella / usted",), ("encantaría",)))
    return items


def _german_items() -> list[ConjugationItem]:
    de = GrammarLanguage.GERMAN
    items: list[ConjugationItem] = []

    def paradigm(topic: str, lemma: str, form: str, answers: tuple[str, ...], note: str = "") -> None:
        items.extend(_items(de, topic, lemma, form, DE_PERSONS, answers, note=note))

    paradigm("a1b1_praeteritum_perfekt", "sein", "Präteritum", ("war", "warst", "war", "waren", "wart", "waren"))
    paradigm("a1b1_praeteritum_perfekt", "haben", "Präteritum", ("hatte", "hattest", "hatte", "hatten", "hattet", "hatten"))
    paradigm("a1b1_praeteritum_perfekt", "machen", "Perfekt", ("habe gemacht", "hast gemacht", "hat gemacht", "haben gemacht", "habt gemacht", "haben gemacht"), "Supply the complete verb phrase.")
    for lemma, forms in {
        "können": ("konnte", "konntest", "konnte", "konnten", "konntet", "konnten"),
        "müssen": ("musste", "musstest", "musste", "mussten", "musstet", "mussten"),
        "dürfen": ("durfte", "durftest", "durfte", "durften", "durftet", "durften"),
        "sollen": ("sollte", "solltest", "sollte", "sollten", "solltet", "sollten"),
        "wollen": ("wollte", "wolltest", "wollte", "wollten", "wolltet", "wollten"),
        "mögen": ("mochte", "mochtest", "mochte", "mochten", "mochtet", "mochten"),
    }.items():
        paradigm("a1b1_praeteritum_perfekt", lemma, "Präteritum", forms)
    for lemma, forms in {
        "haben": ("hätte", "hättest", "hätte", "hätten", "hättet", "hätten"),
        "sein": ("wäre", "wärst", "wäre", "wären", "wärt", "wären"),
        "werden": ("würde", "würdest", "würde", "würden", "würdet", "würden"),
    }.items():
        paradigm("b2c1_konjunktiv2_gegenwart_formen", lemma, "Konjunktiv II Gegenwart", forms)
    paradigm("b2c1_gebrauch_von_zeiten_der_vergangenheit", "wissen", "Präteritum", ("wusste", "wusstest", "wusste", "wussten", "wusstet", "wussten"))
    for lemma, forms in {
        "wollen": ("will", "willst", "will", "wollen", "wollt", "wollen"),
        "können": ("kann", "kannst", "kann", "können", "könnt", "können"),
        "müssen": ("muss", "musst", "muss", "müssen", "müsst", "müssen"),
    }.items():
        paradigm("b2c1_modalverben_grundbedeutung", lemma, "Präsens", forms)
    paradigm("b2c1_modalverben_vermutungen_gegenwart", "da sein", "Vermutung mit müssen (Gegenwart)", ("muss da sein", "musst da sein", "muss da sein", "müssen da sein", "müsst da sein", "müssen da sein"), "Supply the modal construction.")
    paradigm("b2c1_das_verb_lassen", "lassen", "Präsens", ("lasse", "lässt", "lässt", "lassen", "lasst", "lassen"))
    paradigm("b2c1_bildung_der_vergangenheitszeiten", "zerbrechen (intransitiv)", "Perfekt", ("bin zerbrochen", "bist zerbrochen", "ist zerbrochen", "sind zerbrochen", "seid zerbrochen", "sind zerbrochen"), "Supply the auxiliary and participle.")
    paradigm("b2c1_bildung_der_vergangenheitszeiten", "zerbrechen (transitiv)", "Perfekt", ("habe zerbrochen", "hast zerbrochen", "hat zerbrochen", "haben zerbrochen", "habt zerbrochen", "haben zerbrochen"), "Supply the auxiliary and participle.")
    paradigm("b2c1_indirekte_rede_konjunktiv_1", "sein", "Konjunktiv I Gegenwart", ("sei", "seiest", "sei", "seien", "seiet", "seien"))
    paradigm("b2c1_indirekte_rede_konjunktiv_1", "kommen", "Konjunktiv I Gegenwart", ("komme", "kommest", "komme", "kommen", "kommet", "kommen"))
    paradigm("b2c1_indirekte_rede_vergangenheit", "Glück haben", "Konjunktiv I Vergangenheit", ("habe Glück gehabt", "habest Glück gehabt", "habe Glück gehabt", "haben Glück gehabt", "habet Glück gehabt", "haben Glück gehabt"), "Supply the complete verb phrase.")
    paradigm("b2c1_konjunktiv2_vergangenheit_formen", "zu Hause bleiben", "Konjunktiv II Vergangenheit", ("wäre zu Hause geblieben", "wärst zu Hause geblieben", "wäre zu Hause geblieben", "wären zu Hause geblieben", "wärt zu Hause geblieben", "wären zu Hause geblieben"), "Supply the complete verb phrase.")
    passive = {
        "Präsens Passiv": ("werde informiert", "wirst informiert", "wird informiert", "werden informiert", "werdet informiert", "werden informiert"),
        "Präteritum Passiv": ("wurde informiert", "wurdest informiert", "wurde informiert", "wurden informiert", "wurdet informiert", "wurden informiert"),
        "Perfekt Passiv": ("bin informiert worden", "bist informiert worden", "ist informiert worden", "sind informiert worden", "seid informiert worden", "sind informiert worden"),
        "Plusquamperfekt Passiv": ("war informiert worden", "warst informiert worden", "war informiert worden", "waren informiert worden", "wart informiert worden", "waren informiert worden"),
        "Futur I Passiv": ("werde informiert werden", "wirst informiert werden", "wird informiert werden", "werden informiert werden", "werdet informiert werden", "werden informiert werden"),
    }
    for form, forms in passive.items():
        paradigm("b2c1_passiv_in_allen_zeiten", "informieren", form, forms, "Supply the complete passive verb phrase.")
    items.extend(_items(de, "b2c1_passiv_mit_modalverben", "erledigen", "Passiv mit Modalverb", ("er / sie / es · Präsens", "er / sie / es · Präteritum", "er / sie / es · Perfekt"), ("muss erledigt werden", "musste erledigt werden", "hat erledigt werden müssen"), note="Supply the complete verb phrase."))
    paradigm("b2c1_besondere_perfektformen", "gehen müssen", "Perfekt mit Ersatzinfinitiv", ("habe gehen müssen", "hast gehen müssen", "hat gehen müssen", "haben gehen müssen", "habt gehen müssen", "haben gehen müssen"), "Supply the complete verb phrase.")
    for lemma, forms in {
        "kommen sehen": ("habe kommen sehen", "hast kommen sehen", "hat kommen sehen", "haben kommen sehen", "habt kommen sehen", "haben kommen sehen"),
        "kommen hören": ("habe kommen hören", "hast kommen hören", "hat kommen hören", "haben kommen hören", "habt kommen hören", "haben kommen hören"),
        "gehen lassen": ("habe gehen lassen", "hast gehen lassen", "hat gehen lassen", "haben gehen lassen", "habt gehen lassen", "haben gehen lassen"),
    }.items():
        paradigm("b2c1_besondere_perfektformen", lemma, "besonderes Perfekt", forms, "Supply the complete verb phrase.")
    paradigm("b2c1_vermutung_zukunft_futur", "den Zug verpassen", "Futur II", ("werde den Zug verpasst haben", "wirst den Zug verpasst haben", "wird den Zug verpasst haben", "werden den Zug verpasst haben", "werdet den Zug verpasst haben", "werden den Zug verpasst haben"), "Supply the complete verb phrase.")
    overview = {
        "Präsens": ("mache", "machst", "macht", "machen", "macht", "machen"),
        "Präteritum": ("machte", "machtest", "machte", "machten", "machtet", "machten"),
        "Perfekt": ("habe gemacht", "hast gemacht", "hat gemacht", "haben gemacht", "habt gemacht", "haben gemacht"),
        "Plusquamperfekt": ("hatte gemacht", "hattest gemacht", "hatte gemacht", "hatten gemacht", "hattet gemacht", "hatten gemacht"),
        "Futur I": ("werde machen", "wirst machen", "wird machen", "werden machen", "werdet machen", "werden machen"),
        "Futur II": ("werde gemacht haben", "wirst gemacht haben", "wird gemacht haben", "werden gemacht haben", "werdet gemacht haben", "werden gemacht haben"),
    }
    for form, forms in overview.items():
        paradigm("b2c1_ueberblick_zeiten", "machen", form, forms, "Supply the complete verb phrase.")
    items.extend(_items(de, "b2c1_modalverben_vermutungen_vergangenheit", "zu Fuß gehen", "Vermutung über die Vergangenheit", ("sie (Singular)",), ("muss zu Fuß gegangen sein",), note="Supply the modal construction."))
    return items


CONJUGATION_ITEMS = tuple(_german_items() + _spanish_items())
CONJUGATION_ITEMS_BY_KEY = {item.key: item for item in CONJUGATION_ITEMS}
CONJUGATION_TOPIC_KEYS = frozenset(item.topic_key for item in CONJUGATION_ITEMS)

if len(CONJUGATION_ITEMS_BY_KEY) != len(CONJUGATION_ITEMS):
    raise ValueError("Duplicate conjugation workout key")


def validate_conjugation_inventory(catalogues: Iterable[GrammarTopic]) -> None:
    topics = {topic.key: topic for topic in catalogues}
    missing = CONJUGATION_TOPIC_KEYS - topics.keys()
    if missing:
        raise ValueError(f"Conjugation topics absent from grammar catalogues: {sorted(missing)}")
    for item in CONJUGATION_ITEMS:
        if topics[item.topic_key].language is not item.language:
            raise ValueError(f"Wrong language for conjugation item {item.key}")


def normalize_conjugation_answer(value: str) -> str:
    value = unicodedata.normalize("NFC", value).casefold().strip()
    value = re.sub(r"[.!?¡¿]+$", "", value)
    return re.sub(r"\s+", " ", value)


def grade_conjugation(item: ConjugationItem, answer: str) -> bool:
    normalized = normalize_conjugation_answer(answer)
    return normalized in {normalize_conjugation_answer(value) for value in item.answers}


def schedule_conjugation(
    state: ScheduleState, *, correct: bool, reviewed_at: datetime
) -> ScheduleState:
    if reviewed_at.tzinfo is None:
        raise ValueError("reviewed_at must include a timezone")
    reviewed_at = reviewed_at.astimezone(UTC)
    if not correct:
        return ScheduleState(
            repetitions=state.repetitions,
            lapses=state.lapses + 1,
            consecutive_correct=0,
            last_reviewed_at=reviewed_at,
            next_review_at=reviewed_at,
        )
    streak = state.consecutive_correct + 1
    days = CONJUGATION_INTERVAL_DAYS[
        min(streak - 1, len(CONJUGATION_INTERVAL_DAYS) - 1)
    ]
    return ScheduleState(
        repetitions=state.repetitions + 1,
        lapses=state.lapses,
        consecutive_correct=streak,
        last_reviewed_at=reviewed_at,
        next_review_at=reviewed_at + timedelta(days=days),
    )
