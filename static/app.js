import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.worker.min.mjs";
const $ = (selector) => document.querySelector(selector);
const pages = $("#pages");
let selectedText = "";
let activeDocumentKey = "";
let pendingHighlight = [];
const textItemForSpan = new WeakMap();
const characterOffsetsForSpan = new WeakMap();
const measurementContext = document.createElement("canvas").getContext("2d");
let selectionDragStart = null;

document.querySelectorAll("input[type=file]").forEach((input) => input.addEventListener("change", (event) => openPdf(event.target.files[0])));

async function openPdf(file) {
  if (!file) return;
  pages.replaceChildren();
  activeDocumentKey = `margin:${file.name}:${file.size}:${file.lastModified}`;
  const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
  $("#document-name").textContent = file.name.replace(/\.pdf$/i, "");
  $("#page-count").textContent = `${pdf.numPages} page${pdf.numPages === 1 ? "" : "s"}`;
  $("#empty-state").hidden = true;
  $("#reader").hidden = false;
  for (let number = 1; number <= pdf.numPages; number += 1) await renderPage(await pdf.getPage(number), number);
  restoreHighlights();
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
}

document.addEventListener("selectionchange", () => {
  const selection = window.getSelection();
  if (!selection?.rangeCount || !pages.contains(selection.anchorNode) || !pages.contains(selection.focusNode)) return;
  const selected = readSelection(selection.getRangeAt(0));
  if (selected) showSelection(selected);
});

pages.addEventListener("pointerdown", event => {
  if (event.button === 0 && event.target.closest(".textLayer")) {
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

function showSelection({ text, rectangles }) {
  selectedText = text;
  $("#selected-text").textContent = text;
  $("#selection-hint").hidden = true;
  $("#translation-content").hidden = false;
  $("#result").hidden = true;
  $("#error").textContent = "";
  pendingHighlight = rectangles;
}

// The quoted text and the highlight have to come out of a single measurement
// pass. Deriving the text from glyph geometry while taking the highlight from
// the native Range makes the two disagree by however much the two coordinate
// models differ, which is exactly the mismatch this replaces.
function readSelection(range, drag = null) {
  const selected = selectionGeometry(range, drag);
  if (selected.text && selected.rectangles.length) return selected;
  // Chrome sometimes reports a range whose text is not empty but whose client
  // rectangles are degenerate. Quoting that text would leave the panel showing a
  // phrase with nothing highlighted, so a selection is only accepted when it
  // comes with the geometry to highlight it; otherwise the previous one stands.
  const text = range.toString().replace(/\s+/g, " ").trim();
  if (!text) return null;
  const rectangles = rangeRectangles(range);
  return rectangles.length ? { text, rectangles } : null;
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

$("#translate-button").addEventListener("click", async () => {
  const button = $("#translate-button");
  button.disabled = true; button.textContent = "Translating…"; $("#error").textContent = "";
  try {
    const response = await fetch("/api/translate", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ text:selectedText, target_language:$("#target-language").value }) });
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
      ? await response.json()
      : { detail: await response.text() };

    if (!response.ok) {
      throw new Error(
        data.detail || `Translation failed (${response.status})`
      );
    }
    $("#detected-language").textContent = `Detected ${data.detected_language}`;
    $("#translated-text").textContent = data.translation;
    $("#result").hidden = false;
    saveHighlight(pendingHighlight);
  } catch (error) { $("#error").textContent = error.message; }
  finally { button.disabled = false; button.textContent = "Translate selection"; }
});

function saveHighlight(rectangles) {
  if (!rectangles.length) return;
  const stored = JSON.parse(localStorage.getItem(activeDocumentKey) || "[]");
  stored.push(rectangles); localStorage.setItem(activeDocumentKey, JSON.stringify(stored));
  drawHighlight(rectangles); pendingHighlight = []; window.getSelection()?.removeAllRanges();
}
function drawHighlight(rectangles) {
  for (const rect of rectangles) {
    const mark = document.createElement("span");
    mark.style.cssText = `left:${rect.x*100}%;top:${rect.y*100}%;width:${rect.width*100}%;height:${rect.height*100}%`;
    document.querySelector(`.pdf-page[data-page="${rect.page}"] .highlight-layer`)?.append(mark);
  }
}
function restoreHighlights() { for (const rectangles of JSON.parse(localStorage.getItem(activeDocumentKey) || "[]")) drawHighlight(rectangles); }
$("#clear-highlights").addEventListener("click", () => { localStorage.removeItem(activeDocumentKey); document.querySelectorAll(".highlight-layer").forEach((layer) => layer.replaceChildren()); });
