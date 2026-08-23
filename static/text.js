export function sentenceContaining(text, needle, approximateOffset = null) {
  const cleanText = String(text || "").replace(/\s+/g, " ").trim();
  if (!cleanText) return "";

  let offset = findIgnoringCase(cleanText, needle);
  if (offset < 0 && Number.isFinite(approximateOffset)) {
    offset = Math.max(0, Math.min(approximateOffset, cleanText.length - 1));
  }
  if (offset < 0) return cleanText;

  const segments = sentenceSegments(cleanText);
  return segments.find(segment =>
    offset >= segment.index && offset < segment.index + segment.text.length
  )?.text.trim() || cleanText;
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

function findIgnoringCase(text, needle) {
  const candidate = String(needle || "").trim();
  if (!candidate) return -1;
  return text.toLocaleLowerCase().indexOf(candidate.toLocaleLowerCase());
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
