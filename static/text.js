export function sentenceContaining(text, needle, approximateOffset = null) {
  return sentenceContext(text, needle, approximateOffset).text;
}

export function sentenceContext(
  text,
  needle,
  approximateOffset = null,
  requireComplete = false,
) {
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
  if (requireComplete && !isCompleteSentence(segment)) {
    return { text: "", offset: null };
  }
  const leadingWhitespace = segment.text.length - segment.text.trimStart().length;
  return {
    text: segment.text.trim(),
    offset: Math.max(0, offset - segment.index - leadingWhitespace),
  };
}

function isCompleteSentence(segment) {
  const text = segment.text.trim();
  if (!/[.!?…][”’"')\]]*$/u.test(text)) return false;

  // A first segment that starts in lower case is usually a continuation from
  // the preceding PDF page. Upper-case, numeric, and caseless-script starts are
  // retained because a sentence may legitimately begin at the top of a page.
  if (segment.index === 0) {
    const openingRemoved = text.replace(/^[¿¡“‘"'([\s]+/u, "");
    if (/^\p{Ll}/u.test(openingRemoved)) return false;
  }
  return true;
}

export function renderHighlightedSentence(element, text, needles, prefix = "") {
  element.replaceChildren();
  if (!text) return;
  if (prefix) element.append(document.createTextNode(prefix));

  const terms = needles.filter(Boolean).sort((left, right) => right.length - left.length);
  let matches = null;
  for (const term of terms) {
    const index = findIgnoringCase(text, term);
    if (index >= 0) {
      matches = [{ index, length: term.length }];
      break;
    }
  }
  if (!matches) {
    for (const term of terms) {
      const parts = term.split(/\s+/).filter(Boolean);
      if (parts.length < 2) continue;
      const separated = [];
      let from = 0;
      for (const part of parts) {
        const index = findWholeWordIgnoringCase(text, part, from);
        if (index < 0) {
          separated.length = 0;
          break;
        }
        separated.push({ index, length: part.length });
        from = index + part.length;
      }
      if (separated.length === parts.length) {
        matches = separated;
        break;
      }
    }
  }
  if (!matches) {
    element.append(document.createTextNode(text));
    return;
  }

  let position = 0;
  for (const match of matches) {
    element.append(document.createTextNode(text.slice(position, match.index)));
    const mark = document.createElement("mark");
    mark.textContent = text.slice(match.index, match.index + match.length);
    element.append(mark);
    position = match.index + match.length;
  }
  element.append(document.createTextNode(text.slice(position)));
}

export function renderClozeSentence(element, text, needle, label = "") {
  element.replaceChildren();
  const candidate = String(needle || "").trim();
  const index = findIgnoringCase(text, candidate);
  let matches = index >= 0 ? [{ index, length: candidate.length }] : null;
  if (!matches) {
    const parts = candidate.split(/\s+/).filter(Boolean);
    const separated = [];
    let from = 0;
    for (const part of parts) {
      const partIndex = findWholeWordIgnoringCase(text, part, from);
      if (partIndex < 0) return false;
      separated.push({ index: partIndex, length: part.length });
      from = partIndex + part.length;
    }
    if (separated.length < 2) return false;
    matches = separated;
  }

  let position = 0;
  for (const match of matches) {
    element.append(document.createTextNode(text.slice(position, match.index)));
    const blank = document.createElement("span");
    blank.className = "revision-cloze";
    blank.textContent = "_____";
    if (label) blank.setAttribute("aria-label", label);
    element.append(blank);
    position = match.index + match.length;
  }
  element.append(document.createTextNode(text.slice(position)));
  return true;
}

function findIgnoringCase(text, needle) {
  const candidate = String(needle || "").trim();
  if (!candidate) return -1;
  return text.toLocaleLowerCase().indexOf(candidate.toLocaleLowerCase());
}

function findWholeWordIgnoringCase(text, needle, from = 0) {
  const candidate = String(needle || "").trim();
  if (!candidate) return -1;
  const haystack = text.toLocaleLowerCase();
  const lowered = candidate.toLocaleLowerCase();
  let index = haystack.indexOf(lowered, from);
  while (index >= 0) {
    const before = text[index - 1] || "";
    const after = text[index + candidate.length] || "";
    if (!isWordCharacter(before) && !isWordCharacter(after)) return index;
    index = haystack.indexOf(lowered, index + Math.max(1, lowered.length));
  }
  return -1;
}

function isWordCharacter(value) {
  return Boolean(value) && /[\p{L}\p{M}\p{N}_]/u.test(value);
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
