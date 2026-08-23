import { renderHighlightedSentence, sentenceContaining } from "./text.js";

const $ = selector => document.querySelector(selector);

const view = $("#revision-view");
const loading = $("#revision-loading");
const empty = $("#revision-empty");
const session = $("#revision-session");
let queue = [];
let currentCard = null;
let answered = 0;
let correctAnswers = 0;

$("#open-revision")?.addEventListener("click", openRevision);
$("#close-revision")?.addEventListener("click", closeRevision);
$("#revision-continue")?.addEventListener("click", renderNextCard);
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !view.hidden) closeRevision();
});

async function openRevision() {
  view.hidden = false;
  document.body.classList.add("revision-open");
  loading.hidden = false;
  empty.hidden = true;
  session.hidden = true;
  queue = [];
  currentCard = null;
  answered = 0;
  correctAnswers = 0;

  try {
    const response = await fetch("/api/revision/session?limit=40");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Revision could not be loaded");
    queue = data.cards.map(card => ({ ...card, retryCount: 0 }));
    loading.hidden = true;
    if (!queue.length) {
      showEmptySession();
      return;
    }
    session.hidden = false;
    renderNextCard();
  } catch (error) {
    loading.hidden = true;
    empty.hidden = false;
    $("#revision-empty-title").textContent = "Revision could not be loaded";
    $("#revision-empty-copy").textContent = error.message;
  }
}

function closeRevision() {
  view.hidden = true;
  document.body.classList.remove("revision-open");
}

function showEmptySession(finished = false) {
  session.hidden = true;
  empty.hidden = false;
  $("#revision-empty-title").textContent = finished ? "Session complete" : "Nothing due right now";
  $("#revision-empty-copy").textContent = finished
    ? `${correctAnswers} of ${answered} answers were correct.`
    : "You are caught up, or need at least two saved words in the same language pair to make a quiz.";
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
  const category = currentCard.category.replaceAll("_", " ");
  $("#revision-direction").textContent = sourceFirst
    ? `${currentCard.source_language} → ${currentCard.target_language} · ${category}`
    : `${currentCard.target_language} → ${currentCard.source_language} · ${category}`;
  $("#revision-prompt").textContent = currentCard.prompt;
  updateProgress();

  const choices = $("#revision-choices");
  choices.replaceChildren();
  currentCard.choices.forEach(choice => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "revision-choice";
    button.textContent = choice;
    button.addEventListener("click", () => submitAnswer(choice));
    choices.append(button);
  });
}

async function submitAnswer(selectedAnswer) {
  const buttons = [...document.querySelectorAll(".revision-choice")];
  buttons.forEach(button => { button.disabled = true; });
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
    if (!response.ok) throw new Error(data.detail || "Answer could not be saved");

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
    $("#revision-feedback-title").textContent = data.correct
      ? "Correct"
      : `Not quite — the answer is ${data.correct_answer}.`;
    const context = sentenceContaining(
      data.item.context,
      data.item.original_source || data.item.normalized_source,
    );
    renderHighlightedSentence(
      $("#revision-context"),
      context,
      [data.item.original_source, data.item.normalized_source],
      "From the text: ",
    );
    $("#revision-feedback").hidden = false;
    currentCard = null;
    updateProgress();
  } catch (error) {
    buttons.forEach(button => { button.disabled = false; });
    $("#revision-feedback-title").textContent = error.message;
    $("#revision-context").textContent = "";
    $("#revision-feedback").hidden = false;
  }
}

function updateProgress() {
  const remaining = queue.length + (currentCard ? 1 : 0);
  $("#revision-progress-text").textContent = `${answered} answered · ${remaining} remaining`;
  $("#revision-score").textContent = answered ? `${correctAnswers} correct` : "";
}

function normalize(value) {
  return value.normalize("NFKC").trim().toLocaleLowerCase().replace(/\s+/g, " ");
}
