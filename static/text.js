export function sentenceContaining(text, needle, approximateOffset = null) {
  return sentenceContext(text, needle, approximateOffset).text;
}

export function sentenceContext(text, needle, approximateOffset = null) {
  const cleanText = String(text || "").replace(/\s+/g, " ").trim();
  if (!cleanText) return { text: "", offset: null };

  let offset = closestMatchIgnoringCase(cleanText, needle, approximateOffset);
  if (offset < 0 && Number.isFinite(approximateOffset)) {
    offset = Math.max(0, Math.min(approximateOffset, cleanText.length - 1));
  }
  if (offset < 0) return { text: cleanText, offset: null };

  const segments = sentenceSegments(cleanText);
  const segment = segments.find(segment =>
    offset >= segment.index && offset < segment.index + segment.text.length
  );
  if (!segment) return { text: cleanText, offset };
  const leadingWhitespace = segment.text.length - segment.text.trimStart().length;
  return {
    text: segment.text.trim(),
    offset: Math.max(0, offset - segment.index - leadingWhitespace),
  };
}

export function renderHighlightedSentence(element, text, needles, prefix = "") {
  element.replaceChildren();
  if (!text) return;
  if (prefix) element.append(document.createTextNode(prefix));

  const terms = needles.filter(Boolean).sort((left, right) => right.length - left.length);
  let match = null;
  for (const term of terms) {
    const index = findIgnoringCase(text, term);
    if (index >= 0) {
      match = { index, length: term.length };
      break;
    }
  }
  if (!match) {
    element.append(document.createTextNode(text));
    return;
  }

  element.append(document.createTextNode(text.slice(0, match.index)));
  const mark = document.createElement("mark");
  mark.textContent = text.slice(match.index, match.index + match.length);
  element.append(mark, document.createTextNode(text.slice(match.index + match.length)));
}

export function renderClozeSentence(element, text, needle, label = "") {
  element.replaceChildren();
  const candidate = String(needle || "").trim();
  const index = findIgnoringCase(text, candidate);
  if (index < 0) return false;

  element.append(document.createTextNode(text.slice(0, index)));
  const blank = document.createElement("span");
  blank.className = "revision-cloze";
  blank.textContent = "_____";
  if (label) blank.setAttribute("aria-label", label);
  element.append(blank, document.createTextNode(text.slice(index + candidate.length)));
  return true;
}

function findIgnoringCase(text, needle) {
  const candidate = String(needle || "").trim();
  if (!candidate) return -1;
  return text.toLocaleLowerCase().indexOf(candidate.toLocaleLowerCase());
}

function closestMatchIgnoringCase(text, needle, approximateOffset) {
  const candidate = String(needle || "").trim().toLocaleLowerCase();
  if (!candidate) return -1;
  const haystack = text.toLocaleLowerCase();
  const matches = [];
  let from = 0;
  while (from <= haystack.length - candidate.length) {
    const match = haystack.indexOf(candidate, from);
    if (match < 0) break;
    matches.push(match);
    from = match + Math.max(1, candidate.length);
  }
  if (!matches.length) return -1;
  if (!Number.isFinite(approximateOffset)) return matches[0];
  return matches.reduce((closest, match) =>
    Math.abs(match - approximateOffset) < Math.abs(closest - approximateOffset)
      ? match
      : closest
  );
}

function sentenceSegments(text) {
  if (typeof Intl.Segmenter === "function") {
    const segmenter = new Intl.Segmenter(undefined, { granularity: "sentence" });
    return [...segmenter.segment(text)].map(segment => ({
      text: segment.segment,
      index: segment.index,
    }));
  }

  const segments = [];
  const expression = /[^.!?]+(?:[.!?]+[”’"')\]]*|$)/g;
  for (const match of text.matchAll(expression)) {
    segments.push({ text: match[0], index: match.index });
  }
  return segments.length ? segments : [{ text, index: 0 }];
}
