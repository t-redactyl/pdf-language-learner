import { t } from "./i18n.js?v=26";

const $ = selector => document.querySelector(selector);
let queue = [];
let current = null;
let totalPlanned = 0;
let answered = 0;
let correct = 0;
let retryCounts = new Map();
let controller = null;
let finishCurrent = null;


export function initializeConjugationWorkout(finish) {
  finishCurrent = finish;
  $("#conjugation-answer-form")?.addEventListener("submit", event => {
    event.preventDefault();
    const answer = $("#conjugation-answer").value.trim();
    if (answer) submitAnswer(answer);
  });
  $("#conjugation-continue")?.addEventListener("click", renderNext);
}


export function cancelConjugationRequests() {
  controller?.abort();
  controller = null;
}


export async function loadConjugationWorkout(language, options = {}) {
  cancelConjugationRequests();
  controller = new AbortController();
  const activeController = controller;
  try {
    const params = new URLSearchParams({
      language,
      limit: String(options.limit || 20),
    });
    if (options.topicKeys?.length) params.set("topics", options.topicKeys.join(","));
    const response = await fetch(`/api/conjugation/session?${params}`, {
      signal: activeController.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || t("conjugation.loadError"));
    queue = data.cards.map(card => ({ ...card }));
    totalPlanned = queue.length;
    answered = 0;
    correct = 0;
    retryCounts = new Map();
    if (!queue.length) return false;
    $("#conjugation-session").hidden = false;
    renderNext();
    return true;
  } finally {
    if (controller === activeController) controller = null;
  }
}


function renderNext() {
  if (!queue.length) {
    current = null;
    $("#conjugation-session").hidden = true;
    finishCurrent({ answered, correct });
    return;
  }
  current = queue.shift();
  $("#conjugation-feedback").hidden = true;
  $("#conjugation-answer-form").hidden = false;
  $("#conjugation-answer").value = "";
  $("#conjugation-answer").disabled = false;
  $("#conjugation-answer-form button").disabled = false;
  $("#conjugation-topic").textContent = `${current.level} · ${current.topic}`;
  $("#conjugation-lemma").textContent = current.lemma;
  $("#conjugation-form").textContent = current.form;
  const personCue = $("#conjugation-person-cue");
  personCue.hidden = false;
  $("#conjugation-person").textContent = current.person || "—";
  updateProgress();
  $("#conjugation-answer").focus();
}


function updateProgress() {
  $("#conjugation-progress").textContent = t("conjugation.progress", {
    current: Math.min(answered + 1, totalPlanned),
    total: totalPlanned,
  });
  $("#conjugation-score").textContent = t("revision.score", { count: correct });
}


async function submitAnswer(answer) {
  const form = $("#conjugation-answer-form");
  form.querySelectorAll("input, button").forEach(control => { control.disabled = true; });
  const activeCard = current;
  try {
    const response = await fetch(`/api/conjugation/items/${encodeURIComponent(activeCard.key)}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || t("revision.answerSaveError"));
    answered += 1;
    correct += Number(result.correct);
    if (!result.correct && (retryCounts.get(activeCard.key) || 0) < 1) {
      retryCounts.set(activeCard.key, 1);
      queue.splice(Math.min(2, queue.length), 0, activeCard);
      totalPlanned += 1;
    }
    $("#conjugation-feedback-title").textContent = t(
      result.correct ? "conjugation.correct" : "conjugation.incorrect"
    );
    $("#conjugation-reference").textContent = result.reference_answer;
    $("#conjugation-note").textContent = activeCard.note || "";
    form.hidden = true;
    $("#conjugation-feedback").hidden = false;
    updateProgress();
    $("#conjugation-continue").focus();
  } catch (error) {
    form.querySelectorAll("input, button").forEach(control => { control.disabled = false; });
    $("#conjugation-feedback-title").textContent = error.message;
    $("#conjugation-reference").textContent = "";
    $("#conjugation-note").textContent = "";
    $("#conjugation-feedback").hidden = false;
  }
}
