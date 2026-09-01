import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.min.mjs";
import { sentenceContext } from "./text.js?v=5";
import { initI18n, languageName, t } from "./i18n.js?v=21";

pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.worker.min.mjs";
const $ = (selector) => document.querySelector(selector);
const pages = $("#pages");
const pagesScroll = $("#pages-scroll");
const PDF_ZOOM_LEVELS = [0.75, 1, 1.25, 1.5, 1.75, 2, 2.5];
let pdfZoomIndex = 1;
let selectedText = "";
let selectedContext = "";
let selectedContextOffset = null;
let activeDocumentKey = "";
let detectedSourceLanguage = "";
let sourceLanguageOverride = "";
let documentLanguageSample = "";
let languageDetectionPending = false;
let languageDetectionError = "";
const preparedSourceLanguages = new Set();
let pendingHighlight = [];
let pendingTranscriptRange = null;
const textItemForSpan = new WeakMap();
const characterOffsetsForSpan = new WeakMap();
const measurementContext = document.createElement("canvas").getContext("2d");
let selectionDragStart = null;
let translations = [];
let displayedTranslation = null;
let activePdf = null;
let activeHls = null;
const pdfPageState = new WeakMap();
const pdfPageRenderObserver = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) renderPdfPage(entry.target);
    else releasePdfPage(entry.target);
  });
}, { rootMargin: "1200px 0px" });
const LEGACY_SAVED_VOCABULARY_STORAGE_KEY = "margin:saved-vocabulary:v1";
let savedVocabulary = [];
const pdfPageResizeObserver = new ResizeObserver(entries => {
  entries.forEach(({ target, contentRect }) => {
    const renderWidth = Number(target.dataset.renderWidth);
    if (renderWidth > 0) {
      target.style.setProperty("--responsive-scale", contentRect.width / renderWidth);
    }
  });
});
const pdfColumnResizeObserver = new ResizeObserver(() => applyPdfZoom());
pdfColumnResizeObserver.observe(pagesScroll);
let readerLayoutFrame = null;
let currentSuggestions = [];

function sizePdfPage(page) {
  const renderWidth = Number(page.dataset.renderWidth);
  if (!(renderWidth > 0)) return;
  const fitWidth = Math.min(renderWidth, pagesScroll.clientWidth || renderWidth);
  page.style.width = `${fitWidth * PDF_ZOOM_LEVELS[pdfZoomIndex]}px`;
}

function applyPdfZoom() {
  pages.querySelectorAll(".pdf-page").forEach(sizePdfPage);
  const zoom = PDF_ZOOM_LEVELS[pdfZoomIndex];
  $("#pdf-zoom-value").textContent = `${Math.round(zoom * 100)}%`;
  $("#pdf-zoom-out").disabled = pdfZoomIndex === 0;
  $("#pdf-zoom-in").disabled = pdfZoomIndex === PDF_ZOOM_LEVELS.length - 1;
}

function setPdfZoom(nextIndex) {
  const boundedIndex = Math.max(0, Math.min(PDF_ZOOM_LEVELS.length - 1, nextIndex));
  if (boundedIndex === pdfZoomIndex) return;
  const oldScrollWidth = pagesScroll.scrollWidth;
  const horizontalCentre = oldScrollWidth > 0
    ? (pagesScroll.scrollLeft + pagesScroll.clientWidth / 2) / oldScrollWidth
    : 0.5;
  const referenceY = window.innerHeight / 2;
  const anchorPage = [...pages.querySelectorAll(".pdf-page")].find(page => page.getBoundingClientRect().bottom >= referenceY);
  const anchorBox = anchorPage?.getBoundingClientRect();
  const anchorRatio = anchorBox?.height
    ? Math.max(0, Math.min(1, (referenceY - anchorBox.top) / anchorBox.height))
    : 0;

  pdfZoomIndex = boundedIndex;
  applyPdfZoom();
  if (anchorPage) {
    const resizedBox = anchorPage.getBoundingClientRect();
    window.scrollBy(0, resizedBox.top + resizedBox.height * anchorRatio - referenceY);
  }
  pagesScroll.scrollLeft = horizontalCentre * pagesScroll.scrollWidth - pagesScroll.clientWidth / 2;
  schedulePdfReaderLayout();
}

$("#pdf-zoom-out").addEventListener("click", () => setPdfZoom(pdfZoomIndex - 1));
$("#pdf-zoom-in").addEventListener("click", () => setPdfZoom(pdfZoomIndex + 1));
$("#pdf-zoom-reset").addEventListener("click", () => setPdfZoom(PDF_ZOOM_LEVELS.indexOf(1)));

function updatePdfReaderLayout() {
  readerLayoutFrame = null;
  const reader = $("#reader");
  reader.classList.remove("reader-stacked");
  const firstPage = pages.querySelector(".pdf-page");
  if (!firstPage || reader.hidden) {
    if (window.innerWidth > 1050) setReaderMetaOpen(false);
    return;
  }
  const pageBox = firstPage.getBoundingClientRect();
  const pageTopAtViewportStart = pageBox.top + window.scrollY;
  const availableHeight = window.innerHeight - pageTopAtViewportStart;
  // Keep the side panels while the page already fills the screen vertically.
  // If it would end with a visible strip of empty viewport beneath it, give the
  // PDF the full reading column and move translation controls to the bottom.
  reader.classList.toggle("reader-stacked", pageBox.height + 24 < availableHeight);
  if (!reader.classList.contains("reader-stacked") && window.innerWidth > 1050) {
    setReaderMetaOpen(false);
  }
}

function schedulePdfReaderLayout() {
  if (readerLayoutFrame !== null) cancelAnimationFrame(readerLayoutFrame);
  readerLayoutFrame = requestAnimationFrame(updatePdfReaderLayout);
}

window.addEventListener("resize", schedulePdfReaderLayout);

function setTranslationPanelCollapsed(collapsed) {
  const panel = $(".translation-panel");
  const toggle = $("#toggle-translation-panel");
  panel.classList.toggle("is-collapsed", collapsed);
  $("#reader").classList.toggle("translation-panel-collapsed", collapsed);
  toggle.setAttribute("aria-expanded", String(!collapsed));
  const label = t(collapsed ? "translation.expand" : "translation.collapse");
  toggle.setAttribute("aria-label", label);
  toggle.title = label;
  toggle.querySelector(".visually-hidden").textContent = label;
}

$("#toggle-translation-panel").addEventListener("click", () => {
  setTranslationPanelCollapsed(!$(".translation-panel").classList.contains("is-collapsed"));
});

function setReaderMetaOpen(open, returnFocus = false) {
  const reader = $("#reader");
  const toggle = $("#toggle-reader-meta");
  reader.classList.toggle("meta-open", open);
  document.body.classList.toggle("reader-meta-open", open);
  toggle.setAttribute("aria-expanded", String(open));
  $("#reader-meta-backdrop").hidden = !open;
  if (open) $("#close-reader-meta").focus();
  else if (returnFocus) toggle.focus();
}

$("#toggle-reader-meta").addEventListener("click", () => setReaderMetaOpen(true));
$("#close-reader-meta").addEventListener("click", () => setReaderMetaOpen(false, true));
$("#reader-meta-backdrop").addEventListener("click", () => setReaderMetaOpen(false, true));
$("#open-revision").addEventListener("click", () => setReaderMetaOpen(false));
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && $("#reader").classList.contains("meta-open")) {
    setReaderMetaOpen(false, true);
  }
});

initI18n();
localizeLanguageOptions();
setTranslationPanelCollapsed(false);

document.addEventListener("margin:locale-changed", () => {
  localizeLanguageOptions();
  if (languageDetectionError) languageDetectionError = t("language.detectionFailed");
  renderSourceLanguageState();
  renderTranslationHistory();
  renderSavedVocabulary();
  refreshNounGenderTitles();
  const shownSource = $("#result").hidden ? "" : $("#detected-language").dataset.language;
  if (shownSource) $("#detected-language").textContent = t("translation.source", { language: languageName(shownSource) });
  setTranslationPanelCollapsed($(".translation-panel").classList.contains("is-collapsed"));
  renderPanelVocabularyToggle();
  renderSuggestions(currentSuggestions);
});

function localizeLanguageOptions() {
  document.querySelectorAll("#source-language option:not([value=auto]), #target-language option").forEach(option => {
    option.textContent = languageName(option.value);
  });
}

document.querySelectorAll("input[type=file]").forEach(input => input.addEventListener("change", event => {
  const file = event.currentTarget.files[0];
  // A file input does not emit another change event when the user picks the
  // same file. Clear it immediately so a PDF can be reopened after reading a
  // web document (or after a failed attempt to load it).
  event.currentTarget.value = "";
  openPdf(file);
}));

async function openPdf(file) {
  if (!file) return;
  prepareDocument(`margin:${file.name}:${file.size}:${file.lastModified}`);
  // Highlights used to be persisted under the document key. Remove that legacy
  // data now that highlights are intentionally transient.
  try { localStorage.removeItem(activeDocumentKey); } catch {}
  const documentKey = activeDocumentKey;
  const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
  if (activeDocumentKey !== documentKey) {
    pdf.destroy();
    return;
  }
  activePdf = pdf;
  $("#empty-state").hidden = true;
  $("#reader").hidden = false;
  $("#pdf-zoom-toolbar").hidden = false;
  applyPdfZoom();
  const pageTexts = [];
  for (let number = 1; number <= pdf.numPages; number += 1) {
    const page = await pdf.getPage(number);
    // A representative prefix is enough for language detection. Do not keep
    // every page's text and bitmap alive merely to build the sample.
    if (pageTexts.join("").length < 12000) {
      const textContent = await page.getTextContent();
      pageTexts.push(pdfText(textContent));
      page.cleanup();
    }
    createPdfPage(page, number);
  }
  documentLanguageSample = pageTexts.join("\n").replace(/\s+/g, " ").trim().slice(0, 12000);
  if (!detectedSourceLanguage) await detectDocumentLanguage();
}

function prepareDocument(documentKey) {
  clearCurrentHighlight();
  setReaderMetaOpen(false);
  pages.querySelectorAll(".pdf-page").forEach(page => {
    pdfPageResizeObserver.unobserve(page);
    pdfPageRenderObserver.unobserve(page);
    releasePdfPage(page);
  });
  activePdf?.destroy();
  activePdf = null;
  activeHls?.destroy();
  activeHls = null;
  pages.replaceChildren();
  $("#pdf-zoom-toolbar").hidden = true;
  pagesScroll.scrollLeft = 0;
  $("#reader").classList.remove("reader-stacked");
  activeDocumentKey = documentKey;
  translations = readStoredTranslations();
  renderTranslationHistory();
  savedVocabulary = [];
  displayedTranslation = null;
  renderSavedVocabulary();
  renderPanelVocabularyToggle();
  selectedText = "";
  selectedContext = "";
  selectedContextOffset = null;
  pendingHighlight = [];
  pendingTranscriptRange = null;
  documentLanguageSample = "";
  languageDetectionPending = false;
  languageDetectionError = "";
  readDocumentLanguageState();
  renderSourceLanguageState();
  if (effectiveSourceLanguage()) loadSavedVocabulary(effectiveSourceLanguage()).catch(() => {});
  $("#selection-hint").hidden = false;
  $("#translation-content").hidden = true;
  $("#result").hidden = true;
  $("#error").textContent = "";
}

async function importWebUrl(url) {
  const response = await fetch("/api/import-web", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || t("error.import", { status: response.status }));
  openWebDocument(data);
  document.querySelectorAll(".web-url-form input[name=url]").forEach(input => { input.value = data.url; });
}

document.querySelectorAll(".web-url-form").forEach(form => form.addEventListener("submit", async event => {
  event.preventDefault();
  const input = form.elements.url;
  const button = form.querySelector("button[type=submit]");
  const url = input.value.trim();
  if (!url) return;
  button.disabled = true;
  button.textContent = t("web.importing");
  setWebImportStatus("");
  try {
    await importWebUrl(url);
  } catch (error) {
    setWebImportStatus(error.message);
  } finally {
    button.disabled = false;
    button.textContent = t(form.classList.contains("topbar-url-form") ? "url.open" : "url.import");
  }
}));

function renderSuggestions(suggestions) {
  const groups = $("#suggestions-groups");
  const status = $("#suggestions-status");
  if (!groups || !status) return;
  const groupDefinitions = [
    ["German", $("#suggestions-german")],
    ["Spanish", $("#suggestions-spanish")],
  ];
  let shown = 0;
  groupDefinitions.forEach(([language, group]) => {
    const list = group.querySelector(".suggestion-list");
    list.replaceChildren();
    const items = suggestions.filter(item => item.language === language);
    group.hidden = items.length === 0;
    shown += items.length;
    items.forEach(item => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "suggestion-card";
      button.dataset.url = item.url;
      const meta = document.createElement("span");
      meta.className = "suggestion-meta";
      const series = document.createElement("span");
      series.textContent = item.series;
      const cefr = document.createElement("span");
      cefr.className = "cefr-badge";
      cefr.textContent = item.cefr;
      const title = document.createElement("span");
      title.className = "suggestion-title";
      title.textContent = item.title;
      meta.append(series, cefr);
      button.append(meta, title);
      list.append(button);
    });
  });
  groups.hidden = shown === 0;
  status.hidden = shown > 0;
  if (shown === 0) status.textContent = t("suggestions.empty");
}

async function loadSuggestions() {
  const status = $("#suggestions-status");
  if (!status) return;
  status.hidden = false;
  status.textContent = t("suggestions.loading");
  try {
    const response = await fetch("/api/suggestions");
    if (!response.ok) throw new Error();
    currentSuggestions = await response.json();
    renderSuggestions(currentSuggestions);
  } catch {
    currentSuggestions = [];
    $("#suggestions-groups").hidden = true;
    status.textContent = t("suggestions.unavailable");
  }
}

$("#suggestions-groups")?.addEventListener("click", async event => {
  const button = event.target.closest(".suggestion-card");
  if (!button) return;
  button.disabled = true;
  setWebImportStatus("");
  try {
    await importWebUrl(button.dataset.url);
  } catch (error) {
    setWebImportStatus(error.message);
  } finally {
    button.disabled = false;
  }
});

loadSuggestions();

document.querySelectorAll(".url-clear-button").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll(".web-url-form input[name=url]").forEach(input => { input.value = ""; });
  setWebImportStatus("");
  $("#error").textContent = "";
  button.closest(".web-url-form")?.elements.url.focus();
}));

function setWebImportStatus(message) {
  document.querySelectorAll(".web-import-status").forEach(node => { node.textContent = message; });
  if (message && $("#reader").hidden === false) $("#error").textContent = message;
}

function openWebDocument(data) {
  prepareDocument(`margin:web:${data.url}`);
  const article = document.createElement("article");
  article.className = "web-document";
  const header = document.createElement("header");
  header.className = "web-document-header";
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  const transcriptKind = data.video_url ? "web.videoTranscript" : "web.audioTranscript";
  eyebrow.dataset.i18n = transcriptKind;
  eyebrow.textContent = t(transcriptKind);
  const title = document.createElement("h1");
  title.textContent = data.title;
  const source = document.createElement("a");
  source.className = "web-source-link";
  source.href = data.url;
  source.target = "_blank";
  source.rel = "noopener noreferrer";
  source.textContent = new URL(data.url).hostname;
  header.append(eyebrow, title, source);
  if (data.video_url) {
    const video = document.createElement("video");
    video.className = "web-video";
    video.controls = true;
    video.preload = "metadata";
    video.playsInline = true;
    if (attachHlsVideo(video, data.video_url)) {
      trackListeningCompletion(video, data);
      header.append(video);
    } else {
      header.append(mediaFallbackNotice(source, "web.noVideoPlayback", "web.watchOriginal"));
    }
  } else if (data.audio_url) {
    const audio = document.createElement("audio");
    audio.className = "web-audio";
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = data.audio_url;
    trackListeningCompletion(audio, data);
    header.append(audio);
  } else {
    header.append(mediaFallbackNotice(source, "web.noDirectAudio", "web.listenOriginal"));
  }
  const transcript = document.createElement("section");
  transcript.className = "web-transcript";
  transcript.dataset.i18nAriaLabel = "web.transcript";
  transcript.setAttribute("aria-label", t("web.transcript"));
  if (data.transcript.length) {
    data.transcript.forEach(value => {
      const paragraph = document.createElement("p");
      paragraph.textContent = value;
      transcript.append(paragraph);
    });
  } else {
    const message = document.createElement("p");
    message.className = "transcript-empty";
    message.dataset.i18n = "web.noTranscript";
    message.textContent = t("web.noTranscript");
    transcript.append(message);
  }
  article.append(header, transcript);
  pages.append(article);
  $("#empty-state").hidden = true;
  $("#reader").hidden = false;
  documentLanguageSample = data.transcript.join(" ").replace(/\s+/g, " ").trim().slice(0, 12000);
  if (!detectedSourceLanguage && data.source_language) {
    detectedSourceLanguage = data.source_language;
    saveDocumentLanguageState();
    loadSavedVocabulary(effectiveSourceLanguage()).catch(() => {});
  }
  renderSourceLanguageState();
  if (!detectedSourceLanguage) detectDocumentLanguage();
}

function trackListeningCompletion(media, data) {
  media.addEventListener("ended", async () => {
    try {
      const response = await fetch("/api/listening-history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: data.url, title: data.title }),
      });
      if (response.ok) await loadSuggestions();
    } catch {
      // Completion tracking is non-blocking; replaying can retry the request.
    }
  }, { once: true });
}

function attachHlsVideo(video, url) {
  // Some Android browsers report native HLS support but leave DW's adaptive
  // master playlists stuck at 0:00. Prefer HLS.js wherever MediaSource is
  // available, and reserve native playback for Safari-style implementations.
  if (window.Hls?.isSupported()) {
    activeHls = new window.Hls({ capLevelToPlayerSize: true, startLevel: 0 });
    activeHls.loadSource(url);
    activeHls.attachMedia(video);
    return true;
  }
  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = url;
    return true;
  }
  return false;
}

function mediaFallbackNotice(source, messageKey, linkKey) {
  const notice = document.createElement("p");
  notice.className = "audio-notice";
  const noticeText = document.createElement("span");
  noticeText.dataset.i18n = messageKey;
  noticeText.textContent = t(messageKey);
  notice.append(noticeText);
  const mediaLink = source.cloneNode(true);
  mediaLink.dataset.i18n = linkKey;
  mediaLink.textContent = t(linkKey);
  notice.append(mediaLink);
  return notice;
}

function createPdfPage(page, number) {
  const baseViewport = page.getViewport({ scale: 1 });
  const viewport = page.getViewport({ scale: Math.min(1.55, 820 / baseViewport.width) });
  const wrapper = document.createElement("article");
  wrapper.className = "pdf-page";
  wrapper.dataset.page = number;
  wrapper.dataset.renderWidth = viewport.width;
  // TextLayer uses this variable for all PDF-space coordinates and font sizes.
  // The stock PDF.js viewer defines it on its viewer container; since this app
  // embeds TextLayer directly, it must provide the viewport scale itself.
  wrapper.style.setProperty("--scale-factor", viewport.scale);
  wrapper.style.setProperty("--pdf-width", `${viewport.width}px`);
  wrapper.style.setProperty("--pdf-height", `${viewport.height}px`);
  wrapper.style.setProperty("--responsive-scale", "1");
  wrapper.style.aspectRatio = `${viewport.width} / ${viewport.height}`;
  const highlightLayer = document.createElement("div");
  highlightLayer.className = "highlight-layer";
  wrapper.append(highlightLayer);
  pages.append(wrapper);
  pdfPageState.set(wrapper, { page, viewport, generation: 0, renderTask: null, rendered: false });
  sizePdfPage(wrapper);
  if (number === 1) updatePdfReaderLayout();
  pdfPageResizeObserver.observe(wrapper);
  pdfPageRenderObserver.observe(wrapper);
}

async function renderPdfPage(wrapper) {
  const state = pdfPageState.get(wrapper);
  if (!state || state.rendered || state.renderTask) return;
  const generation = ++state.generation;
  const { page, viewport } = state;
  const canvas = document.createElement("canvas");
  // Large high-DPI magazine canvases are the dominant memory cost on mobile.
  // The PDF is already rendered wider than most tablet viewports, so 1.5x
  // remains crisp without allowing each page to consume tens of megabytes.
  const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
  canvas.width = Math.ceil(viewport.width * ratio);
  canvas.height = Math.ceil(viewport.height * ratio);
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  wrapper.prepend(canvas);
  try {
    state.renderTask = page.render({
      canvasContext: canvas.getContext("2d"),
      viewport,
      transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0],
    });
    await state.renderTask.promise;
    if (state.generation !== generation || !wrapper.isConnected) return;
    const textContent = await page.getTextContent();
    if (state.generation !== generation || !wrapper.isConnected) return;
    const textLayer = document.createElement("div");
    textLayer.className = "textLayer";
    wrapper.append(textLayer);
    const textLayerTask = new pdfjsLib.TextLayer({ textContentSource: textContent, container: textLayer, viewport });
    await textLayerTask.render();
    if (state.generation !== generation || !wrapper.isConnected) {
      textLayer.remove();
      return;
    }
    // TextLayer pushes exactly one span per text item, in item order, so the
    // two arrays line up index for index.
    textLayerTask.textDivs.forEach((span, index) => textItemForSpan.set(span, textContent.items[index]));
    state.rendered = true;
  } catch (error) {
    if (error?.name !== "RenderingCancelledException") console.error("PDF page rendering failed", error);
  } finally {
    if (state.generation === generation) state.renderTask = null;
  }
}

function releasePdfPage(wrapper) {
  const state = pdfPageState.get(wrapper);
  if (!state) return;
  state.generation += 1;
  state.renderTask?.cancel();
  state.renderTask = null;
  state.rendered = false;
  wrapper.querySelector("canvas")?.remove();
  wrapper.querySelector(".textLayer")?.remove();
  state.page.cleanup();
}

function pdfText(textContent) {
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
  if (event.target.closest(".textLayer, .web-transcript")) {
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
  setTranslationPanelCollapsed(false);
  selectedText = text;
  selectedContext = context;
  selectedContextOffset = contextOffset;
  displayedTranslation = null;
  renderPanelVocabularyToggle();
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
  const transcriptSelection = readTranscriptSelection(range);
  if (transcriptSelection) return transcriptSelection;
  // Pointer-up remeasures selections after even a tiny drag. Keep hyphenated
  // word expansion active for that pass too, or it replaces the complete word
  // captured by selectionchange with only the half under the pointer.
  const measuredRange = expandHyphenatedWordRange(range);
  const selected = selectionGeometry(measuredRange, drag);
  if (selected.text && selected.rectangles.length) {
    return { ...selected, ...selectionContext(measuredRange, selected.text) };
  }
  // Chrome sometimes reports a range whose text is not empty but whose client
  // rectangles are degenerate. Quoting that text would leave the panel showing a
  // phrase with nothing highlighted, so a selection is only accepted when it
  // comes with the geometry to highlight it; otherwise the previous one stands.
  const text = measuredRange.toString().replace(/\s+/g, " ").trim();
  if (!text) return null;
  const rectangles = rangeRectangles(measuredRange);
  return rectangles.length
    ? { text, rectangles, ...selectionContext(measuredRange, text) }
    : null;
}

// PDF producers normally encode a word broken across lines as two ordinary
// text runs with a visible hyphen between them. Native browser word selection
// can only select one run, so expand a one-word selection to the run on the
// other side of a line-ending hyphen. The range still yields two rectangles,
// which is the correct visual representation of one logical word.
function expandHyphenatedWordRange(range) {
  if (range.startContainer.nodeType !== Node.TEXT_NODE || range.endContainer.nodeType !== Node.TEXT_NODE) return range;
  const selected = range.toString().trim();
  if (!/^\p{L}[\p{L}\p{M}]*$/u.test(selected)) return range;

  const startSpan = range.startContainer.parentElement?.closest(".textLayer span");
  const endSpan = range.endContainer.parentElement?.closest(".textLayer span");
  const page = startSpan?.closest(".pdf-page");
  if (!page || page !== endSpan?.closest(".pdf-page")) return range;

  const spans = [...page.querySelectorAll(".textLayer span")];
  const startIndex = spans.indexOf(startSpan);
  const endIndex = spans.indexOf(endSpan);
  const hyphen = "[-\\u00ad\\u2010]";
  const continuation = /^\p{L}[\p{L}\p{M}]*/u;
  const expanded = range.cloneRange();

  const endText = range.endContainer.textContent;
  if (startSpan === endSpan && new RegExp(`^${hyphen}\\s*$`, "u").test(endText.slice(range.endOffset))) {
    const next = adjacentLineSpan(spans, endIndex, 1);
    const match = next?.textContent.match(continuation);
    const textNode = next?.firstChild;
    if (match && textNode?.nodeType === Node.TEXT_NODE) {
      expanded.setEnd(textNode, match[0].length);
      return expanded;
    }
  }

  const startText = range.startContainer.textContent;
  if (startSpan === endSpan && /^\s*$/u.test(startText.slice(0, range.startOffset))) {
    const previous = adjacentLineSpan(spans, startIndex, -1);
    const match = previous?.textContent.match(new RegExp(`(\\p{L}[\\p{L}\\p{M}]*)${hyphen}\\s*$`, "u"));
    const textNode = previous?.firstChild;
    if (match && textNode?.nodeType === Node.TEXT_NODE) {
      expanded.setStart(textNode, match.index);
      return expanded;
    }
  }
  return range;
}

function adjacentLineSpan(spans, index, direction) {
  const origin = spans[index]?.getBoundingClientRect();
  if (!origin) return null;
  for (let candidateIndex = index + direction; candidateIndex >= 0 && candidateIndex < spans.length; candidateIndex += direction) {
    const candidate = spans[candidateIndex];
    if (!candidate.textContent.trim()) continue;
    const rect = candidate.getBoundingClientRect();
    return changedTextLine(rect, origin) ? candidate : null;
  }
  return null;
}

function readTranscriptSelection(range) {
  const start = range.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer : range.startContainer.parentElement;
  const end = range.endContainer.nodeType === Node.ELEMENT_NODE ? range.endContainer : range.endContainer.parentElement;
  const transcript = start?.closest?.(".web-transcript");
  if (!transcript || transcript !== end?.closest?.(".web-transcript")) return null;
  const text = range.toString().replace(/\s+/g, " ").trim();
  if (!text || ![...range.getClientRects()].some(rect => rect.width >= 1 && rect.height >= 1)) return null;
  pendingTranscriptRange = range.cloneRange();
  const paragraph = start.closest("p");
  if (!paragraph || paragraph !== end.closest("p")) {
    return { text, rectangles: [{ transcript: true }], context: "", contextOffset: null };
  }
  const prefix = document.createRange();
  prefix.selectNodeContents(paragraph);
  prefix.setEnd(range.startContainer, range.startOffset);
  const sentence = sentenceContext(paragraph.textContent, text, prefix.toString().length);
  return {
    text,
    rectangles: [{ transcript: true }],
    context: sentence.text.slice(0, 2000),
    contextOffset: sentence.offset,
  };
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
  const selectedEnd = Math.max(start, end);
  const contextSpans = pdfContextSpans(spans, selectedStart, selectedEnd);
  const spanText = span => textItemForSpan.get(span)?.str || span.textContent;
  const offsetWithinSpan = range.startContainer.nodeType === Node.TEXT_NODE
    ? range.startOffset
    : 0;
  let context = "";
  let approximateOffset = 0;
  let previousRect = null;
  contextSpans.forEach(({ span, index }) => {
    const rect = span.getBoundingClientRect();
    const value = spanText(span);
    context = appendPdfText(context, value, rect, previousRect);
    if (index === selectedStart) approximateOffset = context.length - value.length + offsetWithinSpan;
    previousRect = rect;
  });
  const sentence = sentenceContext(context, selectedText, approximateOffset, true);
  return {
    context: sentence.text.slice(0, 2000),
    contextOffset: sentence.offset,
  };
}

// A PDF content stream does not necessarily follow the visual reading order.
// Magazine sidebars and glossaries are commonly interleaved with the article's
// text items, producing one enormous "sentence" with unrelated fragments. Use
// the typography of the selected run to keep the context in the same text flow;
// sentence segmentation can then operate on coherent input.
function pdfContextSpans(spans, selectedStart, selectedEnd) {
  const selectedStyles = new Map();
  for (let index = selectedStart; index <= selectedEnd; index += 1) {
    const item = textItemForSpan.get(spans[index]);
    if (!item?.fontName) continue;
    const height = pdfTextItemHeight(item, spans[index]);
    const heights = selectedStyles.get(item.fontName) || [];
    heights.push(height);
    selectedStyles.set(item.fontName, heights);
  }
  if (!selectedStyles.size) return spans.map((span, index) => ({ span, index }));

  return spans.flatMap((span, index) => {
    const item = textItemForSpan.get(span);
    const selectedHeights = selectedStyles.get(item?.fontName);
    if (!selectedHeights) return [];
    const height = pdfTextItemHeight(item, span);
    const sameTextSize = selectedHeights.some(selectedHeight =>
      selectedHeight > 0 && Math.abs(height - selectedHeight) / selectedHeight <= 0.15
    );
    return sameTextSize ? [{ span, index }] : [];
  });
}

function pdfTextItemHeight(item, span) {
  const transformHeight = Math.hypot(item?.transform?.[2] || 0, item?.transform?.[3] || 0);
  return transformHeight || span.getBoundingClientRect().height;
}

function selectionGeometry(range, drag) {
  const selectionRects = [...range.getClientRects()].filter(rect => rect.width >= 1 && rect.height >= 1);
  if (!selectionRects.length) return { text: "", rectangles: [] };
  const selectionTop = Math.min(...selectionRects.map(rect => rect.top));
  const selectionBottom = Math.max(...selectionRects.map(rect => rect.bottom));
  const rectangles = [];
  let text = "";
  let previousRect = null;
  let previousEndsWithUnselectedHyphen = false;

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
      text = appendPdfText(
        text,
        characters.slice(start, end),
        spanRect,
        previousRect,
        previousEndsWithUnselectedHyphen,
      );
      previousRect = spanRect;
      // A drag can end just before the narrow line-breaking hyphen even though
      // both letter fragments are selected. PDF.js leaves that hyphen in the
      // same text run, outside the measured highlight. Remember it so the next
      // line is joined as one logical word rather than with an invented space.
      previousEndsWithUnselectedHyphen = /^\s*[-\u00ad\u2010]\s*$/u.test(
        characters.slice(end),
      );
    }
  }
  return { text: text.replace(/\s+/g, " ").trim(), rectangles };
}

// PDF text runs carry their own spacing, so joining every run with a space
// splits words that the producer happened to emit in two pieces. Only add one
// where the layout implies a break: a new line, or a visible horizontal gap.
function separatorBefore(spanRect, previousRect) {
  if (!previousRect) return "";
  const changedLine = changedTextLine(spanRect, previousRect);
  return changedLine || spanRect.left - previousRect.right > spanRect.height * 0.2 ? " " : "";
}

function changedTextLine(rect, previousRect) {
  const centre = rect.top + rect.height / 2;
  const previousCentre = previousRect.top + previousRect.height / 2;
  return Math.abs(centre - previousCentre) > Math.min(rect.height, previousRect.height) / 2;
}

function appendPdfText(text, value, rect, previousRect, previousEndsWithUnselectedHyphen = false) {
  const separator = text ? separatorBefore(rect, previousRect) : "";
  if (separator && /^\p{L}/u.test(value)) {
    if (/[-\u00ad\u2010]$/u.test(text)) return text.slice(0, -1) + value;
    if (previousEndsWithUnselectedHyphen) return text + value;
  }
  return text + separator + value;
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

function prepareSourceLanguage(language) {
  const cacheKey = String(language || "").trim().toLocaleLowerCase();
  if (!cacheKey || preparedSourceLanguages.has(cacheKey)) return;
  preparedSourceLanguages.add(cacheKey);
  fetch("/api/prepare-language", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_language: language }),
  }).then(response => {
    if (!response.ok) throw new Error(`Language preparation failed (${response.status})`);
  }).catch(() => {
    // Preparation is an optimization only. Allow a later state render to retry.
    preparedSourceLanguages.delete(cacheKey);
  });
}

function renderSourceLanguageState(message = "") {
  const select = $("#source-language");
  const status = $("#source-language-status");
  select.value = sourceLanguageOverride || "auto";
  if (message) {
    status.textContent = message;
  } else if (sourceLanguageOverride) {
    status.textContent = t("language.usingOverride", { language: languageName(sourceLanguageOverride) });
  } else if (detectedSourceLanguage) {
    status.textContent = t("language.detected", { language: languageName(detectedSourceLanguage) });
  } else if (languageDetectionPending) {
    status.textContent = t("language.detecting");
  } else if (languageDetectionError) {
    status.textContent = languageDetectionError;
  } else {
    status.textContent = t("language.choose");
  }
  const sourceLanguage = effectiveSourceLanguage();
  prepareSourceLanguage(sourceLanguage);
  $("#translate-button").disabled = !selectedText || !sourceLanguage;
  document.dispatchEvent(new CustomEvent("margin:document-language", {
    detail: { language: detectedSourceLanguage },
  }));
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
    if (!response.ok) throw new Error(data.detail || t("error.detection", { status: response.status }));
    if (activeDocumentKey !== documentKey) return;
    detectedSourceLanguage = data.detected_language;
    saveDocumentLanguageState();
    loadSavedVocabulary(effectiveSourceLanguage()).catch(() => {});
  } catch (error) {
    if (activeDocumentKey === documentKey) {
      languageDetectionError = t("language.detectionFailed");
    }
  } finally {
    if (activeDocumentKey === documentKey) {
      languageDetectionPending = false;
      renderSourceLanguageState();
    }
  }
}

$("#source-language").addEventListener("change", async event => {
  sourceLanguageOverride = event.target.value === "auto" ? "" : event.target.value;
  saveDocumentLanguageState();
  renderSourceLanguageState();
  await loadSavedVocabulary(effectiveSourceLanguage()).catch(() => {});
  if (!sourceLanguageOverride && !detectedSourceLanguage) detectDocumentLanguage();
});

const NOUN_GENDERS = new Set(["masculine", "feminine", "neutral"]);
const ARTICLE_GENDERS = {
  german: { der: "masculine", die: "feminine", das: "neutral" },
  spanish: { el: "masculine", la: "feminine" },
  portuguese: { o: "masculine", a: "feminine" },
  italian: { il: "masculine", lo: "masculine", la: "feminine" },
  french: { le: "masculine", la: "feminine" },
  dutch: { het: "neutral" },
};

function nounGenderFor(translation) {
  const supplied = translation.nounGender
    || translation.noun_gender
    || translation.grammatical_gender
    || translation.gender;
  if (NOUN_GENDERS.has(supplied)) return supplied;

  // Older API responses and saved history entries predate noun_gender, but
  // normalized nouns already include their singular definite article.
  const language = String(
    translation.sourceLanguage
    || translation.source_language
    || translation.detectedLanguage
    || translation.detected_language
    || ""
  ).toLocaleLowerCase();
  const source = String(
    translation.normalizedSource
    || translation.normalized_source
    || translation.source
    || ""
  ).trim().toLocaleLowerCase();
  const article = source.match(/^[\p{L}]+/u)?.[0];
  return ARTICLE_GENDERS[language]?.[article] || null;
}

function setNounGender(element, gender) {
  element.classList.remove("noun-masculine", "noun-feminine", "noun-neutral");
  element.removeAttribute("title");
  if (!NOUN_GENDERS.has(gender)) return;
  element.classList.add(`noun-${gender}`);
  element.title = t("gender.title", { gender: t(`gender.${gender}`) });
}

function refreshNounGenderTitles() {
  document.querySelectorAll("#normalized-text, .reader-meta .history-source").forEach(element => {
    const gender = [...NOUN_GENDERS].find(value => element.classList.contains(`noun-${value}`));
    if (gender) setNounGender(element, gender);
  });
}

function showNormalizedResult(source, isWord, nounGender = null) {
  $("#normalized-result").hidden = !isWord;
  const normalizedText = $("#normalized-text");
  normalizedText.textContent = source;
  setNounGender(normalizedText, nounGender);
}

function showSynonymResult(synonyms, visible) {
  const container = $("#synonyms-result");
  const result = $("#synonyms-list");
  container.hidden = !visible;
  result.replaceChildren();
  if (!visible) return;
  if (!synonyms.length) {
    const empty = document.createElement("li");
    empty.className = "synonym-empty";
    empty.textContent = t("synonyms.none");
    result.append(empty);
    return;
  }
  synonyms.forEach(entry => {
    const value = typeof entry === "string" ? { text: entry } : entry;
    const synonym = document.createElement("span");
    synonym.className = "synonym-text";
    synonym.textContent = value.text;
    const item = document.createElement("li");
    item.className = "synonym-result";
    setNounGender(item, value.noun_gender);
    item.append(synonym);
    result.append(item);
  });
}

$("#translate-button").addEventListener("click", async () => {
  const button = $("#translate-button");
  button.disabled = true;
  button.textContent = t("translation.translating");
  $("#error").textContent = "";
  try {
    const sourceLanguage = effectiveSourceLanguage();
    if (!sourceLanguage) throw new Error(t("translation.chooseSource"));
    const payload = {
      text:selectedText,
      source_language:sourceLanguage,
      target_language:$("#target-language").value,
      include_synonyms:true,
      context:selectedContext,
      context_offset:selectedContextOffset,
    };
    const response = await fetch("/api/translate", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload) });
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
      ? await response.json()
      : { detail: await response.text() };

    if (!response.ok) {
      throw new Error(
        data.detail || t("error.translation", { status: response.status })
      );
    }
    $("#detected-language").dataset.language = data.detected_language;
    $("#detected-language").textContent = t("translation.source", { language: languageName(data.detected_language) });
    // The API can resolve a one-word selection to a known multi-word term.
    const isWord = data.is_word === true;
    const nounGender = nounGenderFor({ ...data, sourceLanguage });
    showNormalizedResult(data.normalized_source, isWord, nounGender);
    $("#translated-text").textContent = data.translation;
    showSynonymResult(data.synonyms || [], Array.isArray(data.synonyms));
    $("#result").hidden = false;
    showCurrentHighlight(pendingHighlight);
    displayedTranslation = {
      source: data.normalized_source,
      originalSource: data.original_source || selectedText,
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
      nounGender,
      synonyms: data.synonyms || null,
    };
    saveTranslation(displayedTranslation);
    renderPanelVocabularyToggle();
  } catch (error) { $("#error").textContent = error.message; }
  finally { button.textContent = t("translation.button"); renderSourceLanguageState(); }
});

function showCurrentHighlight(rectangles) {
  if (!rectangles.length) return;
  clearCurrentHighlight();
  if (pendingTranscriptRange && window.Highlight && CSS.highlights) {
    CSS.highlights.set("margin-current-selection", new Highlight(pendingTranscriptRange));
  } else {
    drawHighlight(rectangles);
  }
  pendingHighlight = []; pendingTranscriptRange = null; window.getSelection()?.removeAllRanges();
}

function clearCurrentHighlight() {
  document.querySelectorAll(".highlight-layer").forEach((layer) => layer.replaceChildren());
  CSS.highlights?.delete("margin-current-selection");
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
    nounGender: nounGenderFor(translation),
    synonyms: Array.isArray(translation.synonyms) ? translation.synonyms : [],
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
    noun_gender: item.nounGender,
    synonyms: item.synonyms.map(entry => {
      const synonym = typeof entry === "string" ? { text: entry } : entry;
      return {
        text: synonym.text,
        noun_gender: synonym.noun_gender || synonym.nounGender || null,
      };
    }),
  };
}

function vocabularyFromApi(item) {
  return {
    id: item.id,
    isWord: true,
    schemaVersion: item.schema_version,
    source: item.normalized_source,
    originalSource: item.original_source,
    normalizedSource: item.normalized_source,
    translation: item.translation,
    sourceLanguage: item.source_language,
    targetLanguage: item.target_language,
    context: item.context,
    documentKey: item.document_key,
    nounGender: nounGenderFor(item),
    synonyms: item.synonyms || [],
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
  if (!response.ok) throw new Error(data.detail || t("error.vocabularySave"));
  return vocabularyFromApi(data.item);
}

async function loadSavedVocabulary(language = effectiveSourceLanguage()) {
  const documentKey = activeDocumentKey;
  if (!language) {
    savedVocabulary = [];
    renderTranslationHistory();
    renderSavedVocabulary();
    renderPanelVocabularyToggle();
    return;
  }
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

  const query = language ? `?${new URLSearchParams({ language })}` : "";
  const response = await fetch(`/api/vocabulary${query}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || t("error.vocabularyLoad"));
  if (activeDocumentKey !== documentKey || effectiveSourceLanguage() !== language) return;
  savedVocabulary = data.map(vocabularyFromApi);
  renderTranslationHistory();
  renderSavedVocabulary();
  renderPanelVocabularyToggle();
}

async function toggleSavedVocabulary(translation) {
  const index = savedVocabularyIndex(translation);
  if (index >= 0) {
    const response = await fetch(`/api/vocabulary/${encodeURIComponent(savedVocabulary[index].id)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || t("error.vocabularyRemove"));
    }
  } else {
    await requestVocabulary(translation);
  }
  await loadSavedVocabulary(effectiveSourceLanguage());
}

function renderPanelVocabularyToggle() {
  const button = $("#translation-vocabulary-toggle");
  if (!button) return;
  const translation = displayedTranslation;
  const isWord = translation && (translation.isWord
    ?? String(translation.originalSource || translation.source || "").trim().split(/\s+/).length === 1);
  button.hidden = !isWord;
  if (!isWord) return;
  const word = translation.normalizedSource || translation.source;
  const isSaved = savedVocabularyIndex(translation) >= 0;
  button.setAttribute("aria-pressed", String(isSaved));
  button.setAttribute(
    "aria-label",
    t(isSaved ? "vocabulary.removeAria" : "vocabulary.saveAria", { word }),
  );
  button.title = t(isSaved ? "vocabulary.removeTitle" : "vocabulary.saveTitle");
  $(".translation-vocabulary-icon").textContent = isSaved ? "★" : "☆";
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
  setNounGender(source, nounGenderFor(translation));
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
  saveButton.setAttribute("aria-label", t(isSaved ? "vocabulary.removeAria" : "vocabulary.saveAria", { word: source.textContent }));
  saveButton.title = t(isSaved ? "vocabulary.removeTitle" : "vocabulary.saveTitle");
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

document.addEventListener("margin:vocabulary-removed", event => {
  const itemId = event.detail?.itemId;
  if (!itemId) return;
  savedVocabulary = savedVocabulary.filter(entry => entry.id !== itemId);
  renderSavedVocabulary();
  renderTranslationHistory();
  renderPanelVocabularyToggle();
});

function translationFromControl(control) {
  const collection = control.dataset.translationCollection === "saved" ? savedVocabulary : translations;
  return collection[Number(control.dataset.translationIndex)];
}

function showTranslation(translation) {
  setTranslationPanelCollapsed(false);
  const source = translation.normalizedSource || translation.source;
  const sourceLanguage = translation.sourceLanguage || translation.detectedLanguage;
  selectedText = translation.originalSource || source;
  selectedContext = translation.context || "";
  selectedContextOffset = translation.contextOffset ?? null;
  pendingHighlight = [];
  displayedTranslation = translation;
  $("#selected-text").textContent = translation.originalSource || source;
  $("#target-language").value = translation.targetLanguage;
  $("#detected-language").dataset.language = sourceLanguage;
  $("#detected-language").textContent = t("translation.source", { language: languageName(sourceLanguage) });
  const isWord = translation.isWord
    ?? String(translation.originalSource || source).trim().split(/\s+/).length === 1;
  showNormalizedResult(source, isWord, nounGenderFor(translation));
  $("#translated-text").textContent = translation.translation;
  showSynonymResult(translation.synonyms || [], Array.isArray(translation.synonyms));
  $("#selection-hint").hidden = true;
  $("#translation-content").hidden = false;
  $("#result").hidden = false;
  $("#error").textContent = "";
  renderPanelVocabularyToggle();
}

$("#translation-vocabulary-toggle")?.addEventListener("click", async event => {
  const button = event.currentTarget;
  if (!displayedTranslation) return;
  button.disabled = true;
  $("#error").textContent = "";
  try {
    await toggleSavedVocabulary(displayedTranslation);
  } catch (error) {
    $("#error").textContent = error.message;
  } finally {
    button.disabled = false;
    renderPanelVocabularyToggle();
  }
});

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
  if (translation) {
    showTranslation(translation);
    setReaderMetaOpen(false);
  }
}

$("#translation-history-list")?.addEventListener("click", handleTranslationListClick);
$("#saved-vocabulary-list")?.addEventListener("click", handleTranslationListClick);

$("#clear-translations")?.addEventListener("click", () => {
  translations = [];
  localStorage.removeItem(translationsStorageKey());
  renderTranslationHistory();
});
