import { t } from "./i18n.js?v=24";

const $ = selector => document.querySelector(selector);
let activeSession = null;
let selectedTokens = [];
let orderingTokens = [];
let loadCurrent = null;
let finishCurrent = null;
let sessionLoadController = null;
let answerController = null;
const summaryControllers = new Set();
let continuationPending = false;
let completedSessionSummary = null;
const GRAMMAR_REQUEST_TIMEOUT_MS = 190_000;

async function grammarFetch(url, options = {}, controller) {
  let timedOut = false;
  const timeout = window.setTimeout(
    () => {
      timedOut = true;
      controller.abort();
    },
    GRAMMAR_REQUEST_TIMEOUT_MS,
  );
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const data = await response.json();
    return { response, data };
  } catch (error) {
    if (timedOut) {
      const timeoutError = new Error(t("grammar.requestTimeout"));
      timeoutError.name = "TimeoutError";
      throw timeoutError;
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export function cancelGrammarRequests() {
  sessionLoadController?.abort();
  answerController?.abort();
  summaryControllers.forEach(controller => controller.abort());
  summaryControllers.clear();
  sessionLoadController = null;
  answerController = null;
  continuationPending = false;
  completedSessionSummary = null;
}

export function initializeGrammarRevision(reload, finish) {
  loadCurrent = reload;
  finishCurrent = finish;
  $("#grammar-answer-form")?.addEventListener("submit", event => {
    event.preventDefault();
    const answer = $("#grammar-answer").value.trim();
    if (answer) submitGrammarAnswer(answer);
  });
  $("#grammar-order-clear")?.addEventListener("click", () => {
    selectedTokens = [];
    renderOrdering();
  });
  $("#grammar-order-check")?.addEventListener("click", () => {
    if (selectedTokens.length) submitGrammarAnswer(orderingAnswer());
  });
  $("#grammar-continue")?.addEventListener("click", async event => {
    if (continuationPending) return;
    if (completedSessionSummary) {
      const summary = completedSessionSummary;
      completedSessionSummary = null;
      finishCurrent(summary);
      return;
    }
    const button = event.currentTarget;
    continuationPending = true;
    button.disabled = true;
    button.textContent = t("grammar.loadingNext");
    try {
      await loadCurrent();
    } finally {
      continuationPending = false;
      button.disabled = false;
    }
  });
}

export async function loadGrammarRevision(language) {
  sessionLoadController?.abort();
  completedSessionSummary = null;
  const controller = new AbortController();
  sessionLoadController = controller;
  $("#grammar-session").hidden = true;
  try {
    const { response, data } = await grammarFetch("/api/grammar/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language }),
    }, controller);
    if (!response.ok) throw new Error(data.detail || t("grammar.loadError"));
    if (controller.signal.aborted) return;
    activeSession = data;
    renderSession();
  } finally {
    if (sessionLoadController === controller) sessionLoadController = null;
  }
}

function renderSession() {
  const exercise = activeSession.exercise;
  $("#grammar-session").hidden = false;
  $("#grammar-progress").textContent = t("grammar.progress", {
    current: Math.min(activeSession.answered + 1, activeSession.total),
    total: activeSession.total,
  });
  $("#grammar-score").textContent = t("revision.score", { count: activeSession.correct });
  $("#grammar-session-kind").textContent = t(`grammar.kind.${activeSession.kind}`);
  renderTopicHeading();
  const lesson = $("#grammar-lesson");
  lesson.hidden = activeSession.kind === "review";
  $("#grammar-rule-summary").replaceChildren(
    ...ruleSummaryPoints(activeSession.rule_summary).map(point => {
      const item = document.createElement("li");
      item.textContent = point;
      return item;
    }),
  );
  $("#grammar-rule-tables").replaceChildren(
    ...(activeSession.rule_tables || []).map(renderRuleTable),
  );
  $("#grammar-examples").replaceChildren(...activeSession.worked_examples.map(example => {
    const item = document.createElement("li");
    item.textContent = example;
    return item;
  }));
  $("#grammar-feedback").hidden = true;
  $("#grammar-exercise").hidden = !exercise;
  if (!exercise) return;
  $("#grammar-instruction").textContent = exercise.instruction;
  $("#grammar-prompt").textContent = exercise.prompt;
  document.querySelectorAll("#grammar-exercise button, #grammar-exercise input").forEach(control => {
    control.disabled = false;
  });
  const choices = $("#grammar-choices");
  choices.replaceChildren();
  $("#grammar-answer-form").hidden = exercise.type === "multiple_choice" || exercise.type === "ordering";
  $("#grammar-ordering").hidden = exercise.type !== "ordering";
  $("#grammar-answer").value = "";
  if (exercise.type === "multiple_choice") {
    shuffledChoices(exercise.choices).forEach(choice => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = choice;
      button.addEventListener("click", () => submitGrammarAnswer(choice));
      choices.append(button);
    });
  }
  selectedTokens = [];
  orderingTokens = exercise.type === "ordering"
    ? shuffledOrderingTokens(exercise.tokens)
    : [];
  if (exercise.type === "ordering") renderOrdering();
}

function shuffledChoices(choices) {
  const shuffled = [...choices];
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const randomIndex = Math.floor(Math.random() * (index + 1));
    [shuffled[index], shuffled[randomIndex]] = [shuffled[randomIndex], shuffled[index]];
  }
  return shuffled;
}

function shuffledOrderingTokens(tokens) {
  const shuffled = tokens.map((token, index) => ({ index, token }));
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const randomIndex = Math.floor(Math.random() * (index + 1));
    [shuffled[index], shuffled[randomIndex]] = [shuffled[randomIndex], shuffled[index]];
  }
  if (shuffled.length > 1 && shuffled.every((item, index) => item.index === index)) {
    shuffled.push(shuffled.shift());
  }
  return shuffled;
}

function ruleSummaryPoints(summary) {
  const text = String(summary || "").trim();
  if (!text) return [];
  const lines = text.split(/\r?\n/).map(line => (
    line.trim().replace(/^(?:[-*•]|\d+[.)])\s+/, "")
  )).filter(Boolean);
  if (lines.length > 1) return lines;
  if (typeof Intl.Segmenter === "function") {
    return [...new Intl.Segmenter("en", { granularity: "sentence" }).segment(text)]
      .map(({ segment }) => segment.trim())
      .filter(Boolean);
  }
  return text.split(/(?<=[.!?])\s+/).filter(Boolean);
}

function renderTopicHeading() {
  const topics = activeSession.topics || [];
  const title = $("#grammar-topic-title");
  const list = $("#grammar-topic-list");
  list.replaceChildren();
  if (activeSession.kind !== "review") {
    title.textContent = topics.map(topic => topic.title).join(" · ");
    list.hidden = true;
    return;
  }
  const countKey = topics.length === 1 ? "one" : "other";
  title.textContent = t(`grammar.reviewRules.${countKey}`, { count: topics.length });
  list.replaceChildren(...topics.map(topic => {
    const item = document.createElement("li");
    const disclosure = document.createElement("details");
    disclosure.className = "grammar-topic-disclosure";
    const heading = document.createElement("summary");
    const label = document.createElement("span");
    label.textContent = topic.title;
    const chevron = document.createElement("span");
    chevron.className = "grammar-topic-chevron";
    chevron.setAttribute("aria-hidden", "true");
    heading.append(label, chevron);
    const summary = document.createElement("p");
    summary.className = "grammar-topic-summary";
    if (topic.summary) summary.textContent = topic.summary;
    disclosure.append(heading, summary);
    disclosure.addEventListener("toggle", () => {
      if (disclosure.open && !topic.summary && summary.dataset.loading !== "true") {
        loadTopicSummary(topic, summary);
      }
    });
    item.append(disclosure);
    return item;
  }));
  list.hidden = false;
}

async function loadTopicSummary(topic, summary) {
  const controller = new AbortController();
  summaryControllers.add(controller);
  summary.dataset.loading = "true";
  summary.textContent = t("grammar.summaryGenerating");
  try {
    const { response, data } = await grammarFetch(
      `/api/grammar/session/${activeSession.id}/topics/${encodeURIComponent(topic.key)}/summary`,
      { method: "POST" },
      controller,
    );
    if (!response.ok) throw new Error(data.detail || t("grammar.summaryError"));
    topic.summary = data.summary;
    summary.textContent = data.summary;
  } catch {
    summary.textContent = t("grammar.summaryError");
  } finally {
    summaryControllers.delete(controller);
    summary.dataset.loading = "false";
  }
}

function renderRuleTable(ruleTable) {
  const wrapper = document.createElement("div");
  wrapper.className = "grammar-rule-table-wrap";
  const table = document.createElement("table");
  table.className = "grammar-rule-table";
  const caption = document.createElement("caption");
  caption.textContent = ruleTable.title;
  table.append(caption);
  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");
  ruleTable.headers.forEach(header => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = header;
    headerRow.append(cell);
  });
  head.append(headerRow);
  table.append(head);
  const body = document.createElement("tbody");
  ruleTable.rows.forEach(row => {
    const tableRow = document.createElement("tr");
    row.forEach(value => {
      const cell = document.createElement("td");
      cell.textContent = value;
      tableRow.append(cell);
    });
    body.append(tableRow);
  });
  table.append(body);
  wrapper.append(table);
  return wrapper;
}

function renderOrdering() {
  $("#grammar-order-answer").textContent = orderingAnswer();
  const pool = $("#grammar-order-tokens");
  pool.replaceChildren();
  orderingTokens.forEach(({ index, token }) => {
    const used = selectedTokens.some(item => item.index === index);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = token;
    button.disabled = used;
    button.addEventListener("click", () => {
      selectedTokens.push({ index, token });
      renderOrdering();
    });
    pool.append(button);
  });
  $("#grammar-order-answer").textContent = orderingAnswer();
}

function orderingAnswer() {
  return selectedTokens.map(item => item.token).join(" ")
    .replace(/\s+([,.;:!?%)\]}])/g, "$1")
    .replace(/([¿¡(\[{])\s+/g, "$1");
}

async function submitGrammarAnswer(answer) {
  if (answerController) return;
  const controller = new AbortController();
  answerController = controller;
  document.querySelectorAll("#grammar-exercise button, #grammar-exercise input").forEach(control => { control.disabled = true; });
  $("#grammar-feedback-title").textContent = t("grammar.checking");
  $("#grammar-feedback-copy").textContent = "";
  $("#grammar-reference-row").hidden = true;
  $("#grammar-explanation").hidden = true;
  $("#grammar-continue").hidden = true;
  $("#grammar-feedback").hidden = false;
  try {
    const exercise = activeSession.exercise;
    const { response, data: result } = await grammarFetch(`/api/grammar/session/${activeSession.id}/exercises/${exercise.id}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    }, controller);
    if (!response.ok) throw new Error(result.detail || t("revision.answerSaveError"));
    $("#grammar-feedback-title").textContent = result.correct ? t("revision.correct") : t("grammar.notQuite");
    $("#grammar-feedback-copy").textContent = result.feedback;
    $("#grammar-reference").textContent = result.reference_answer;
    $("#grammar-reference-row").hidden = false;
    $("#grammar-explanation").textContent = result.explanation;
    $("#grammar-explanation").hidden = false;
    if (result.session_complete) {
      completedSessionSummary = {
        answered: activeSession.answered + 1,
        correct: activeSession.correct + Number(result.correct),
      };
    }
    $("#grammar-continue").textContent = result.session_complete
      ? t("grammar.finish")
      : t("revision.continue");
    $("#grammar-continue").hidden = false;
    $("#grammar-feedback").hidden = false;
  } catch (error) {
    if (error.name === "AbortError") return;
    document.querySelectorAll("#grammar-exercise button, #grammar-exercise input").forEach(control => { control.disabled = false; });
    $("#grammar-feedback-title").textContent = error.message;
    $("#grammar-feedback-copy").textContent = "";
    $("#grammar-reference").textContent = "";
    $("#grammar-reference-row").hidden = true;
    $("#grammar-explanation").textContent = "";
    $("#grammar-explanation").hidden = true;
    $("#grammar-continue").hidden = true;
    $("#grammar-feedback").hidden = false;
  } finally {
    if (answerController === controller) answerController = null;
  }
}
