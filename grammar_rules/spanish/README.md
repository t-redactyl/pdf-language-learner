# Spanish grammar rule source

This directory contains optional, human-authored grammar rules used by grammar
generation. A completed section for a selected topic is supplied to the model as
its primary source. When a selected topic is incomplete, completed sections from
this directory are supplied as style and depth exemplars instead.

Enter the A1 material in `a1.md` and the A2 material in `a2.md`. Each grammar
topic already has a heading and its stable catalogue key in a `topic` comment.
Keep those comments unchanged, because they provide a reliable way to connect
the prose to the existing catalogue later.

Replace each `TODO` comment with the rule text. Use ordinary Markdown for
paragraphs, lists, examples, emphasis, and tables. For example:

```markdown
<!-- topic: es_a1_u2_indefinite_articles -->
## Indefinite articles

Spanish indefinite articles agree with the noun in gender and number.

|          | Singular | Plural |
|----------|----------|--------|
| Masculine | un      | unos   |
| Feminine  | una     | unas   |
```

The section heading is for navigation; it does not need to match the textbook
word for word. Keep all material belonging to a topic between its `topic`
comment and the next `topic` comment. If the textbook treats two catalogue
topics together, repeat the relevant text or add a short cross-reference so
that each section remains understandable on its own.

Sections containing a `TODO` are ignored until they are completed. Changes take
effect on newly generated grammar content; existing prepared content is not
rewritten in place.
