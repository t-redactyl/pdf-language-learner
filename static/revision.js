import {
  renderClozeSentence,
  renderHighlightedSentence,
  sentenceContaining,
} from "./text.js?v=5";
import { languageName, t } from "./i18n.js?v=26";
import {
  cancelGrammarRequests,
  initializeGrammarRevision,
  loadGrammarRevision,
} from "./grammar.js?v=16";
import {
  cancelConjugationRequests,
  initializeConjugationWorkout,
  loadConjugationWorkout,
} from "./conjugation.js?v=3";

const $ = selector => document.querySelector(selector);

const view = $("#revision-view");
const loading = $("#revision-loading");
const empty = $("#revision-empty");
const session = $("#revision-session");
const EXERCISE_PREFERENCE_KEY = "margin-revision-exercises";
const DEFAULT_EXERCISES = ["vocabulary", "connectors", "synonyms"];
let queue = [];
let currentCard = null;
let answered = 0;
let correctAnswers = 0;
let removed = 0;
let documentLanguage = "";
let synonymPairsAnswered = 0;
let synonymPairsFirstTry = 0;
let connectorAnswers = 0;
let connectorCorrectAnswers = 0;
let matchingPairs = new Map();
let matchedPairIds = new Set();
let missedPairIds = new Set();
let selectedMatchingSource = null;
let selectedMatchingSynonym = null;
let tilePattern = [];
let tileOptions = [];
let selectedTileIds = [];
let tilesLocked = false;
let hintUsed = false;
let revisionMode = "vocabulary";
let conjugationFocus = null;
const NOUN_GENDERS = new Set(["masculine", "feminine", "neutral"]);
const ARTICLE_GENDERS = {
  german: { der: "masculine", die: "feminine", das: "neutral" },
  spanish: { el: "masculine", la: "feminine" },
  portuguese: { o: "masculine", a: "feminine" },
  italian: { il: "masculine", lo: "masculine", la: "feminine" },
  french: { le: "masculine", la: "feminine" },
  dutch: { het: "neutral" },
};

function nounGender(source, language, supplied = null) {
  if (NOUN_GENDERS.has(supplied)) return supplied;
  const article = String(source).trim().toLocaleLowerCase().match(/^[\p{L}]+/u)?.[0];
  return ARTICLE_GENDERS[String(language).toLocaleLowerCase()]?.[article] || null;
}

function setNounGender(element, gender, showTitle = true) {
  element.classList.remove("noun-masculine", "noun-feminine", "noun-neutral");
  element.removeAttribute("title");
  if (!NOUN_GENDERS.has(gender)) return;
  element.classList.add(`noun-${gender}`);
  if (showTitle) element.title = t("gender.title", { gender: t(`gender.${gender}`) });
}

$("#open-revision")?.addEventListener("click", openRevision);
$("#close-revision")?.addEventListener("click", closeRevision);
$("#revision-continue")?.addEventListener("click", renderNextCard);
$("#revision-remove")?.addEventListener("click", removeCurrentCard);
$("#revision-recall")?.addEventListener("submit", event => {
  event.preventDefault();
  const answer = $("#revision-recall-answer").value.trim();
  if (answer) submitAnswer(answer);
});
$("#revision-tiles")?.addEventListener("submit", event => {
  event.preventDefault();
  if (selectedTileIds.length === tileOptions.length) submitAnswer(tileAnswer());
});
$("#revision-tile-clear")?.addEventListener("click", () => {
  selectedTileIds = [];
  renderLetterTiles();
});
$("#revision-recall-hint")?.addEventListener("click", revealTypedHint);
$("#revision-tile-hint")?.addEventListener("click", revealTileHint);
$("#revision-recall-answer")?.addEventListener("input", updateRecallHintButton);
$("#revision-language")?.addEventListener("change", loadRevisionSession);
$("#revision-mode-vocabulary")?.addEventListener("click", () => setRevisionMode("vocabulary"));
$("#revision-mode-grammar")?.addEventListener("click", () => setRevisionMode("grammar"));
$("#revision-mode-conjugation")?.addEventListener("click", () => setRevisionMode("conjugation"));
document.addEventListener("margin:open-revision", event => {
  const requested = event.detail?.mode;
  setRevisionMode(["grammar", "conjugation"].includes(requested) ? requested : "vocabulary");
  openRevision();
});
$("#revision-exercise-selector")?.addEventListener("change", event => {
  const selected = selectedRevisionExercises();
  if (!selected.size) {
    event.target.checked = true;
    return;
  }
  try {
    localStorage.setItem(EXERCISE_PREFERENCE_KEY, JSON.stringify([...selected]));
  } catch {
    // The selector still works for this session when storage is unavailable.
  }
  if (!view.hidden && $("#revision-language").value) loadRevisionSession();
});
document.addEventListener("margin:document-language", event => {
  const nextLanguage = event.detail?.language || "";
  if (normalize(nextLanguage) === normalize(documentLanguage)) return;
  documentLanguage = nextLanguage;
  if (documentLanguage && !view.hidden) {
    const select = $("#revision-language");
    if (![...select.options].some(option => normalize(option.value) === normalize(documentLanguage))) {
      select.add(new Option(languageName(documentLanguage), documentLanguage));
    }
    select.value = documentLanguage;
    loadRevisionSession();
  }
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !view.hidden) closeRevision();
});
document.addEventListener("margin:locale-changed", () => {
  $("#revision-title").textContent = t(revisionTitleKey());
  localizeRevisionLanguageOptions();
  if (currentCard?.exercise === "connector_cloze") {
    renderConnectorDirection();
  } else if (currentCard?.exercise === "synonym_matching") {
    renderMatchingDirection();
  } else if (currentCard) {
    renderCardDirection();
  }
  const prompt = $("#revision-prompt");
  const gender = [...NOUN_GENDERS].find(value => prompt?.classList.contains(`noun-${value}`));
  if (gender) setNounGender(prompt, gender);
  if (currentCard?.exercise === "letter_tiles") renderLetterTiles();
  updateProgress();
});

async function openRevision() {
  view.hidden = false;
  document.body.classList.add("revision-open");
  document.dispatchEvent(new CustomEvent("margin:revision-opened"));
  try {
    await populateLanguageSelector();
  } catch (error) {
    showRevisionError(error);
    return;
  }
  await loadRevisionSession();
}

function restoreRevisionExercisePreferences() {
  let selected = new Set(DEFAULT_EXERCISES);
  try {
    const stored = JSON.parse(localStorage.getItem(EXERCISE_PREFERENCE_KEY));
    if (Array.isArray(stored) && stored.some(value => DEFAULT_EXERCISES.includes(value))) {
      selected = new Set(stored);
    }
  } catch {
    // Retain the inclusive defaults when local storage is unavailable or invalid.
  }
  document.querySelectorAll("#revision-exercise-selector input").forEach(input => {
    input.checked = selected.has(input.value);
  });
}

function selectedRevisionExercises() {
  return new Set(
    [...document.querySelectorAll("#revision-exercise-selector input:checked")]
      .map(input => input.value),
  );
}

async function populateLanguageSelector() {
  const response = await fetch("/api/vocabulary/languages");
  const languages = await response.json();
  if (!response.ok) throw new Error(languages.detail || t("revision.languagesLoadError"));
  const select = $("#revision-language");
  select.replaceChildren(new Option(t("revision.selectLanguage"), ""));
  const choices = [...new Set([...languages, "German", "Spanish"])];
  if (documentLanguage && !choices.some(language => normalize(language) === normalize(documentLanguage))) {
    choices.push(documentLanguage);
  }
  choices.sort((left, right) => left.localeCompare(right));
  choices.forEach(language => select.add(new Option(languageName(language), language)));
  select.value = documentLanguage || "";
}

async function loadRevisionSession() {
  const loadingKey = revisionMode === "grammar"
    ? "grammar.generating"
    : revisionMode === "conjugation"
      ? "conjugation.preparing"
      : "revision.preparing";
  $("#revision-loading-copy").dataset.i18n = loadingKey;
  $("#revision-loading-copy").textContent = t(loadingKey);
  loading.hidden = false;
  empty.hidden = true;
  session.hidden = true;
  $("#grammar-session").hidden = true;
  $("#conjugation-session").hidden = true;
  queue = [];
  currentCard = null;
  answered = 0;
  correctAnswers = 0;
  removed = 0;
  synonymPairsAnswered = 0;
  synonymPairsFirstTry = 0;
  connectorAnswers = 0;
  connectorCorrectAnswers = 0;

  const language = $("#revision-language").value;
  if (!language) {
    loading.hidden = true;
    empty.hidden = false;
    $("#revision-empty-title").textContent = t("revision.chooseLanguage");
    $("#revision-empty-copy").textContent = t("revision.chooseLanguageCopy");
    return;
  }

  if (revisionMode === "grammar") {
    cancelConjugationRequests();
    try {
      await loadGrammarRevision(language);
      loading.hidden = true;
    } catch (error) {
      loading.hidden = true;
      if (error.name === "GrammarNotDueError") showEmptySession();
      else if (error.name !== "AbortError") showRevisionError(error);
    }
    return;
  }

  if (revisionMode === "conjugation") {
    cancelGrammarRequests();
    try {
      const focus = conjugationFocus;
      conjugationFocus = null;
      const available = await loadConjugationWorkout(
        language,
        focus ? { topicKeys: focus.topicKeys, limit: 8 } : {},
      );
      loading.hidden = true;
      if (!available) showEmptySession();
    } catch (error) {
      loading.hidden = true;
      if (error.name !== "AbortError") showRevisionError(error);
    }
    return;
  }

  cancelGrammarRequests();
  cancelConjugationRequests();

  try {
    const params = new URLSearchParams({
      language,
      limit: "40",
      supports_letter_tiles: "true",
    });
    const response = await fetch(`/api/revision/session?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || t("revision.loadError"));
    const exercises = selectedRevisionExercises();
    queue = exercises.has("vocabulary")
      ? data.cards.map(card => ({ ...card, retryCount: 0 }))
      : [];
    if (exercises.has("connectors")) queue.push(...(data.connector_cards || []));
    if (exercises.has("synonyms") && data.synonym_round) queue.push(data.synonym_round);
    loading.hidden = true;
    if (!queue.length) {
      showEmptySession();
      return;
    }
    session.hidden = false;
    renderNextCard();
  } catch (error) {
    showRevisionError(error);
  }
}

function showRevisionError(error) {
  loading.hidden = true;
  empty.hidden = false;
  session.hidden = true;
  $("#grammar-session").hidden = true;
  $("#conjugation-session").hidden = true;
  $("#revision-empty-title").textContent = t("revision.loadError");
  $("#revision-empty-copy").textContent = error.message;
}

function setRevisionMode(mode, reload = true, focus = null) {
  revisionMode = mode;
  conjugationFocus = mode === "conjugation" ? focus : null;
  const grammar = mode === "grammar";
  const conjugation = mode === "conjugation";
  const vocabulary = mode === "vocabulary";
  $("#revision-mode-vocabulary").classList.toggle("active", vocabulary);
  $("#revision-mode-vocabulary").setAttribute("aria-selected", String(vocabulary));
  $("#revision-mode-grammar").classList.toggle("active", grammar);
  $("#revision-mode-grammar").setAttribute("aria-selected", String(grammar));
  $("#revision-mode-conjugation").classList.toggle("active", conjugation);
  $("#revision-mode-conjugation").setAttribute("aria-selected", String(conjugation));
  $("#revision-exercise-selector").hidden = !vocabulary;
  $("#revision-title").textContent = t(revisionTitleKey());
  const select = $("#revision-language");
  [...select.options].forEach(option => {
    option.disabled = !vocabulary && option.value
      && !["german", "spanish"].includes(normalize(option.value));
  });
  if (!vocabulary && select.selectedOptions[0]?.disabled) select.value = "";
  if (reload && !view.hidden) loadRevisionSession();
}

function revisionTitleKey() {
  if (revisionMode === "grammar") return "grammar.title";
  if (revisionMode === "conjugation") return "conjugation.title";
  return "revision.title";
}

function closeRevision() {
  cancelGrammarRequests();
  cancelConjugationRequests();
  view.hidden = true;
  document.body.classList.remove("revision-open");
  document.dispatchEvent(new CustomEvent("margin:revision-closed"));
  document.dispatchEvent(new CustomEvent("margin:reviews-changed"));
}

function showEmptySession(finished = false) {
  session.hidden = true;
  empty.hidden = false;
  $("#revision-empty-title").textContent = t(finished ? "revision.sessionComplete" : "revision.nothingDue");
  if (!finished) {
    $("#revision-empty-copy").textContent = t("revision.caughtUp");
    return;
  }
  const summaries = [];
  if (answered) {
    summaries.push(t("revision.answers", { correct: correctAnswers, answered }));
  }
  if (synonymPairsAnswered) {
    summaries.push(t("revision.synonymRoundComplete", {
      correct: synonymPairsFirstTry,
      total: synonymPairsAnswered,
    }));
  }
  if (connectorAnswers) {
    summaries.push(t("revision.connectorAnswers", {
      correct: connectorCorrectAnswers,
      answered: connectorAnswers,
    }));
  }
  if (!summaries.length) summaries.push(t("revision.noAnswers"));
  const removalSummary = removed
    ? t(`revision.removal.${removed === 1 ? "one" : "other"}`, { count: removed })
    : "";
  if (removalSummary) summaries.push(removalSummary.trim());
  $("#revision-empty-copy").textContent = summaries.join(" ");
}

function renderNextCard() {
  $("#revision-feedback").hidden = true;
  $("#revision-matching").hidden = true;
  $("#revision-connector-hint").hidden = true;
  if (!queue.length) {
    currentCard = null;
    showEmptySession(true);
    return;
  }

  currentCard = queue.shift();
  if (currentCard.exercise === "connector_cloze") {
    renderConnectorCard();
    return;
  }
  if (currentCard.exercise === "synonym_matching") {
    renderSynonymMatchingRound();
    return;
  }
  $("#revision-card-actions").hidden = false;
  const sourceFirst = currentCard.direction === "source_to_translation";
  const category = t(`revision.category.${currentCard.category}`);
  const promptGender = sourceFirst
    ? nounGender(currentCard.prompt, currentCard.source_language, currentCard.noun_gender)
    : null;
  setNounGender(document.querySelector(".revision-card"), promptGender, false);
  renderCardDirection(category);
  const prompt = $("#revision-prompt");
  prompt.textContent = currentCard.prompt;
  setNounGender(prompt, null);
  const promptContext = $("#revision-prompt-context");
  const dictionaryForm = $("#revision-dictionary-form");
  const contextNeedle = [...String(
    currentCard.original_source || currentCard.normalized_source,
  ).split(/\s+/)].sort((left, right) => right.length - left.length)[0];
  const context = sentenceContaining(
    currentCard.context,
    contextNeedle,
  );
  if (sourceFirst && context) {
    renderHighlightedSentence(
      promptContext,
      context,
      [currentCard.original_source, currentCard.normalized_source],
    );
    promptContext.hidden = false;
    dictionaryForm.hidden = false;
    $("#revision-dictionary-value").textContent = currentCard.normalized_source;
    prompt.hidden = true;
  } else if (!sourceFirst && context && renderClozeSentence(
    promptContext,
    context,
    currentCard.original_source,
    t("revision.missingWord"),
  )) {
    promptContext.hidden = false;
    dictionaryForm.hidden = true;
    prompt.hidden = false;
  } else {
    promptContext.replaceChildren();
    promptContext.hidden = true;
    dictionaryForm.hidden = true;
    prompt.hidden = false;
  }
  const removeButton = $("#revision-remove");
  removeButton.dataset.itemId = currentCard.item_id;
  removeButton.dataset.prompt = currentCard.normalized_source || currentCard.prompt;
  removeButton.disabled = false;
  removeButton.textContent = t("revision.remove");
  $("#revision-action-error").textContent = "";
  updateProgress();

  const choices = $("#revision-choices");
  const recall = $("#revision-recall");
  const tiles = $("#revision-tiles");
  const recallAnswer = $("#revision-recall-answer");
  hintUsed = false;
  choices.replaceChildren();
  choices.hidden = currentCard.exercise !== "multiple_choice";
  recall.hidden = currentCard.exercise !== "typed_recall";
  tiles.hidden = currentCard.exercise !== "letter_tiles";
  recallAnswer.value = "";
  recallAnswer.disabled = false;
  recall.querySelector("button[type=submit]").disabled = false;
  recallAnswer.classList.remove("is-correct", "is-incorrect");
  updateRecallHintButton();
  currentCard.choices.forEach(choice => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "revision-choice";
    button.textContent = choice;
    setNounGender(
      button,
      sourceFirst
        ? null
        : nounGender(
            choice,
            currentCard.source_language,
            currentCard.choice_genders?.[choice],
          ),
    );
    button.addEventListener("click", () => submitAnswer(choice));
    choices.append(button);
  });
  if (currentCard.exercise === "letter_tiles") {
    setupLetterTiles(currentCard.normalized_source);
  }
  if (currentCard.exercise === "typed_recall") recallAnswer.focus();
}

function renderConnectorCard() {
  setNounGender(document.querySelector(".revision-card"), null, false);
  renderConnectorDirection();
  $("#revision-card-actions").hidden = true;
  $("#revision-dictionary-form").hidden = true;
  $("#revision-prompt").hidden = true;
  $("#revision-recall").hidden = true;
  $("#revision-tiles").hidden = true;
  $("#revision-matching").hidden = true;

  $("#revision-connector-hint").hidden = false;
  $("#revision-connector-meanings").textContent =
    currentCard.contextual_gloss || currentCard.glosses[0] || "";
  const context = $("#revision-prompt-context");
  renderConnectorSentence(context, currentCard, false);
  context.hidden = false;

  const choices = $("#revision-choices");
  choices.replaceChildren();
  choices.hidden = false;
  currentCard.choices.forEach(choice => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "revision-choice";
    button.textContent = choice;
    button.addEventListener("click", () => submitConnectorAnswer(choice));
    choices.append(button);
  });
  updateProgress();
}

function renderConnectorDirection() {
  const category = t(`revision.category.${currentCard.category}`);
  const types = currentCard.connector_categories
    .map(value => t(`revision.connectorCategory.${value}`))
    .join(" / ");
  $("#revision-direction").textContent = [
    languageName(currentCard.source_language),
    t("revision.connectorPractice"),
    types,
    category,
  ].join(" · ");
}

function renderConnectorSentence(element, card, reveal) {
  element.replaceChildren();
  const start = Math.max(0, Math.min(card.start_offset, card.sentence.length));
  const end = Math.max(start, Math.min(card.end_offset, card.sentence.length));
  element.append(document.createTextNode(card.sentence.slice(0, start)));
  if (reveal) {
    const mark = document.createElement("mark");
    mark.textContent = card.sentence.slice(start, end);
    element.append(mark);
  } else {
    const blank = document.createElement("span");
    blank.className = "revision-cloze revision-connector-cloze";
    blank.textContent = card.sentence.slice(start, end);
    blank.setAttribute("aria-label", t("revision.missingConnector"));
    element.append(blank);
  }
  element.append(document.createTextNode(card.sentence.slice(end)));
}

async function submitConnectorAnswer(selectedAnswer) {
  const card = currentCard;
  const buttons = [...document.querySelectorAll(".revision-choice")];
  buttons.forEach(button => { button.disabled = true; });
  try {
    const response = await fetch(
      `/api/revision/connectors/${encodeURIComponent(card.occurrence_id)}/answer`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selected_answer: selectedAnswer }),
      },
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || t("revision.answerSaveError"));
    connectorAnswers += 1;
    if (data.correct) connectorCorrectAnswers += 1;
    buttons.forEach(button => {
      if (normalize(button.textContent) === normalize(data.correct_answer)) {
        button.classList.add("is-correct");
      } else if (button.textContent === selectedAnswer) {
        button.classList.add("is-incorrect");
      }
    });
    $("#revision-feedback-title").textContent = data.correct
      ? t("revision.correct")
      : t("revision.incorrect", { answer: data.correct_answer });
    renderConnectorSentence($("#revision-prompt-context"), card, true);
    $("#revision-choices").hidden = true;
    $("#revision-context").replaceChildren();
    $("#revision-context").hidden = true;
    $("#revision-feedback-dictionary").hidden = true;
    $("#revision-feedback").hidden = false;
    currentCard = null;
    updateProgress();
  } catch (error) {
    buttons.forEach(button => { button.disabled = false; });
    $("#revision-feedback-title").textContent = error.message;
    $("#revision-context").hidden = true;
    $("#revision-feedback-dictionary").hidden = true;
    $("#revision-feedback").hidden = false;
  }
}

function renderSynonymMatchingRound() {
  setNounGender(document.querySelector(".revision-card"), null, false);
  renderMatchingDirection();
  $("#revision-prompt-context").hidden = true;
  $("#revision-dictionary-form").hidden = true;
  $("#revision-prompt").hidden = true;
  $("#revision-card-actions").hidden = true;
  $("#revision-choices").hidden = true;
  $("#revision-recall").hidden = true;
  $("#revision-tiles").hidden = true;
  $("#revision-matching").hidden = false;
  $("#revision-matching-status").textContent = "";

  matchingPairs = new Map(currentCard.pairs.map(pair => [pair.item_id, pair]));
  matchedPairIds = new Set();
  missedPairIds = new Set();
  selectedMatchingSource = null;
  selectedMatchingSynonym = null;

  const sources = [...currentCard.pairs];
  const synonyms = [...currentCard.pairs];
  shuffle(sources);
  shuffle(synonyms);
  renderMatchingOptions("source", sources, $("#revision-matching-sources"));
  renderMatchingOptions("synonym", synonyms, $("#revision-matching-synonyms"));
  updateProgress();
}

function renderMatchingDirection() {
  $("#revision-direction").textContent = [
    languageName(currentCard.source_language),
    t("revision.synonymMatching"),
  ].join(" · ");
}

function renderMatchingOptions(side, pairs, container) {
  container.replaceChildren();
  pairs.forEach(pair => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "revision-matching-option";
    button.dataset.pairId = pair.item_id;
    button.dataset.side = side;
    button.setAttribute("aria-pressed", "false");
    button.textContent = side === "source" ? pair.normalized_source : pair.synonym;
    setNounGender(
      button,
      side === "source" ? pair.noun_gender : pair.synonym_gender,
    );
    button.addEventListener("click", () => selectMatchingOption(button));
    container.append(button);
  });
}

function selectMatchingOption(button) {
  const side = button.dataset.side;
  const pairId = button.dataset.pairId;
  const selectedId = side === "source"
    ? selectedMatchingSource
    : selectedMatchingSynonym;
  document.querySelectorAll(`.revision-matching-option[data-side="${side}"]`)
    .forEach(option => {
      option.classList.remove("is-selected");
      option.setAttribute("aria-pressed", "false");
    });
  const nextId = selectedId === pairId ? null : pairId;
  if (side === "source") selectedMatchingSource = nextId;
  else selectedMatchingSynonym = nextId;
  if (nextId) {
    button.classList.add("is-selected");
    button.setAttribute("aria-pressed", "true");
  }
  if (selectedMatchingSource && selectedMatchingSynonym) checkMatchingPair();
}

function checkMatchingPair() {
  const sourceId = selectedMatchingSource;
  const synonymId = selectedMatchingSynonym;
  const sourceButton = matchingButton("source", sourceId);
  const synonymButton = matchingButton("synonym", synonymId);
  sourceButton.classList.remove("is-selected");
  synonymButton.classList.remove("is-selected");
  sourceButton.setAttribute("aria-pressed", "false");
  synonymButton.setAttribute("aria-pressed", "false");
  selectedMatchingSource = null;
  selectedMatchingSynonym = null;

  if (sourceId === synonymId) {
    matchedPairIds.add(sourceId);
    synonymPairsAnswered += 1;
    if (!missedPairIds.has(sourceId)) synonymPairsFirstTry += 1;
    sourceButton.classList.add("is-matched");
    synonymButton.classList.add("is-matched");
    sourceButton.disabled = true;
    synonymButton.disabled = true;
    $("#revision-matching-status").textContent = t("revision.matchingCorrect");
    updateProgress();
    if (matchedPairIds.size === matchingPairs.size) finishSynonymMatchingRound();
    return;
  }

  missedPairIds.add(sourceId);
  sourceButton.classList.add("is-incorrect");
  synonymButton.classList.add("is-incorrect");
  $("#revision-matching-status").textContent = t("revision.matchingIncorrect");
  setTimeout(() => {
    sourceButton.classList.remove("is-incorrect");
    synonymButton.classList.remove("is-incorrect");
  }, 500);
}

function matchingButton(side, pairId) {
  return [...document.querySelectorAll(
    `.revision-matching-option[data-side="${side}"]`,
  )].find(button => button.dataset.pairId === pairId);
}

function finishSynonymMatchingRound() {
  const total = matchingPairs.size;
  const roundFirstTry = [...matchingPairs.keys()]
    .filter(pairId => !missedPairIds.has(pairId)).length;
  $("#revision-feedback-title").textContent = t("revision.synonymRoundComplete", {
    correct: roundFirstTry,
    total,
  });
  $("#revision-context").hidden = true;
  $("#revision-feedback-dictionary").hidden = true;
  $("#revision-feedback").hidden = false;
  currentCard = null;
  updateProgress();
}

function setupLetterTiles(answer) {
  tilePattern = graphemes(answer).map(value => ({
    value,
    selectable: /[\p{L}\p{N}]/u.test(value),
  }));
  tileOptions = tilePattern
    .map((entry, index) => ({ ...entry, id: String(index) }))
    .filter(entry => entry.selectable);
  shuffle(tileOptions);
  selectedTileIds = [];
  tilesLocked = false;
  $("#revision-tile-answer").classList.remove("is-correct", "is-incorrect");
  renderLetterTiles();
}

function graphemes(value) {
  if (typeof Intl.Segmenter === "function") {
    return [...new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(value)]
      .map(segment => segment.segment);
  }
  return Array.from(value);
}

function shuffle(values) {
  for (let index = values.length - 1; index > 0; index -= 1) {
    const other = Math.floor(Math.random() * (index + 1));
    [values[index], values[other]] = [values[other], values[index]];
  }
}

function renderLetterTiles() {
  const optionsById = new Map(tileOptions.map(option => [option.id, option]));
  const selected = new Set(selectedTileIds);
  const answer = $("#revision-tile-answer");
  const pool = $("#revision-tile-pool");
  const controls = document.querySelector(".revision-tile-controls");
  answer.replaceChildren();
  pool.replaceChildren();

  let selectedIndex = 0;
  tilePattern.forEach(entry => {
    if (!entry.selectable) {
      const separator = document.createElement("span");
      separator.className = "revision-tile-separator";
      separator.textContent = /\s/u.test(entry.value) ? "\u00a0" : entry.value;
      answer.append(separator);
      return;
    }

    const tileId = selectedTileIds[selectedIndex];
    const option = optionsById.get(tileId);
    if (option) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "revision-letter-tile is-selected";
      button.textContent = option.value;
      button.disabled = tilesLocked;
      button.setAttribute("aria-label", t("revision.removeLetter", { letter: option.value }));
      const removeAt = selectedIndex;
      button.addEventListener("click", () => {
        selectedTileIds.splice(removeAt, 1);
        renderLetterTiles();
      });
      answer.append(button);
      selectedIndex += 1;
      return;
    }

    const blank = document.createElement("span");
    blank.className = "revision-letter-blank";
    blank.setAttribute("aria-hidden", "true");
    answer.append(blank);
  });

  const remainingOptions = tileOptions.filter(option => !selected.has(option.id));
  pool.hidden = !remainingOptions.length || tilesLocked;
  controls.hidden = tilesLocked;
  remainingOptions.forEach(option => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "revision-letter-tile";
    button.textContent = option.value;
    button.disabled = tilesLocked;
    button.setAttribute("aria-label", t("revision.addLetter", { letter: option.value }));
    button.addEventListener("click", () => {
      selectedTileIds.push(option.id);
      renderLetterTiles();
    });
    pool.append(button);
  });

  $("#revision-tile-clear").disabled = tilesLocked || !selectedTileIds.length;
  $("#revision-tile-hint").disabled = tilesLocked || (
    selectedTileIds.length === tileOptions.length
    && normalize(tileAnswer()) === normalize(currentCard.hint_answer)
  );
  $("#revision-tile-check").disabled = tilesLocked
    || selectedTileIds.length !== tileOptions.length;
}

function matchingPrefixLength(values, expected) {
  let length = 0;
  while (
    length < values.length
    && length < expected.length
    && values[length].toLocaleLowerCase() === expected[length].toLocaleLowerCase()
  ) length += 1;
  return length;
}

function revealTypedHint() {
  const input = $("#revision-recall-answer");
  const expected = graphemes(currentCard.hint_answer);
  const entered = graphemes(input.value);
  if (normalize(input.value) === normalize(currentCard.hint_answer)) return;
  const prefixLength = matchingPrefixLength(entered, expected);
  input.value = expected.slice(0, Math.min(prefixLength + 1, expected.length)).join("");
  hintUsed = true;
  input.focus();
  updateRecallHintButton();
}

function updateRecallHintButton() {
  const button = $("#revision-recall-hint");
  const input = $("#revision-recall-answer");
  if (!button || !input) return;
  button.disabled = input.disabled || !currentCard?.hint_answer
    || normalize(input.value) === normalize(currentCard.hint_answer);
}

function revealTileHint() {
  const optionsById = new Map(tileOptions.map(option => [option.id, option]));
  const expectedIds = tilePattern
    .map((entry, index) => entry.selectable ? String(index) : null)
    .filter(value => value !== null);
  const selectedValues = selectedTileIds.map(id => optionsById.get(id)?.value || "");
  const expectedValues = expectedIds.map(id => optionsById.get(id).value);
  const prefixLength = matchingPrefixLength(selectedValues, expectedValues);
  if (prefixLength >= expectedIds.length) return;
  selectedTileIds = [
    ...selectedTileIds.slice(0, prefixLength),
    expectedIds[prefixLength],
  ];
  hintUsed = true;
  renderLetterTiles();
}

function tileAnswer() {
  const optionsById = new Map(tileOptions.map(option => [option.id, option]));
  let selectedIndex = 0;
  return tilePattern.map(entry => {
    if (!entry.selectable) return entry.value;
    const value = optionsById.get(selectedTileIds[selectedIndex])?.value || "";
    selectedIndex += 1;
    return value;
  }).join("");
}

function setTileControlsDisabled(disabled) {
  tilesLocked = disabled;
  renderLetterTiles();
}

async function removeCurrentCard() {
  const button = $("#revision-remove");
  const itemId = button.dataset.itemId;
  if (!itemId) return;
  const prompt = button.dataset.prompt || t("revision.thisWord");
  if (!window.confirm(t("revision.confirmRemove", { word: prompt }))) return;

  const choiceButtons = [...document.querySelectorAll(".revision-choice")];
  const recallAnswer = $("#revision-recall-answer");
  const recallButton = $("#revision-recall button[type=submit]");
  button.disabled = true;
  choiceButtons.forEach(choice => { choice.disabled = true; });
  recallAnswer.disabled = true;
  recallButton.disabled = true;
  $("#revision-recall-hint").disabled = true;
  setTileControlsDisabled(true);
  $("#revision-action-error").textContent = "";
  try {
    const response = await fetch(`/api/vocabulary/${encodeURIComponent(itemId)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || t("revision.removeError"));
    }

    queue = queue.filter(card => card.item_id !== itemId);
    removed += 1;
    document.dispatchEvent(new CustomEvent("margin:vocabulary-removed", {
      detail: { itemId },
    }));
    if (currentCard?.item_id === itemId) {
      currentCard = null;
      renderNextCard();
    } else {
      button.textContent = t("revision.removed");
      updateProgress();
    }
  } catch (error) {
    button.disabled = false;
    if (currentCard) {
      choiceButtons.forEach(choice => { choice.disabled = false; });
      recallAnswer.disabled = false;
      recallButton.disabled = false;
      setTileControlsDisabled(false);
      updateRecallHintButton();
    }
    $("#revision-action-error").textContent = error.message;
  }
}

async function submitAnswer(selectedAnswer) {
  const buttons = [...document.querySelectorAll(".revision-choice")];
  const recallAnswer = $("#revision-recall-answer");
  const recallButton = $("#revision-recall button[type=submit]");
  const removeButton = $("#revision-remove");
  buttons.forEach(button => { button.disabled = true; });
  recallAnswer.disabled = true;
  recallButton.disabled = true;
  $("#revision-recall-hint").disabled = true;
  setTileControlsDisabled(true);
  removeButton.disabled = true;
  try {
    const response = await fetch(`/api/revision/${encodeURIComponent(currentCard.item_id)}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        direction: currentCard.direction,
        selected_answer: selectedAnswer,
        hint_used: hintUsed,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || t("revision.answerSaveError"));

    answered += 1;
    if (data.correct) correctAnswers += 1;
    if (!data.correct && currentCard.retryCount < 2) {
      const retryAt = Math.min(5, queue.length);
      queue.splice(retryAt, 0, { ...currentCard, retryCount: currentCard.retryCount + 1 });
    }

    buttons.forEach(button => {
      if (normalize(button.textContent) === normalize(data.correct_answer)) {
        button.classList.add("is-correct");
      } else if (button.textContent === selectedAnswer) {
        button.classList.add("is-incorrect");
      }
    });
    if (currentCard.exercise === "typed_recall") {
      recallAnswer.classList.add(data.correct ? "is-correct" : "is-incorrect");
    } else if (currentCard.exercise === "letter_tiles") {
      $("#revision-tile-answer").classList.add(
        data.correct ? "is-correct" : "is-incorrect",
      );
    }
    $("#revision-feedback-title").textContent = hintUsed
      ? t("revision.hintNotCounted", { answer: data.correct_answer })
      : data.correct
        ? t("revision.correct")
        : t("revision.incorrect", { answer: data.correct_answer });
    renderVocabularyFeedbackContext(currentCard);
    $("#revision-feedback-dictionary").hidden = false;
    $("#revision-feedback-dictionary-value").textContent = data.item.normalized_source;
    $("#revision-feedback").hidden = false;
    currentCard = null;
    removeButton.disabled = false;
    updateProgress();
  } catch (error) {
    buttons.forEach(button => { button.disabled = false; });
    recallAnswer.disabled = false;
    recallButton.disabled = false;
    setTileControlsDisabled(false);
    updateRecallHintButton();
    removeButton.disabled = false;
    $("#revision-feedback-title").textContent = error.message;
    $("#revision-context").textContent = "";
    $("#revision-context").hidden = true;
    $("#revision-feedback-dictionary").hidden = true;
    $("#revision-feedback").hidden = false;
  }
}

function renderVocabularyFeedbackContext(card) {
  const element = $("#revision-context");
  element.replaceChildren();
  element.hidden = true;
  if (card.direction !== "translation_to_source") return;

  const surfaceForm = card.original_source || card.normalized_source;
  const contextNeedle = [...String(surfaceForm).split(/\s+/)]
    .sort((left, right) => right.length - left.length)[0];
  const context = sentenceContaining(card.context, contextNeedle);
  if (!context) return;

  renderHighlightedSentence(element, context, [surfaceForm]);
  element.hidden = false;
}

function updateProgress() {
  if (currentCard?.exercise === "synonym_matching") {
    $("#revision-progress-text").textContent = t("revision.matchingProgress", {
      matched: matchedPairIds.size,
      total: matchingPairs.size,
    });
    $("#revision-score").textContent = t("revision.synonymScore", {
      count: synonymPairsFirstTry,
    });
    return;
  }
  const remaining = queue.length + (currentCard ? 1 : 0);
  $("#revision-progress-text").textContent = t("revision.progress", { answered, remaining });
  const score = answered ? t("revision.score", { count: correctAnswers }) : "";
  const synonymScore = synonymPairsAnswered
    ? t("revision.synonymScore", { count: synonymPairsFirstTry })
    : "";
  const connectorScore = connectorAnswers
    ? t("revision.connectorScore", { count: connectorCorrectAnswers })
    : "";
  const removals = removed ? t("revision.removedCount", { count: removed }) : "";
  $("#revision-score").textContent = [score, connectorScore, synonymScore, removals]
    .filter(Boolean).join(" · ");
}

function renderCardDirection(category = null) {
  if (!currentCard) return;
  const sourceFirst = currentCard.direction === "source_to_translation";
  const label = category || t(`revision.category.${currentCard.category}`);
  const source = languageName(currentCard.source_language);
  const target = languageName(currentCard.target_language);
  $("#revision-direction").textContent = sourceFirst
    ? `${source} → ${target} · ${label}`
    : `${target} → ${source} · ${label}`;
}

function localizeRevisionLanguageOptions() {
  const select = $("#revision-language");
  if (!select) return;
  [...select.options].forEach(option => {
    option.textContent = option.value ? languageName(option.value) : t("revision.selectLanguage");
  });
}

function normalize(value) {
  return value.normalize("NFKC").trim().toLocaleLowerCase().replace(/\s+/g, " ");
}

function finishGrammarRevision(summary) {
  answered = summary.answered;
  correctAnswers = summary.correct;
  $("#grammar-session").hidden = true;
  showEmptySession(true);
}

function finishConjugationWorkout(summary) {
  answered = summary.answered;
  correctAnswers = summary.correct;
  $("#conjugation-session").hidden = true;
  showEmptySession(true);
}

function startFocusedConjugationWorkout(details) {
  setRevisionMode("conjugation", true, details);
}

restoreRevisionExercisePreferences();
initializeGrammarRevision(
  loadRevisionSession,
  finishGrammarRevision,
  startFocusedConjugationWorkout,
);
initializeConjugationWorkout(finishConjugationWorkout);
