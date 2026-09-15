# German grammar rule source

This directory is an inactive drafting area for textbook grammar rules. The
application does not read these files yet; grammar sessions continue to use the
metadata and examples in `pdf_language_learner/german_grammar_catalogue.py`.

Enter the selected A1–B1 review material in `a1-b1.md` and the Grammatik Aktiv
B2/C1 material in `b2-c1.md`. Each grammar topic already has a heading and its
stable catalogue key in a `topic` comment. Keep those comments unchanged,
because they provide a reliable way to connect the prose to the catalogue
later.

Replace each `TODO` comment with the rule text. Use ordinary Markdown for
paragraphs, lists, examples, emphasis, and tables. For example:

```markdown
<!-- topic: b2c1_position_dativ_akkusativobjekt -->
## Position von Dativ- und Akkusativobjekt

When both objects are nouns, the dative object normally precedes the
accusative object.

| Objects | Usual order |
|---------|-------------|
| Two nouns | Dative → accusative |
| Two pronouns | Accusative → dative |
```

The section heading is for navigation; it does not need to match the textbook
word for word. Keep all material belonging to a topic between its `topic`
comment and the next `topic` comment. If the textbook treats two catalogue
topics together, repeat the relevant text or add a short cross-reference so
that each section remains understandable on its own.

When every `TODO` has been replaced, the files will be ready for a separate
integration change that loads these rules and includes them in model prompts.

