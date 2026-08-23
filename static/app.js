import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.min.mjs";
import { sentenceContext } from "./text.js?v=2";

pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.worker.min.mjs";
const $ = (selector) => document.querySelector(selector);
const pages = $("#pages");
let selectedText = "";
let selectedContext = "";
let selectedContextOffset = null;
let activeDocumentKey = "";
let detectedSourceLanguage = "";
let sourceLanguageOverride = "";
let documentLanguageSample = "";
let languageDetectionPending = false;
let languageDetectionError = "";
let pendingHighlight = [];
const textItemForSpan = new WeakMap();
const characterOffsetsForSpan = new WeakMap();
const measurementContext = document.createElement("canvas").getContext("2d");
let selectionDragStart = null;
let translations = [];
const LEGACY_SAVED_VOCABULARY_STORAGE_KEY = "margin:saved-vocabulary:v1";
let savedVocabulary = [];

loadSavedVocabulary().catch(() => {});

document.querySelectorAll("input[type=file]").forEach((input) => input.addEventListener("change", (event) => openPdf(event.target.files[0])));

async function openPdf(file) {
  if (!file) return;
  pages.replaceChildren();
  activeDocumentKey = `margin:${file.name}:${file.size}:${file.lastModified}`;
  // Highlights used to be persisted under the document key. Remove that legacy
  // data now that highlights are intentionally transient.
  try { localStorage.removeItem(activeDocumentKey); } catch {}
  translations = readStoredTranslations();
  renderTranslationHistory();
  renderSavedVocabulary();
  selectedText = "";
  selectedContext = "";
  selectedContextOffset = null;
  pendingHighlight = [];
  documentLanguageSample = "";
  languageDetectionPending = false;
  languageDetectionError = "";
  readDocumentLanguageState();
  renderSourceLanguageState();
  $("#selection-hint").hidden = false;
  $("#translation-content").hidden = true;
  $("#result").hidden = true;
  $("#error").textContent = "";
  const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
  $("#empty-state").hidden = true;
  $("#reader").hidden = false;
  const pageTexts = [];
  for (let number = 1; number <= pdf.numPages; number += 1) {
    pageTexts.push(await renderPage(await pdf.getPage(number), number));
  }
  documentLanguageSample = pageTexts.join("\n").replace(/\s+/g, " ").trim().slice(0, 12000);
  if (!detectedSourceLanguage) await detectDocumentLanguage();
}

async function renderPage(page, number) {
  const baseViewport = page.getViewport({ scale: 1 });
  const viewport = page.getViewport({ scale: Math.min(1.55, 820 / baseViewport.width) });
  const wrapper = document.createElement("article");
  wrapper.className = "pdf-page";
  wrapper.dataset.page = number;
  // TextLayer uses this variable for all PDF-space coordinates and font sizes.
  // The stock PDF.js viewer defines it on its viewer container; since this app
  // embeds TextLayer directly, it must provide the viewport scale itself.
  wrapper.style.setProperty("--scale-factor", viewport.scale);
  wrapper.style.width = `${viewport.width}px`;
  wrapper.style.height = `${viewport.height}px`;
  const canvas = document.createElement("canvas");
  const ratio = window.devicePixelRatio || 1;
  canvas.width = viewport.width * ratio;
  canvas.height = viewport.height * ratio;
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  wrapper.append(canvas);
  const highlightLayer = document.createElement("div");
  highlightLayer.className = "highlight-layer";
  wrapper.append(highlightLayer);
  const textLayer = document.createElement("div");
  textLayer.className = "textLayer";
  wrapper.append(textLayer);
  pages.append(wrapper);
  await page.render({ canvasContext: canvas.getContext("2d"), viewport, transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0] }).promise;
  const textContent = await page.getTextContent();
  const textLayerTask = new pdfjsLib.TextLayer({ textContentSource: textContent, container: textLayer, viewport });
  await textLayerTask.render();
  // TextLayer pushes exactly one span per text item, in item order, so the two
  // arrays line up index for index.
  textLayerTask.textDivs.forEach((span, index) => textItemForSpan.set(span, textContent.items[index]));
  return textContent.items.map(item => `${item.str}${item.hasEOL ? "\n" : " "}`).join("");
}

document.addEventListener("selectionchange", () => {
  const selection = window.getSelection();
  if (!selection?.rangeCount || !pages.contains(selection.anchorNode) || !pages.contains(selection.focusNode)) return;
  const selected = readSelection(selection.getRangeAt(0));
  if (selected) showSelection(selected);
});

pages.addEventListener("pointerdown", event => {
  if (event.button !== 0) return;
  clearCurrentHighlight();
  pendingHighlight = [];
  if (event.target.closest(".textLayer")) {
    selectionDragStart = { x: event.clientX, y: event.clientY };
  }
});

document.addEventListener("pointerup", event => {
  const start = selectionDragStart;
  selectionDragStart = null;
  const selection = window.getSelection();
  if (!start || !selection?.rangeCount || !pages.contains(selection.anchorNode) || !pages.contains(selection.focusNode)) return;
  const end = { x: event.clientX, y: event.clientY };
  // A click or a double-click word selection has no meaningful drag extent, so
  // only clamp to the pointer path when the pointer actually travelled.
  const dragged = Math.hypot(end.x - start.x, end.y - start.y) > 3;
  const selected = readSelection(selection.getRangeAt(0), dragged ? { start, end } : null);
  if (selected) showSelection(selected);
});

function showSelection({ text, rectangles, context = "", contextOffset = null }) {
  selectedText = text;
  selectedContext = context;
  selectedContextOffset = contextOffset;
  $("#selected-text").textContent = text;
  $("#selection-hint").hidden = true;
  $("#translation-content").hidden = false;
  $("#result").hidden = true;
  $("#error").textContent = "";
  pendingHighlight = rectangles;
  renderSourceLanguageState();
}

// The quoted text and the highlight have to come out of a single measurement
// pass. Deriving the text from glyph geometry while taking the highlight from
// the native Range makes the two disagree by however much the two coordinate
// models differ, which is exactly the mismatch this replaces.
function readSelection(range, drag = null) {
  const selected = selectionGeometry(range, drag);
  if (selected.text && selected.rectangles.length) {
    return { ...selected, ...selectionContext(range, selected.text) };
  }
  // Chrome sometimes reports a range whose text is not empty but whose client
  // rectangles are degenerate. Quoting that text would leave the panel showing a
  // phrase with nothing highlighted, so a selection is only accepted when it
  // comes with the geometry to highlight it; otherwise the previous one stands.
  const text = range.toString().replace(/\s+/g, " ").trim();
  if (!text) return null;
  const rectangles = rangeRectangles(range);
  return rectangles.length
    ? { text, rectangles, ...selectionContext(range, text) }
    : null;
}

function selectionContext(range, selectedText) {
  const startElement = range.startContainer.nodeType === Node.ELEMENT_NODE
    ? range.startContainer
    : range.startContainer.parentElement;
  const endElement = range.endContainer.nodeType === Node.ELEMENT_NODE
    ? range.endContainer
    : range.endContainer.parentElement;
  const page = startElement?.closest?.(".pdf-page");
  if (!page || page !== endElement?.closest?.(".pdf-page")) return { context: "", contextOffset: null };
  const spans = [...page.querySelectorAll(".textLayer span")];
  const start = spans.indexOf(startElement.closest("span"));
  const end = spans.indexOf(endElement.closest("span"));
  if (start < 0 || end < 0) return { context: "", contextOffset: null };
  const selectedStart = Math.min(start, end);
  const spanText = span => textItemForSpan.get(span)?.str || span.textContent;
  const offsetWithinSpan = range.startContainer.nodeType === Node.TEXT_NODE
    ? range.startOffset
    : 0;
  let context = "";
  let approximateOffset = 0;
  let previousRect = null;
  spans.forEach((span, index) => {
    const rect = span.getBoundingClientRect();
    const separator = context ? separatorBefore(rect, previousRect) : "";
    if (index === selectedStart) {
      approximateOffset = context.length + separator.length + offsetWithinSpan;
    }
    context += separator + spanText(span);
    previousRect = rect;
  });
  const sentence = sentenceContext(context, selectedText, approximateOffset);
  return {
    context: sentence.text.slice(0, 2000),
    contextOffset: sentence.offset,
  };
}

function selectionGeometry(range, drag) {
  const selectionRects = [...range.getClientRects()].filter(rect => rect.width >= 1 && rect.height >= 1);
  if (!selectionRects.length) return { text: "", rectangles: [] };
  const selectionTop = Math.min(...selectionRects.map(rect => rect.top));
  const selectionBottom = Math.max(...selectionRects.map(rect => rect.bottom));
  const rectangles = [];
  let text = "";
  let previousRect = null;

  for (const page of document.querySelectorAll(".pdf-page")) {
    const pageBox = page.getBoundingClientRect();
    if (pageBox.bottom < selectionTop || pageBox.top > selectionBottom) continue;

    for (const span of page.querySelectorAll(".textLayer span")) {
      const characters = span.textContent;
      if (!textItemForSpan.get(span)?.fontName || !characters || span.style.transform.includes("rotate")) continue;
      const spanRect = span.getBoundingClientRect();
      if (spanRect.width <= 0 || spanRect.height <= 0) continue;

      // A line rectangle is as tall as the tallest span on its line, so test the
      // span's own centre line instead of accepting any vertical overlap; that
      // keeps neighbouring lines out of a single-line selection.
      const centre = spanRect.top + spanRect.height / 2;
      const overlaps = selectionRects.filter(rect =>
        rect.right > spanRect.left && rect.left < spanRect.right && rect.top <= centre && rect.bottom >= centre
      );
      if (!overlaps.length) continue;

      const dragIsOnThisLine = drag &&
        drag.start.y >= spanRect.top && drag.start.y <= spanRect.bottom &&
        drag.end.y >= spanRect.top && drag.end.y <= spanRect.bottom;
      const left = Math.max(spanRect.left, dragIsOnThisLine
        ? Math.min(drag.start.x, drag.end.x)
        : Math.min(...overlaps.map(rect => rect.left)));
      const right = Math.min(spanRect.right, dragIsOnThisLine
        ? Math.max(drag.start.x, drag.end.x)
        : Math.max(...overlaps.map(rect => rect.right)));
      if (right <= left) continue;

      const offsets = characterOffsets(span, characters);
      const scale = spanRect.width / offsets.at(-1);
      if (!Number.isFinite(scale) || scale <= 0) continue;

      // A character is selected when its own centre falls inside the region,
      // which treats both edges alike rather than snapping each one to whichever
      // character boundary happens to sit nearest.
      let start = characters.length;
      let end = 0;
      for (let index = 0; index < characters.length; index += 1) {
        const characterCentre = spanRect.left + scale * (offsets[index] + offsets[index + 1]) / 2;
        if (characterCentre < left || characterCentre > right) continue;
        start = Math.min(start, index);
        end = Math.max(end, index + 1);
      }
      if (start >= end) continue;

      const from = spanRect.left + scale * offsets[start];
      const to = spanRect.left + scale * offsets[end];
      // Clamp the height to the line that matched rather than using the whole
      // span box: a PDF can set a blank run in a huge font beside a drop cap,
      // and a box that tall would paint over lines outside the selection.
      const top = Math.max(spanRect.top, Math.min(...overlaps.map(rect => rect.top)));
      const bottom = Math.min(spanRect.bottom, Math.max(...overlaps.map(rect => rect.bottom)));
      if (bottom <= top) continue;
      rectangles.push({
        page: Number(page.dataset.page),
        x: (from - pageBox.left) / pageBox.width,
        y: (top - pageBox.top) / pageBox.height,
        width: (to - from) / pageBox.width,
        height: (bottom - top) / pageBox.height,
      });
      text += (text ? separatorBefore(spanRect, previousRect) : "") + characters.slice(start, end);
      previousRect = spanRect;
    }
  }
  return { text: text.replace(/\s+/g, " ").trim(), rectangles };
}

// PDF text runs carry their own spacing, so joining every run with a space
// splits words that the producer happened to emit in two pieces. Only add one
// where the layout implies a break: a new line, or a visible horizontal gap.
function separatorBefore(spanRect, previousRect) {
  if (!previousRect) return "";
  const centre = spanRect.top + spanRect.height / 2;
  const previousCentre = previousRect.top + previousRect.height / 2;
  const changedLine = Math.abs(centre - previousCentre) > spanRect.height / 2;
  return changedLine || spanRect.left - previousRect.right > spanRect.height * 0.2 ? " " : "";
}

// PDF.js stretches each span with scaleX so its rendered width matches the PDF's
// own, so measuring in the span's real rendered font reproduces the character
// positions the reader is selecting over. Reading the family off the computed
// style matters: item.fontName is a style-cache key, not always a loaded family,
// and a family the canvas cannot resolve silently measures in a fallback font.
function characterOffsets(span, characters) {
  const cached = characterOffsetsForSpan.get(span);
  if (cached) return cached;
  const style = getComputedStyle(span);
  measurementContext.font = `${style.fontSize} ${style.fontFamily}`;
  const offsets = [0];
  for (let index = 1; index <= characters.length; index += 1) {
    offsets.push(measurementContext.measureText(characters.slice(0, index)).width);
  }
  characterOffsetsForSpan.set(span, offsets);
  return offsets;
}

function rangeRectangles(range) {
  const rectangles = [];
  for (const page of document.querySelectorAll(".pdf-page")) {
    const pageBox = page.getBoundingClientRect();
    for (const rect of range.getClientRects()) {
      if (rect.width < 1 || rect.height < 1) continue;
      if (rect.bottom < pageBox.top || rect.top > pageBox.bottom || rect.right < pageBox.left || rect.left > pageBox.right) continue;
      rectangles.push({ page: Number(page.dataset.page), x: (rect.left-pageBox.left)/pageBox.width, y: (rect.top-pageBox.top)/pageBox.height, width: rect.width/pageBox.width, height: rect.height/pageBox.height });
    }
  }
  return rectangles;
}

function documentLanguageStorageKey() {
  return `${activeDocumentKey}:language`;
}

function readDocumentLanguageState() {
  detectedSourceLanguage = "";
  sourceLanguageOverride = "";
  try {
    const stored = JSON.parse(localStorage.getItem(documentLanguageStorageKey()) || "{}");
    if (typeof stored.detectedLanguage === "string") detectedSourceLanguage = stored.detectedLanguage;
    if (typeof stored.override === "string") sourceLanguageOverride = stored.override;
  } catch {}
}

function saveDocumentLanguageState() {
  localStorage.setItem(documentLanguageStorageKey(), JSON.stringify({
    detectedLanguage: detectedSourceLanguage,
    override: sourceLanguageOverride,
  }));
}

function effectiveSourceLanguage() {
  return sourceLanguageOverride || detectedSourceLanguage;
}

function renderSourceLanguageState(message = "") {
  const select = $("#source-language");
  const status = $("#source-language-status");
  select.value = sourceLanguageOverride || "auto";
  if (message) {
    status.textContent = message;
  } else if (sourceLanguageOverride) {
    status.textContent = `Using ${sourceLanguageOverride} (manual override)`;
  } else if (detectedSourceLanguage) {
    status.textContent = `Detected ${detectedSourceLanguage} for this document`;
  } else if (languageDetectionPending) {
    status.textContent = "Detecting document language…";
  } else if (languageDetectionError) {
    status.textContent = languageDetectionError;
  } else {
    status.textContent = "Choose a language to translate";
  }
  $("#translate-button").disabled = !selectedText || !effectiveSourceLanguage();
}

async function detectDocumentLanguage() {
  if (languageDetectionPending || detectedSourceLanguage || documentLanguageSample.length < 20) {
    renderSourceLanguageState();
    return;
  }
  const documentKey = activeDocumentKey;
  languageDetectionPending = true;
  languageDetectionError = "";
  renderSourceLanguageState();
  try {
    const response = await fetch("/api/detect-language", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: documentLanguageSample }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Language detection failed (${response.status})`);
    if (activeDocumentKey !== documentKey) return;
    detectedSourceLanguage = data.detected_language;
    saveDocumentLanguageState();
  } catch (error) {
    if (activeDocumentKey === documentKey) {
      languageDetectionError = "Automatic detection failed; choose the source language";
    }
  } finally {
    if (activeDocumentKey === documentKey) {
      languageDetectionPending = false;
      renderSourceLanguageState();
    }
  }
}

$("#source-language").addEventListener("change", event => {
  sourceLanguageOverride = event.target.value === "auto" ? "" : event.target.value;
  saveDocumentLanguageState();
  renderSourceLanguageState();
  if (!sourceLanguageOverride && !detectedSourceLanguage) detectDocumentLanguage();
});

function showNormalizedResult(source, isWord) {
  $("#normalized-result").hidden = !isWord;
  $("#normalized-text").textContent = source;
}

$("#translate-button").addEventListener("click", async () => {
  const button = $("#translate-button");
  button.disabled = true; button.textContent = "Translating…"; $("#error").textContent = "";
  try {
    const sourceLanguage = effectiveSourceLanguage();
    if (!sourceLanguage) throw new Error("Choose the document's source language first");
    const response = await fetch("/api/translate", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ text:selectedText, source_language:sourceLanguage, target_language:$("#target-language").value, context:selectedContext, context_offset:selectedContextOffset }) });
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
      ? await response.json()
      : { detail: await response.text() };

    if (!response.ok) {
      throw new Error(
        data.detail || `Translation failed (${response.status})`
      );
    }
    $("#detected-language").textContent = `Source ${data.detected_language}`;
    const isWord = data.is_word === true
      && selectedText.trim().split(/\s+/).length === 1;
    showNormalizedResult(data.normalized_source, isWord);
    $("#translated-text").textContent = data.translation;
    $("#result").hidden = false;
    showCurrentHighlight(pendingHighlight);
    saveTranslation({
      source: data.normalized_source,
      originalSource: selectedText,
      normalizedSource: data.normalized_source,
      translation: data.translation,
      detectedLanguage: data.detected_language,
      sourceLanguage,
      targetLanguage: $("#target-language").value,
      context: selectedContext,
      contextOffset: selectedContextOffset,
      documentKey: activeDocumentKey,
      createdAt: new Date().toISOString(),
      isWord,
    });
  } catch (error) { $("#error").textContent = error.message; }
  finally { button.textContent = "Translate selection"; renderSourceLanguageState(); }
});

function showCurrentHighlight(rectangles) {
  if (!rectangles.length) return;
  clearCurrentHighlight();
  drawHighlight(rectangles); pendingHighlight = []; window.getSelection()?.removeAllRanges();
}

function clearCurrentHighlight() {
  document.querySelectorAll(".highlight-layer").forEach((layer) => layer.replaceChildren());
}

function drawHighlight(rectangles) {
  for (const rect of rectangles) {
    const mark = document.createElement("span");
    mark.style.cssText = `left:${rect.x*100}%;top:${rect.y*100}%;width:${rect.width*100}%;height:${rect.height*100}%`;
    document.querySelector(`.pdf-page[data-page="${rect.page}"] .highlight-layer`)?.append(mark);
  }
}

function translationsStorageKey() {
  return `${activeDocumentKey}:translations`;
}

function readStoredTranslations() {
  try {
    const stored = JSON.parse(localStorage.getItem(translationsStorageKey()) || "[]");
    return Array.isArray(stored) ? stored : [];
  } catch {
    return [];
  }
}

function saveTranslation(translation) {
  translations.unshift(translation);
  localStorage.setItem(translationsStorageKey(), JSON.stringify(translations));
  renderTranslationHistory();
}

function readLegacySavedVocabulary() {
  try {
    const stored = JSON.parse(localStorage.getItem(LEGACY_SAVED_VOCABULARY_STORAGE_KEY) || "[]");
    return Array.isArray(stored) ? stored.filter(entry => entry && typeof entry === "object") : [];
  } catch {
    return [];
  }
}

function vocabularyKey(entry) {
  return [
    entry.normalizedSource || entry.source || "",
    entry.sourceLanguage || entry.detectedLanguage || "",
  ].map(value => String(value).normalize("NFKC").trim().toLocaleLowerCase().replace(/\s+/g, " ")).join("\u0000");
}

function savedVocabularyIndex(translation) {
  const key = vocabularyKey(translation);
  return savedVocabulary.findIndex(entry => vocabularyKey(entry) === key);
}

function vocabularyRequest(translation) {
  return {
    originalSource: translation.originalSource || translation.source,
    normalizedSource: translation.normalizedSource || translation.source,
    translation: translation.translation,
    sourceLanguage: translation.sourceLanguage || translation.detectedLanguage,
    targetLanguage: translation.targetLanguage,
    context: translation.context || "",
    documentKey: translation.documentKey || activeDocumentKey,
  };
}

function vocabularyApiPayload(translation) {
  const item = vocabularyRequest(translation);
  return {
    original_source: item.originalSource,
    normalized_source: item.normalizedSource,
    translation: item.translation,
    source_language: item.sourceLanguage,
    target_language: item.targetLanguage,
    context: item.context,
    document_key: item.documentKey,
  };
}

function vocabularyFromApi(item) {
  return {
    id: item.id,
    schemaVersion: item.schema_version,
    source: item.normalized_source,
    originalSource: item.original_source,
    normalizedSource: item.normalized_source,
    translation: item.translation,
    sourceLanguage: item.source_language,
    targetLanguage: item.target_language,
    context: item.context,
    documentKey: item.document_key,
    savedAt: item.saved_at,
    review: item.review,
  };
}

async function requestVocabulary(translation) {
  const response = await fetch("/api/vocabulary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(vocabularyApiPayload(translation)),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Vocabulary could not be saved");
  return vocabularyFromApi(data.item);
}

async function loadSavedVocabulary() {
  const legacyVocabulary = readLegacySavedVocabulary();
  let migrationComplete = legacyVocabulary.length > 0;
  for (const entry of legacyVocabulary) {
    try {
      await requestVocabulary(entry);
    } catch {
      migrationComplete = false;
    }
  }
  if (migrationComplete) localStorage.removeItem(LEGACY_SAVED_VOCABULARY_STORAGE_KEY);

  const response = await fetch("/api/vocabulary");
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Saved vocabulary could not be loaded");
  savedVocabulary = data.map(vocabularyFromApi);
  renderTranslationHistory();
  renderSavedVocabulary();
}

async function toggleSavedVocabulary(translation) {
  const index = savedVocabularyIndex(translation);
  if (index >= 0) {
    const response = await fetch(`/api/vocabulary/${encodeURIComponent(savedVocabulary[index].id)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || "Saved vocabulary could not be removed");
    }
  } else {
    await requestVocabulary(translation);
  }
  await loadSavedVocabulary();
}

function createTranslationListItem(translation, index, collection) {
  const item = document.createElement("li");
  item.className = "history-row";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "history-item";
  button.dataset.translationIndex = index;
  button.dataset.translationCollection = collection;

  const source = document.createElement("span");
  source.className = "history-source";
  source.textContent = translation.normalizedSource || translation.source;
  const translated = document.createElement("span");
  translated.className = "history-translation";
  translated.textContent = translation.translation;
  button.append(source, translated);

  const isWord = translation.isWord
    ?? String(translation.originalSource || translation.source || "").trim().split(/\s+/).length === 1;
  const saveButton = document.createElement("button");
  const isSaved = savedVocabularyIndex(translation) >= 0;
  saveButton.type = "button";
  saveButton.className = "vocabulary-toggle";
  saveButton.dataset.translationIndex = index;
  saveButton.dataset.translationCollection = collection;
  saveButton.setAttribute("aria-pressed", String(isSaved));
  saveButton.setAttribute("aria-label", isSaved ? `Remove ${source.textContent} from saved vocabulary` : `Save ${source.textContent} for revision`);
  saveButton.title = isSaved ? "Remove from saved vocabulary" : "Save for revision";
  saveButton.textContent = isSaved ? "★" : "☆";

  item.append(button);
  if (isWord || collection === "saved") item.append(saveButton);
  return item;
}

function renderTranslationHistory() {
  const list = $("#translation-history-list");
  if (!list) return;
  list.replaceChildren();
  const emptyState = $("#translation-history-empty");
  const clearButton = $("#clear-translations");
  if (emptyState) emptyState.hidden = translations.length > 0;
  if (clearButton) clearButton.hidden = translations.length === 0;

  translations.forEach((translation, index) => {
    list.append(createTranslationListItem(translation, index, "history"));
  });
}

function renderSavedVocabulary() {
  const list = $("#saved-vocabulary-list");
  if (!list) return;
  list.replaceChildren();
  $("#saved-vocabulary-empty").hidden = savedVocabulary.length > 0;
  $("#saved-vocabulary-count").textContent = savedVocabulary.length ? String(savedVocabulary.length) : "";
  savedVocabulary.forEach((translation, index) => {
    list.append(createTranslationListItem(translation, index, "saved"));
  });
}

function translationFromControl(control) {
  const collection = control.dataset.translationCollection === "saved" ? savedVocabulary : translations;
  return collection[Number(control.dataset.translationIndex)];
}

function showTranslation(translation) {
  const source = translation.normalizedSource || translation.source;
  const sourceLanguage = translation.sourceLanguage || translation.detectedLanguage;
  selectedText = translation.originalSource || source;
  selectedContext = translation.context || "";
  selectedContextOffset = translation.contextOffset ?? null;
  pendingHighlight = [];
  $("#selected-text").textContent = translation.originalSource || source;
  $("#target-language").value = translation.targetLanguage;
  $("#detected-language").textContent = `Source ${sourceLanguage}`;
  const isWord = translation.isWord
    ?? String(translation.originalSource || source).trim().split(/\s+/).length === 1;
  showNormalizedResult(source, isWord);
  $("#translated-text").textContent = translation.translation;
  $("#selection-hint").hidden = true;
  $("#translation-content").hidden = false;
  $("#result").hidden = false;
  $("#error").textContent = "";
}

async function handleTranslationListClick(event) {
  const saveButton = event.target.closest(".vocabulary-toggle");
  if (saveButton) {
    const translation = translationFromControl(saveButton);
    if (!translation) return;
    saveButton.disabled = true;
    try {
      await toggleSavedVocabulary(translation);
    } catch (error) {
      $("#error").textContent = error.message;
    } finally {
      saveButton.disabled = false;
    }
    return;
  }

  const button = event.target.closest(".history-item");
  if (!button) return;
  const translation = translationFromControl(button);
  if (translation) showTranslation(translation);
}

$("#translation-history-list")?.addEventListener("click", handleTranslationListClick);
$("#saved-vocabulary-list")?.addEventListener("click", handleTranslationListClick);

$("#clear-translations")?.addEventListener("click", () => {
  translations = [];
  localStorage.removeItem(translationsStorageKey());
  renderTranslationHistory();
});
