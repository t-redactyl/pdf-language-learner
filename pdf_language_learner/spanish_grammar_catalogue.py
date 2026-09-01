"""Static catalogue of Spanish grammar topics, mirroring
german_grammar_catalogue.py's design for German: structured metadata only (no
prose explanations), used to drive topic selection and spaced-repetition
scheduling for the grammar revision feature.

As with the German catalogue, explanations and exercises are generated on
demand by an LLM call seeded with this metadata, rather than stored
verbatim - even though the source PDFs this was built from ("A1 Spanish
grammar" and "A2 Spanish grammar") contain full written explanations. Storing only
the topic identity and one illustrative example keeps the catalogue small,
avoids duplicating content a model can generate well, and lets explanations
be tailored to the learner rather than fixed.

Unlike the German source (Grammatik Aktiv B2/C1), this book does not group
topics by grammatical category across units - each "Unidad" bundles several
unrelated grammar points together. The catalogue therefore keeps the book's
unit in `source_group` and assigns a separate grammar-oriented `category` for
session interleaving.
Both source books omit Units 4 and 8; this reflects their tables of contents
rather than an extraction gap.

Keys are stable slugs and must not be renamed once scheduling data
(`grammar_reviews` rows, if/when that table exists) references them.
"""

from __future__ import annotations

from enum import StrEnum

from pdf_language_learner.grammar_topics import (
    GrammarLanguage,
    GrammarLevel,
    GrammarTopic,
    ordered_grammar_topics,
)


class SpanishGrammarBook(StrEnum):
    A1_GRAMMAR_COMPANION = "a1_spanish_grammar"
    A2_GRAMMAR_COMPANION = "a2_spanish_grammar"


def spanish_grammar_topic(**values) -> GrammarTopic:
    return GrammarTopic(language=GrammarLanguage.SPANISH, **values)


def a1_spanish_grammar_topic(
    key: str,
    unit: int,
    category: str,
    title: str,
    example: str,
) -> GrammarTopic:
    return spanish_grammar_topic(
        key=key,
        book=SpanishGrammarBook.A1_GRAMMAR_COMPANION,
        level=GrammarLevel.A1,
        category=category,
        source_group=f"A1 - Unidad {unit}",
        title=title,
        example=example,
    )


_A1_SPANISH_GRAMMAR_TOPICS: tuple[GrammarTopic, ...] = (
    a1_spanish_grammar_topic("es_a1_u1_definite_articles", 1, "Articles", "Definite articles", "el teatro / los teatros; la palabra / las palabras"),
    a1_spanish_grammar_topic("es_a1_u1_gender_of_nouns", 1, "Nouns", "Gender of nouns", "el libro (masculine); la mesa (feminine)"),
    a1_spanish_grammar_topic("es_a1_u1_plural_of_nouns", 1, "Nouns", "Plural of nouns", "playa -> playas; hotel -> hoteles"),
    a1_spanish_grammar_topic("es_a1_u1_personal_pronouns", 1, "Subject pronouns", "Personal pronouns", "yo, tú, él/ella/usted, nosotros/as, vosotros/as, ellos/ellas/ustedes"),
    a1_spanish_grammar_topic("es_a1_u1_regular_ar_verbs", 1, "Present tense", "Regular -ar verbs", "estudio, estudias, estudia, estudiamos, estudiáis, estudian"),
    a1_spanish_grammar_topic("es_a1_u1_pronunciation", 1, "Pronunciation", "Pronunciation", "cinco ('th'/'s'); llave ('y'); año ('ny')"),
    a1_spanish_grammar_topic("es_a1_u2_indefinite_articles", 2, "Articles", "Indefinite articles", "un libro, una mesa, unos libros, unas mesas"),
    a1_spanish_grammar_topic("es_a1_u2_masculine_feminine_professions", 2, "Nouns and adjectives", "Masculine and feminine professions", "el enfermero / la enfermera; el camarero / la camarera"),
    a1_spanish_grammar_topic("es_a1_u2_negation", 2, "Negation", "Negation", "No trabajo los domingos."),
    a1_spanish_grammar_topic("es_a1_u2_regular_er_ir_verbs", 2, "Present tense", "Regular -er and -ir verbs", "aprendo, aprendes... / vivo, vives..."),
    a1_spanish_grammar_topic("es_a1_u2_verbs_tener_ser", 2, "Present tense", "Verbs tener and ser", "Tengo veinte años. Soy español."),
    a1_spanish_grammar_topic("es_a1_u3_possessive_adjectives", 3, "Possessives", "Possessive adjectives", "mi casa, tu libro, su coche, nuestra familia"),
    a1_spanish_grammar_topic("es_a1_u3_adjectives", 3, "Adjectives", "Adjectives", "un chico alto, una chica alta"),
    a1_spanish_grammar_topic("es_a1_u3_questions", 3, "Interrogatives", "Questions", "¿Quién es? ¿Cuántos años tienes? ¿Por qué? ¿Cómo estás?"),
    a1_spanish_grammar_topic("es_a1_u5_direct_object_pronouns", 5, "Object pronouns", "Direct object pronouns", "¿Tienes el libro? Sí, lo tengo."),
    a1_spanish_grammar_topic("es_a1_u5_numbers_above_100", 5, "Numbers", "Numbers above 100", "cien, doscientos, quinientos, mil, un millón"),
    a1_spanish_grammar_topic("es_a1_u5_irregular_verbs_querer_poder", 5, "Present tense", "Irregular verbs (querer, preferir, poder, probar)", "quiero, prefiero, puedo, pruebo"),
    a1_spanish_grammar_topic("es_a1_u5_telling_time", 5, "Time expressions", "Telling time", "Es la una. Son las dos y cuarto."),
    a1_spanish_grammar_topic("es_a1_u6_hay_vs_esta_estan", 6, "Hay and estar", "Using hay and está/están", "Hay un hotel en la calle. El hotel está cerca del centro."),
    a1_spanish_grammar_topic("es_a1_u6_location_expressions", 6, "Location", "Location expressions", "a la derecha, delante, cerca, enfrente"),
    a1_spanish_grammar_topic("es_a1_u6_use_of_a_and_en", 6, "Prepositions", "Use of a and en", "Voy a Madrid. Vivo en Madrid."),
    a1_spanish_grammar_topic("es_a1_u6_contraction_of_articles", 6, "Articles", "Contraction of articles", "Vamos al cine. Vengo del trabajo."),
    a1_spanish_grammar_topic("es_a1_u6_verbs_ir_estar_seguir", 6, "Present tense", "Verbs ir, estar, seguir", "voy, vas... / estoy, estás... / sigo, sigues..."),
    a1_spanish_grammar_topic("es_a1_u7_indirect_object_pronouns", 7, "Object pronouns", "Indirect object pronouns", "Me gusta el café. Le doy el libro."),
    a1_spanish_grammar_topic("es_a1_u7_muy_and_mucho", 7, "Quantifiers and degree", "Muy and mucho", "Es muy interesante. Tengo mucho trabajo."),
    a1_spanish_grammar_topic("es_a1_u7_irregular_first_person_verbs", 7, "Present tense", "Irregular first-person verbs", "hago, pongo, salgo, traigo, digo, vengo"),
    a1_spanish_grammar_topic("es_a1_u7_perfect_tense", 7, "Past tenses", "Perfect tense", "He comido. Hemos viajado mucho."),
    a1_spanish_grammar_topic("es_a1_u7_irregular_participles", 7, "Past tenses", "Irregular participles", "hecho, dicho, puesto, visto"),
    a1_spanish_grammar_topic("es_a1_u9_comparative_superlative", 9, "Comparisons", "Comparative and superlative", "más alto que, menos caro que, tan bueno como"),
    a1_spanish_grammar_topic("es_a1_u9_reflexive_verbs", 9, "Reflexive verbs", "Reflexive verbs", "Me levanto a las siete. Te levantas tarde."),
    a1_spanish_grammar_topic("es_a1_u9_demonstrative_adjectives", 9, "Demonstratives", "Demonstrative adjectives", "este libro, esa mesa"),
    a1_spanish_grammar_topic("es_a1_u9_gerund", 9, "Gerunds", "Gerund", "hablando, comiendo, escribiendo"),
    a1_spanish_grammar_topic("es_a1_u9_irregular_gerunds", 9, "Gerunds", "Irregular gerunds", "diciendo, viniendo, durmiendo"),
    a1_spanish_grammar_topic("es_a1_u10_relative_pronouns", 10, "Relative clauses", "Relative pronouns", "el libro que leo; la ciudad donde vivo"),
    a1_spanish_grammar_topic("es_a1_u10_otro_un_poco_de", 10, "Determiners and quantities", "Otro/a and un poco de", "Quiero otro café. Un poco de agua, por favor."),
    a1_spanish_grammar_topic("es_a1_u10_nationality_adjectives", 10, "Adjectives", "Nationality adjectives", "italiano/italiana, español/española"),
    a1_spanish_grammar_topic("es_a1_u10_saber_and_poder", 10, "Ability verbs", "Saber and poder", "Sé nadar. ¿Puedes ayudarme?"),
    a1_spanish_grammar_topic("es_a1_u10_prepositions_plus_pronouns", 10, "Prepositions", "Prepositions + pronouns", "Ven conmigo. Voy contigo."),
    a1_spanish_grammar_topic("es_a1_u10_near_future_ir_a_infinitive", 10, "Future constructions", "Near future with ir + a + infinitive", "Voy a trabajar mañana."),
    a1_spanish_grammar_topic("es_a1_u11_indefinido", 11, "Past tenses", "Preterite (pretérito indefinido)", "trabajé, aprendí, fui"),
    a1_spanish_grammar_topic("es_a1_u11_time_markers_indefinido_perfecto", 11, "Past tenses", "Time markers for indefinido and perfecto", "ayer, la semana pasada / hoy, esta semana"),
    a1_spanish_grammar_topic("es_a1_u11_quantifiers", 11, "Quantifiers and degree", "Quantifiers", "todos los días, muchos amigos, algunos libros"),
    a1_spanish_grammar_topic("es_a1_u11_indefinido_vs_perfecto", 11, "Past tenses", "Use of indefinido vs perfecto", "Indefinido: completed past period. Perfecto: unfinished period."),
)


_A2_SPANISH_GRAMMAR_TOPICS: tuple[GrammarTopic, ...] = (
    # --- Unidad 1 ---
    spanish_grammar_topic(
        key="es_a2_u1_infinitive_gerund_constructions",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Verb constructions",
        source_group="A2 - Unidad 1",
        title="Infinitive and gerund constructions",
        example="Empiezo a estudiar; vuelvo a leer; sigue leyendo; deja de hablar.",
    ),
    spanish_grammar_topic(
        key="es_a2_u1_lo_lo_que",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Pronouns and clauses",
        source_group="A2 - Unidad 1",
        title="Lo and lo que",
        example="Lo que más me gusta es leer.",
    ),
    spanish_grammar_topic(
        key="es_a2_u1_adjectives_ending_in_or",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Adjectives",
        source_group="A2 - Unidad 1",
        title="Adjectives ending in -or",
        example="un chico trabajador, una chica trabajadora",
    ),
    spanish_grammar_topic(
        key="es_a2_u1_hace_desde_desde_hace",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Time expressions",
        source_group="A2 - Unidad 1",
        title="Hace, desde and desde hace",
        example="Estudio español desde hace un año.",
    ),
    spanish_grammar_topic(
        key="es_a2_u1_preterite_irregular_forms",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Past tenses",
        source_group="A2 - Unidad 1",
        title="Irregular forms of the preterite",
        example="tuve, tuviste, tuvo, tuvimos, tuvisteis, tuvieron",
    ),
    # --- Unidad 2 ---
    spanish_grammar_topic(
        key="es_a2_u2_que_cual_cuales",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Interrogatives",
        source_group="A2 - Unidad 2",
        title="Qué and cuál/cuáles",
        example="¿Cuál es la tienda más cercana?",
    ),
    spanish_grammar_topic(
        key="es_a2_u2_indefinite_pronouns_determiners",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Determiners and pronouns",
        source_group="A2 - Unidad 2",
        title="Indefinite pronouns and determiners",
        example="No compro nada. Algunos libros, ninguna revista.",
    ),
    spanish_grammar_topic(
        key="es_a2_u2_object_pronouns_together",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Object pronouns",
        source_group="A2 - Unidad 2",
        title="Direct and indirect object pronouns together",
        example="Se lo compro a Eva. Quiero comprármelo.",
    ),
    # --- Unidad 3 ---
    spanish_grammar_topic(
        key="es_a2_u3_adjectives_and_adverbs",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Adjectives and adverbs",
        source_group="A2 - Unidad 3",
        title="Adjectives and adverbs",
        example="Hago deporte regularmente. Dormimos tranquilamente.",
    ),
    spanish_grammar_topic(
        key="es_a2_u3_adverbs_ending_in_mente",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Adverbs",
        source_group="A2 - Unidad 3",
        title="Adverbs ending in -mente",
        example="tranquilo -> tranquilamente; fácil -> fácilmente",
    ),
    spanish_grammar_topic(
        key="es_a2_u3_imperfect_tense",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Past tenses",
        source_group="A2 - Unidad 3",
        title="The imperfect tense",
        example="buscaba, buscabas... / hacía, hacías... / había",
    ),
    # --- Unidad 5 ---
    spanish_grammar_topic(
        key="es_a2_u5_reflexive_meaning_change",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Reflexive verbs",
        source_group="A2 - Unidad 5",
        title="Reflexive and non-reflexive verbs with different meanings",
        example="Me pongo triste. Pongo las llaves en el bolso.",
    ),
    spanish_grammar_topic(
        key="es_a2_u5_diminutives",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Word formation",
        source_group="A2 - Unidad 5",
        title="Diminutives",
        example="libro -> librito; ratón -> ratoncito",
    ),
    spanish_grammar_topic(
        key="es_a2_u5_preterite_imperfect_together",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Past tenses",
        source_group="A2 - Unidad 5",
        title="Preterite and imperfect together",
        example="El ratoncito caminaba por la playa cuando vio una tortuga.",
    ),
    # --- Unidad 6 ---
    spanish_grammar_topic(
        key="es_a2_u6_ir_venir_llevar_traer",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Deictic verbs",
        source_group="A2 - Unidad 6",
        title="Ir/venir and llevar/traer",
        example="¿Vienes a la fiesta? Voy a la fiesta y llevo el pastel.",
    ),
    spanish_grammar_topic(
        key="es_a2_u6_absolute_superlative_isimo",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Adjectives",
        source_group="A2 - Unidad 6",
        title="Absolute superlative with -ísimo",
        example="bueno -> buenísimo; rico -> riquísimo",
    ),
    spanish_grammar_topic(
        key="es_a2_u6_shortened_adjectives",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Adjectives",
        source_group="A2 - Unidad 6",
        title="Shortened adjectives",
        example="un gran vino; un buen amigo; hace mal tiempo",
    ),
    spanish_grammar_topic(
        key="es_a2_u6_affirmative_imperative",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Imperative",
        source_group="A2 - Unidad 6",
        title="Affirmative imperative",
        example="pasa, bebe, abre; ¡Empiece!; ponte, ábrela",
    ),
    # --- Unidad 7 ---
    spanish_grammar_topic(
        key="es_a2_u7_negative_imperative",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Imperative",
        source_group="A2 - Unidad 7",
        title="Negative imperative",
        example="No tomes, no beba, no pidan. No se lo digas.",
    ),
    spanish_grammar_topic(
        key="es_a2_u7_demonstrative_adjectives_pronouns",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Demonstratives",
        source_group="A2 - Unidad 7",
        title="Demonstrative adjectives and pronouns",
        example="este/esta/estos/estas; ese/esa; aquel/aquella",
    ),
    spanish_grammar_topic(
        key="es_a2_u7_stressed_possessive_pronouns",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Possessives",
        source_group="A2 - Unidad 7",
        title="Stressed possessive pronouns",
        example="Mi hijo ya habla. El mío todavía no. Esta pelota es mía.",
    ),
    # --- Unidad 9 ---
    spanish_grammar_topic(
        key="es_a2_u9_ser_estar",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Ser and estar",
        source_group="A2 - Unidad 9",
        title="Ser and estar",
        example="Soy Pablo. Soy venezolano. / Está casado. Estoy nervioso.",
    ),
    spanish_grammar_topic(
        key="es_a2_u9_comparison_tanto_como",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Comparisons",
        source_group="A2 - Unidad 9",
        title="Comparison with tanto...como",
        example="No se paga tanto como en otras tiendas.",
    ),
    spanish_grammar_topic(
        key="es_a2_u9_future_tense",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Future tense",
        source_group="A2 - Unidad 9",
        title="The future tense",
        example="hablaré, hablarás... / ¿Dónde están mis gafas? Estarán en la mesa.",
    ),
    # --- Unidad 10 ---
    spanish_grammar_topic(
        key="es_a2_u10_mismo",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Determiners and expressions",
        source_group="A2 - Unidad 10",
        title="Mismo",
        example="el mismo canal; ahora mismo; Me da lo mismo.",
    ),
    spanish_grammar_topic(
        key="es_a2_u10_preposition_para",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Prepositions",
        source_group="A2 - Unidad 10",
        title="The preposition para",
        example="un billete para Valencia; Para mí...",
    ),
    spanish_grammar_topic(
        key="es_a2_u10_preposition_por",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Prepositions",
        source_group="A2 - Unidad 10",
        title="The preposition por",
        example="un paseo por el barrio; por 20 euros",
    ),
    spanish_grammar_topic(
        key="es_a2_u10_conditional",
        book=SpanishGrammarBook.A2_GRAMMAR_COMPANION,
        level=GrammarLevel.A2,
        category="Conditional",
        source_group="A2 - Unidad 10",
        title="The conditional",
        example="¿Podría decirme la hora? Me encantaría ir.",
    ),
)


SPANISH_GRAMMAR_TOPICS: tuple[GrammarTopic, ...] = ordered_grammar_topics(
    GrammarLanguage.SPANISH,
    _A1_SPANISH_GRAMMAR_TOPICS + _A2_SPANISH_GRAMMAR_TOPICS,
)
A1_SPANISH_GRAMMAR_TOPICS: tuple[GrammarTopic, ...] = tuple(
    topic
    for topic in SPANISH_GRAMMAR_TOPICS
    if topic.book is SpanishGrammarBook.A1_GRAMMAR_COMPANION
)
A2_SPANISH_GRAMMAR_TOPICS: tuple[GrammarTopic, ...] = tuple(
    topic
    for topic in SPANISH_GRAMMAR_TOPICS
    if topic.book is SpanishGrammarBook.A2_GRAMMAR_COMPANION
)


def spanish_grammar_topic_by_key(key: str) -> GrammarTopic | None:
    for topic in SPANISH_GRAMMAR_TOPICS:
        if topic.key == key:
            return topic
    return None


def spanish_grammar_topics_by_category(
    book: SpanishGrammarBook | None = None,
) -> dict[str, tuple[GrammarTopic, ...]]:
    """Group topics by grammatical category, preserving catalogue order."""

    ordered: dict[str, list[GrammarTopic]] = {}
    for topic in SPANISH_GRAMMAR_TOPICS:
        if book is not None and topic.book is not book:
            continue
        ordered.setdefault(topic.category, []).append(topic)
    return {category: tuple(topics) for category, topics in ordered.items()}


def spanish_grammar_topics_by_source_group(
    book: SpanishGrammarBook | None = None,
) -> dict[str, tuple[GrammarTopic, ...]]:
    """Group topics by source-book unit, preserving catalogue order."""

    ordered: dict[str, list[GrammarTopic]] = {}
    for topic in SPANISH_GRAMMAR_TOPICS:
        if book is not None and topic.book is not book:
            continue
        if topic.source_group is not None:
            ordered.setdefault(topic.source_group, []).append(topic)
    return {source_group: tuple(topics) for source_group, topics in ordered.items()}
