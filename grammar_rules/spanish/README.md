# Spanish grammar rule source

This directory is an inactive drafting area for textbook grammar rules. The
application does not read these files yet; grammar sessions continue to use the
metadata and examples in `pdf_language_learner/spanish_grammar_catalogue.py`.

Enter the A1 material in `a1.md` and the A2 material in `a2.md`. Each grammar
topic already has a heading and its stable catalogue key in a `topic` comment.
Keep those comments unchanged, because they provide a reliable way to connect
the prose to the existing catalogue later.

Replace each `TODO` comment with the rule text. Use ordinary Markdown for
paragraphs, lists, examples, emphasis, and tables. For example:

```markdown
<!-- topic: es_a1_u1_definite_articles -->
## Definite articles

Spanish definite articles agree with the noun in gender and number.

|          | Singular | Plural |
|----------|----------|--------|
| Masculine | el      | los    |
| Feminine  | la      | las    |
```

The section heading is for navigation; it does not need to match the textbook
word for word. Keep all material belonging to a topic between its `topic`
comment and the next `topic` comment. If the textbook treats two catalogue
topics together, repeat the relevant text or add a short cross-reference so
that each section remains understandable on its own.

When every `TODO` has been replaced, the files will be ready for a separate
integration change that loads these rules and includes them in model prompts.

