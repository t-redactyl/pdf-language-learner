import { t } from "./i18n.js?v=17";

const $ = selector => document.querySelector(selector);
let activeSession = null;
let selectedTokens = [];
let loadCurrent = null;

export function initializeGrammarRevision(reload) {
  loadCurrent = reload;
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
    if (selectedTokens.length) submitGrammarAnswer(selectedTokens.map(item => item.token).join(" "));
  });
  $("#grammar-continue")?.addEventListener("click", () => loadCurrent());
}

export async function loadGrammarRevision(language) {
  $("#grammar-session").hidden = true;
  const response = await fetch("/api/grammar/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || t("grammar.loadError"));
  activeSession = data;
  renderSession();
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
  $("#grammar-topic-title").textContent = activeSession.topics.map(topic => topic.title).join(" · ");
  const lesson = $("#grammar-lesson");
  lesson.hidden = activeSession.kind !== "lesson";
  $("#grammar-rule-summary").textContent = activeSession.rule_summary;
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
  const choices = $("#grammar-choices");
  choices.replaceChildren();
  $("#grammar-answer-form").hidden = exercise.type === "multiple_choice" || exercise.type === "ordering";
  $("#grammar-ordering").hidden = exercise.type !== "ordering";
  $("#grammar-answer").value = "";
  if (exercise.type === "multiple_choice") {
    exercise.choices.forEach(choice => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = choice;
      button.addEventListener("click", () => submitGrammarAnswer(choice));
      choices.append(button);
    });
  }
  selectedTokens = [];
  if (exercise.type === "ordering") renderOrdering();
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
  const tokens = activeSession.exercise.tokens;
  $("#grammar-order-answer").textContent = selectedTokens.join(" ");
  const pool = $("#grammar-order-tokens");
  pool.replaceChildren();
  tokens.forEach((token, index) => {
    const used = selectedTokens.some(item => item.index === index);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = token;
    button.disabled = used;
    button.addEventListener("click", () => {
      selectedTokens.push({ index, token });
      $("#grammar-order-answer").textContent = selectedTokens.map(item => item.token).join(" ");
      renderOrdering();
    });
    pool.append(button);
  });
  $("#grammar-order-answer").textContent = selectedTokens.map(item => item.token).join(" ");
}

async function submitGrammarAnswer(answer) {
  document.querySelectorAll("#grammar-exercise button, #grammar-exercise input").forEach(control => { control.disabled = true; });
  try {
    const exercise = activeSession.exercise;
    const response = await fetch(`/api/grammar/session/${activeSession.id}/exercises/${exercise.id}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || t("revision.answerSaveError"));
    $("#grammar-feedback-title").textContent = result.correct ? t("revision.correct") : t("grammar.notQuite");
    $("#grammar-feedback-copy").textContent = result.feedback;
    $("#grammar-reference").textContent = result.reference_answer;
    $("#grammar-explanation").textContent = result.explanation;
    $("#grammar-continue").textContent = result.session_complete ? t("grammar.nextSession") : t("revision.continue");
    $("#grammar-feedback").hidden = false;
  } catch (error) {
    document.querySelectorAll("#grammar-exercise button, #grammar-exercise input").forEach(control => { control.disabled = false; });
    $("#grammar-feedback-title").textContent = error.message;
    $("#grammar-feedback-copy").textContent = "";
    $("#grammar-reference").textContent = "";
    $("#grammar-explanation").textContent = "";
    $("#grammar-feedback").hidden = false;
  }
}
