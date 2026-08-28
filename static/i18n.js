const STORAGE_KEY = "margin:interface-language:v1";

const messages = {
  en: {
    "meta.title": "Margin — PDF language reader with audio transcripts",
    "brand.home": "Margin home",
    "brand.tagline": "Language reader",
    "locale.label": "Interface language",
    "url.label": "Article or transcript URL",
    "url.placeholder": "Paste an article URL",
    "url.clear": "Clear URL",
    "url.open": "Open URL",
    "url.import": "Import page",
    "revision.open": "Revise vocabulary",
    "pdf.open": "Open PDF",
    "revision.eyebrow": "Spaced repetition",
    "revision.title": "Vocabulary revision",
    "revision.language": "Language",
    "revision.languageAria": "Vocabulary language",
    "revision.selectLanguage": "Select language",
    "revision.close": "Close",
    "revision.preparing": "Preparing your due words…",
    "revision.nothingDue": "Nothing due right now",
    "revision.savePrompt": "Save vocabulary while reading to build future revision sessions.",
    "revision.remove": "Remove from revision",
    "revision.typeAnswer": "Type your answer",
    "revision.check": "Check answer",
    "revision.continue": "Continue",
    "hero.title": "Turn foreign-language reading into lasting knowledge.",
    "hero.intro": "Open a PDF or import an audio article with a transcript. Select any word or phrase and translate it without leaving the page.",
    "pdf.choose": "Choose a PDF",
    "common.or": "or",
    "url.emptyLabel": "Article or transcript URL",
    "common.clear": "Clear",
    "common.close": "Close",
    "library.open": "Saved & history",
    "library.title": "Reading library",
    "library.close": "Close library",
    "vocabulary.saved": "Saved vocabulary",
    "vocabulary.empty": "Save translated words for later revision.",
    "vocabulary.add": "Add a word",
    "vocabulary.addTitle": "Add a word",
    "vocabulary.sourceLanguage": "Word language",
    "vocabulary.targetLanguage": "Translation language",
    "vocabulary.word": "Word",
    "vocabulary.translation": "Translation",
    "vocabulary.translationOptional": "Leave blank to translate automatically",
    "vocabulary.addButton": "Add to vocabulary",
    "vocabulary.adding": "Adding…",
    "history.title": "Translation history",
    "history.empty": "Translations you create will appear here.",
    "history.clear": "Clear",
    "document.content": "Document content",
    "translation.title": "Translation",
    "translation.hint": "Select text in the document to begin.",
    "translation.original": "Original",
    "translation.sourceLanguage": "Source language",
    "translation.autoDetect": "Auto-detect",
    "translation.targetLanguage": "Translate to",
    "translation.button": "Translate selection",
    "translation.normalized": "Normalized",
    "translation.result": "Translation",
    "synonyms.result": "Synonyms",
    "synonyms.none": "No suitable synonyms found in this context.",
    "web.audioTranscript": "Audio transcript",
    "web.noDirectAudio": "This site does not expose a direct audio file. ",
    "web.listenOriginal": "Listen on the original page",
    "web.transcript": "Transcript",
    "web.noTranscript": "No transcript could be found on this page, but you can still play its audio.",
    "web.importing": "Importing…",
    "error.import": "Page import failed ({status})",
    "error.detection": "Language detection failed ({status})",
    "language.usingOverride": "Using {language} (manual override)",
    "language.detected": "Detected {language} for this document",
    "language.detecting": "Detecting document language…",
    "language.detectionFailed": "Automatic detection failed; choose the source language",
    "language.choose": "Choose a language to translate",
    "gender.title": "{gender} noun",
    "gender.masculine": "Masculine",
    "gender.feminine": "Feminine",
    "gender.neutral": "Neutral",
    "translation.translating": "Translating…",
    "translation.chooseSource": "Choose the document's source language first",
    "error.translation": "Translation failed ({status})",
    "error.synonyms": "Synonym lookup failed ({status})",
    "translation.source": "Source {language}",
    "error.vocabularySave": "Vocabulary could not be saved",
    "error.vocabularyLoad": "Saved vocabulary could not be loaded",
    "error.vocabularyRemove": "Saved vocabulary could not be removed",
    "vocabulary.removeAria": "Remove {word} from saved vocabulary",
    "vocabulary.saveAria": "Save {word} for revision",
    "vocabulary.removeTitle": "Remove from saved vocabulary",
    "vocabulary.saveTitle": "Save for revision",
    "revision.languagesLoadError": "Languages could not be loaded",
    "revision.chooseLanguage": "Select a language",
    "revision.chooseLanguageCopy": "Choose a saved vocabulary language to begin revising.",
    "revision.loadError": "Revision could not be loaded",
    "revision.caughtUp": "You are caught up. Save vocabulary while reading to build future revision sessions.",
    "revision.sessionComplete": "Session complete",
    "revision.answers": "{correct} of {answered} answers were correct.",
    "revision.noAnswers": "No answers were recorded.",
    "revision.removal.one": " {count} word removed from revision.",
    "revision.removal.other": " {count} words removed from revision.",
    "revision.word.one": "word",
    "revision.word.other": "words",
    "revision.thisWord": "this word",
    "revision.confirmRemove": "Remove “{word}” from saved vocabulary and revision?",
    "revision.removeError": "The word could not be removed",
    "revision.removed": "Removed from revision",
    "revision.answerSaveError": "Answer could not be saved",
    "revision.correct": "Correct",
    "revision.incorrect": "Not quite — the answer is {answer}.",
    "revision.fromText": "From the text: ",
    "revision.progress": "{answered} answered · {remaining} remaining",
    "revision.score": "{count} correct",
    "revision.removedCount": "{count} removed",
    "revision.category.new": "new",
    "revision.category.needs_practice": "needs practice",
    "revision.category.usually_correct": "usually correct",
    "revision.category.always_correct": "always correct"
  },
  es: {
    "meta.title": "Margin — lector de PDF para aprender idiomas con transcripciones de audio",
    "brand.home": "Inicio de Margin",
    "brand.tagline": "Lector de idiomas",
    "locale.label": "Idioma de la interfaz",
    "url.label": "URL del artículo o de la transcripción",
    "url.placeholder": "Pega la URL de un artículo",
    "url.clear": "Borrar URL",
    "url.open": "Abrir URL",
    "url.import": "Importar página",
    "revision.open": "Repasar vocabulario",
    "pdf.open": "Abrir PDF",
    "revision.eyebrow": "Repetición espaciada",
    "revision.title": "Repaso de vocabulario",
    "revision.language": "Idioma",
    "revision.languageAria": "Idioma del vocabulario",
    "revision.selectLanguage": "Selecciona un idioma",
    "revision.close": "Cerrar",
    "revision.preparing": "Preparando las palabras pendientes…",
    "revision.nothingDue": "No hay nada pendiente ahora",
    "revision.savePrompt": "Guarda vocabulario mientras lees para crear futuras sesiones de repaso.",
    "revision.remove": "Quitar del repaso",
    "revision.typeAnswer": "Escribe tu respuesta",
    "revision.check": "Comprobar respuesta",
    "revision.continue": "Continuar",
    "hero.title": "Convierte la lectura en otros idiomas en conocimiento duradero.",
    "hero.intro": "Abre un PDF o importa un artículo con audio y transcripción. Selecciona cualquier palabra o frase y tradúcela sin salir de la página.",
    "pdf.choose": "Elegir un PDF",
    "common.or": "o",
    "url.emptyLabel": "URL del artículo o de la transcripción",
    "common.clear": "Borrar",
    "common.close": "Cerrar",
    "library.open": "Guardado e historial",
    "library.title": "Biblioteca de lectura",
    "library.close": "Cerrar biblioteca",
    "vocabulary.saved": "Vocabulario guardado",
    "vocabulary.empty": "Guarda palabras traducidas para repasarlas más adelante.",
    "vocabulary.add": "Añadir palabra",
    "vocabulary.addTitle": "Añadir una palabra",
    "vocabulary.sourceLanguage": "Idioma de la palabra",
    "vocabulary.targetLanguage": "Idioma de la traducción",
    "vocabulary.word": "Palabra",
    "vocabulary.translation": "Traducción",
    "vocabulary.translationOptional": "Déjala en blanco para traducir automáticamente",
    "vocabulary.addButton": "Añadir al vocabulario",
    "vocabulary.adding": "Añadiendo…",
    "history.title": "Historial de traducciones",
    "history.empty": "Las traducciones que hagas aparecerán aquí.",
    "history.clear": "Borrar",
    "document.content": "Contenido del documento",
    "translation.title": "Traducción",
    "translation.hint": "Selecciona texto en el documento para empezar.",
    "translation.original": "Original",
    "translation.sourceLanguage": "Idioma de origen",
    "translation.autoDetect": "Detectar automáticamente",
    "translation.targetLanguage": "Traducir a",
    "translation.button": "Traducir selección",
    "translation.normalized": "Forma normalizada",
    "translation.result": "Traducción",
    "synonyms.result": "Sinónimos",
    "synonyms.none": "No se encontraron sinónimos adecuados para este contexto.",
    "web.audioTranscript": "Transcripción de audio",
    "web.noDirectAudio": "Este sitio no ofrece un archivo de audio directo. ",
    "web.listenOriginal": "Escuchar en la página original",
    "web.transcript": "Transcripción",
    "web.noTranscript": "No se encontró ninguna transcripción en esta página, pero aún puedes reproducir el audio.",
    "web.importing": "Importando…",
    "error.import": "No se pudo importar la página ({status})",
    "error.detection": "No se pudo detectar el idioma ({status})",
    "language.usingOverride": "Usando {language} (selección manual)",
    "language.detected": "Se ha detectado {language} en este documento",
    "language.detecting": "Detectando el idioma del documento…",
    "language.detectionFailed": "La detección automática ha fallado; elige el idioma de origen",
    "language.choose": "Elige un idioma para traducir",
    "gender.title": "Sustantivo {gender}",
    "gender.masculine": "masculino",
    "gender.feminine": "femenino",
    "gender.neutral": "neutro",
    "translation.translating": "Traduciendo…",
    "translation.chooseSource": "Elige primero el idioma de origen del documento",
    "error.translation": "La traducción ha fallado ({status})",
    "error.synonyms": "La búsqueda de sinónimos ha fallado ({status})",
    "translation.source": "Origen: {language}",
    "error.vocabularySave": "No se pudo guardar el vocabulario",
    "error.vocabularyLoad": "No se pudo cargar el vocabulario guardado",
    "error.vocabularyRemove": "No se pudo quitar el vocabulario guardado",
    "vocabulary.removeAria": "Quitar {word} del vocabulario guardado",
    "vocabulary.saveAria": "Guardar {word} para repasarlo",
    "vocabulary.removeTitle": "Quitar del vocabulario guardado",
    "vocabulary.saveTitle": "Guardar para repasar",
    "revision.languagesLoadError": "No se pudieron cargar los idiomas",
    "revision.chooseLanguage": "Selecciona un idioma",
    "revision.chooseLanguageCopy": "Elige el idioma de un vocabulario guardado para empezar a repasar.",
    "revision.loadError": "No se pudo cargar el repaso",
    "revision.caughtUp": "Estás al día. Guarda vocabulario mientras lees para crear futuras sesiones de repaso.",
    "revision.sessionComplete": "Sesión completada",
    "revision.answers": "{correct} de {answered} respuestas fueron correctas.",
    "revision.noAnswers": "No se registró ninguna respuesta.",
    "revision.removal.one": " Se quitó {count} palabra del repaso.",
    "revision.removal.other": " Se quitaron {count} palabras del repaso.",
    "revision.word.one": "palabra",
    "revision.word.other": "palabras",
    "revision.thisWord": "esta palabra",
    "revision.confirmRemove": "¿Quitar «{word}» del vocabulario guardado y del repaso?",
    "revision.removeError": "No se pudo quitar la palabra",
    "revision.removed": "Quitada del repaso",
    "revision.answerSaveError": "No se pudo guardar la respuesta",
    "revision.correct": "Correcto",
    "revision.incorrect": "Casi — la respuesta es {answer}.",
    "revision.fromText": "Del texto: ",
    "revision.progress": "{answered} respondidas · {remaining} restantes",
    "revision.score": "{count} correctas",
    "revision.removedCount": "{count} eliminadas",
    "revision.category.new": "nueva",
    "revision.category.needs_practice": "necesita práctica",
    "revision.category.usually_correct": "normalmente correcta",
    "revision.category.always_correct": "siempre correcta"
  }
};

const languageNames = {
  en: { English: "English", German: "German", Spanish: "Spanish", French: "French", Italian: "Italian", Portuguese: "Portuguese", Dutch: "Dutch", Polish: "Polish", Japanese: "Japanese", Korean: "Korean", "Chinese (Simplified)": "Chinese (Simplified)" },
  es: { English: "inglés", German: "alemán", Spanish: "español", French: "francés", Italian: "italiano", Portuguese: "portugués", Dutch: "neerlandés", Polish: "polaco", Japanese: "japonés", Korean: "coreano", "Chinese (Simplified)": "chino (simplificado)" }
};

let locale = readLocale();

function readLocale() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (messages[stored]) return stored;
  } catch {}
  return "en";
}

export function t(key, values = {}) {
  const template = messages[locale]?.[key] ?? messages.en[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? `{${name}}`);
}

export function languageName(language) {
  return languageNames[locale]?.[language] || language;
}

export function currentLocale() {
  return locale;
}

export function applyTranslations(root = document) {
  root.querySelectorAll("[data-i18n]").forEach(element => {
    element.textContent = t(element.dataset.i18n);
  });
  root.querySelectorAll("[data-i18n-placeholder]").forEach(element => {
    element.placeholder = t(element.dataset.i18nPlaceholder);
  });
  root.querySelectorAll("[data-i18n-aria-label]").forEach(element => {
    element.setAttribute("aria-label", t(element.dataset.i18nAriaLabel));
  });
  root.querySelectorAll("[data-i18n-title]").forEach(element => {
    element.title = t(element.dataset.i18nTitle);
  });
  document.documentElement.lang = locale;
  document.title = t("meta.title");
}

export function setLocale(nextLocale) {
  if (!messages[nextLocale]) return;
  locale = nextLocale;
  try { localStorage.setItem(STORAGE_KEY, locale); } catch {}
  applyTranslations();
  const selector = document.querySelector("#interface-language");
  if (selector) selector.value = locale;
  document.dispatchEvent(new CustomEvent("margin:locale-changed", { detail: { locale } }));
}

export function initI18n() {
  const selector = document.querySelector("#interface-language");
  if (selector) {
    selector.value = locale;
    selector.addEventListener("change", event => setLocale(event.target.value));
  }
  applyTranslations();
}
