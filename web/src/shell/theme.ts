// Light by default even when the device is dark; dark only when chosen in Settings.
export type Theme = "light" | "dark";
const KEY = "theme";

export function getTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function applyTheme(theme: Theme = getTheme()): void {
  document.documentElement.dataset.theme = theme;
}

export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // private mode: the choice lasts for this visit
  }
  applyTheme(theme);
}
