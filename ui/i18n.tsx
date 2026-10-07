import { useSyncExternalStore } from "react";
import { Languages } from "lucide-react";
import catalogue from "./messages.json";

export type Language = "kk" | "ru" | "en";
const key = "sergek.language";
const messages: Record<string, { kk?: string; ru: string; en: string }> =
  catalogue;
const isLanguage = (value: unknown): value is Language =>
  value === "kk" || value === "ru" || value === "en";
function initialLanguage(): Language {
  try {
    const saved = localStorage.getItem(key);
    return isLanguage(saved) ? saved : "kk";
  } catch {
    return "kk";
  }
}
let language = initialLanguage();
let selectionRevision = 0;
const listeners = new Set<() => void>();
const sources = new Map<string, string>();
for (const [source, translations] of Object.entries(messages)) {
  sources.set(translations.ru, source);
  sources.set(translations.en, source);
}
const prefixes = Object.keys(messages).filter((source) =>
  source.endsWith(": "),
);
export function t(value: string): string {
  if (!messages[value] && !sources.has(value)) {
    for (const prefix of prefixes) {
      for (const variant of [
        prefix,
        messages[prefix].ru,
        messages[prefix].en,
      ]) {
        if (value.startsWith(variant))
          return t(prefix) + value.slice(variant.length);
      }
    }
  }
  const source = messages[value] ? value : sources.get(value) || value;
  return language === "kk"
    ? messages[source]?.kk || source
    : messages[source]?.[language] || value;
}
export function getLanguage(): Language {
  return language;
}
export function getLocale(): string {
  return { kk: "kk-KZ", ru: "ru-RU", en: "en-GB" }[language];
}
export function setLanguage(value: Language) {
  if (!isLanguage(value) || value === language) return;
  language = value;
  selectionRevision++;
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Session selection still works. */
  }
  document.documentElement.lang = value;
  for (const listener of listeners) listener();
  window.sergek?.invoke("set-language", { language: value }).catch(() => {});
}
document.documentElement.lang = language;
if (window.sergek) {
  const revision = selectionRevision;
  window.sergek
    .invoke("get-language")
    .then((saved) => {
      if (selectionRevision === revision && isLanguage(saved.language))
        setLanguage(saved.language);
    })
    .catch(() => {});
}
window.addEventListener("storage", (event) => {
  if (event.key === key && isLanguage(event.newValue))
    setLanguage(event.newValue);
});
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
export function useLanguage() {
  return useSyncExternalStore(subscribe, getLanguage, () => "kk" as Language);
}
export function LanguageSelector() {
  const value = useLanguage();
  return (
    <label className="language-selector">
      <Languages size={17} aria-hidden="true" />
      <select
        aria-label={t("Интерфейс тілі")}
        value={value}
        onChange={(event) => setLanguage(event.target.value as Language)}
      >
        <option value="kk">Қазақша</option>
        <option value="ru">Русский</option>
        <option value="en">English</option>
      </select>
    </label>
  );
}
