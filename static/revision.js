import { renderHighlightedSentence, sentenceContaining } from "./text.js";
import { languageName, t } from "./i18n.js?v=2";

const $ = selector => document.querySelector(selector);

const view = $("#revision-view");
const loading = $("#revision-loading");
const empty = $("#revision-empty");
const session = $("#revision-session");
let queue = [];
let currentCard = null;
let answered = 0;
let correctAnswers = 0;
let removed = 0;
let documentLanguage = "";
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
$("#revision-language")?.addEventListener("change", loadRevisionSession);
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
  localizeRevisionLanguageOptions();
  if (currentCard) renderCardDirection();
  const prompt = $("#revision-prompt");
  const gender = [...NOUN_GENDERS].find(value => prompt?.classList.contains(`noun-${value}`));
  if (gender) setNounGender(prompt, gender);
  updateProgress();
});

async function openRevision() {
  view.hidden = false;
  document.body.classList.add("revision-open");
  try {
    await populateLanguageSelector();
  } catch (error) {
    showRevisionError(error);
    return;
  }
  await loadRevisionSession();
}

async function populateLanguageSelector() {
  const response = await fetch("/api/vocabulary/languages");
  const languages = await response.json();
  if (!response.ok) throw new Error(languages.detail || t("revision.languagesLoadError"));
  const select = $("#revision-language");
  select.replaceChildren(new Option(t("revision.selectLanguage"), ""));
  const choices = [...languages];
  if (documentLanguage && !choices.some(language => normalize(language) === normalize(documentLanguage))) {
    choices.push(documentLanguage);
  }
  choices.sort((left, right) => left.localeCompare(right));
  choices.forEach(language => select.add(new Option(languageName(language), language)));
  select.value = documentLanguage || "";
}

async function loadRevisionSession() {
  loading.hidden = false;
  empty.hidden = true;
  session.hidden = true;
  queue = [];
  currentCard = null;
  answered = 0;
  correctAnswers = 0;
  removed = 0;

  const language = $("#revision-language").value;
  if (!language) {
    loading.hidden = true;
    empty.hidden = false;
    $("#revision-empty-title").textContent = t("revision.chooseLanguage");
    $("#revision-empty-copy").textContent = t("revision.chooseLanguageCopy");
    return;
  }

  try {
    const params = new URLSearchParams({ language, limit: "40" });
    const response = await fetch(`/api/revision/session?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || t("revision.loadError"));
    queue = data.cards.map(card => ({ ...card, retryCount: 0 }));
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
  $("#revision-empty-title").textContent = t("revision.loadError");
  $("#revision-empty-copy").textContent = error.message;
}

function closeRevision() {
  view.hidden = true;
  document.body.classList.remove("revision-open");
}

function showEmptySession(finished = false) {
  session.hidden = true;
  empty.hidden = false;
  $("#revision-empty-title").textContent = t(finished ? "revision.sessionComplete" : "revision.nothingDue");
  if (!finished) {
    $("#revision-empty-copy").textContent = t("revision.caughtUp");
    return;
  }
  const answerSummary = answered
    ? t("revision.answers", { correct: correctAnswers, answered })
    : t("revision.noAnswers");
  const removalSummary = removed
    ? t(`revision.removal.${removed === 1 ? "one" : "other"}`, { count: removed })
    : "";
  $("#revision-empty-copy").textContent = answerSummary + removalSummary;
}

function renderNextCard() {
  $("#revision-feedback").hidden = true;
  if (!queue.length) {
    currentCard = null;
    showEmptySession(true);
    return;
  }

  currentCard = queue.shift();
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
  const removeButton = $("#revision-remove");
  removeButton.dataset.itemId = currentCard.item_id;
  removeButton.dataset.prompt = currentCard.prompt;
  removeButton.disabled = false;
  removeButton.textContent = t("revision.remove");
  $("#revision-action-error").textContent = "";
  updateProgress();

  const choices = $("#revision-choices");
  const recall = $("#revision-recall");
  const recallAnswer = $("#revision-recall-answer");
  choices.replaceChildren();
  choices.hidden = currentCard.exercise !== "multiple_choice";
  recall.hidden = currentCard.exercise !== "typed_recall";
  recallAnswer.value = "";
  recallAnswer.disabled = false;
  recall.querySelector("button[type=submit]").disabled = false;
  recallAnswer.classList.remove("is-correct", "is-incorrect");
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
  if (currentCard.exercise === "typed_recall") recallAnswer.focus();
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
  removeButton.disabled = true;
  try {
    const response = await fetch(`/api/revision/${encodeURIComponent(currentCard.item_id)}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        direction: currentCard.direction,
        selected_answer: selectedAnswer,
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
    }
    $("#revision-feedback-title").textContent = data.correct
      ? t("revision.correct")
      : t("revision.incorrect", { answer: data.correct_answer });
    const context = sentenceContaining(
      data.item.context,
      data.item.original_source || data.item.normalized_source,
    );
    renderHighlightedSentence(
      $("#revision-context"),
      context,
      [data.item.original_source, data.item.normalized_source],
      t("revision.fromText"),
    );
    $("#revision-feedback").hidden = false;
    currentCard = null;
    removeButton.disabled = false;
    updateProgress();
  } catch (error) {
    buttons.forEach(button => { button.disabled = false; });
    recallAnswer.disabled = false;
    recallButton.disabled = false;
    removeButton.disabled = false;
    $("#revision-feedback-title").textContent = error.message;
    $("#revision-context").textContent = "";
    $("#revision-feedback").hidden = false;
  }
}

function updateProgress() {
  const remaining = queue.length + (currentCard ? 1 : 0);
  $("#revision-progress-text").textContent = t("revision.progress", { answered, remaining });
  const score = answered ? t("revision.score", { count: correctAnswers }) : "";
  const removals = removed ? t("revision.removedCount", { count: removed }) : "";
  $("#revision-score").textContent = [score, removals].filter(Boolean).join(" · ");
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
