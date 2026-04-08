export type Theme = "light" | "dark";

export const STORAGE_KEY = "gpt-sovits-theme";
export const DEFAULT_THEME: Theme = "dark";

type ClassListLike = {
  add(token: string): void;
  remove(token: string): void;
};

type RootLike = {
  classList: ClassListLike;
} | null;

type StorageLike = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
} | null;

let initializedTheme: Theme | null = null;

function getRoot(): RootLike {
  if (typeof document === "undefined") return null;
  return document.documentElement;
}

function getStorage(): StorageLike {
  if (typeof localStorage === "undefined") return null;
  return localStorage;
}

export function normalizeTheme(rawTheme: string | null | undefined): Theme {
  return rawTheme === "light" ? "light" : DEFAULT_THEME;
}

export function readStoredTheme(storage: StorageLike = getStorage()): Theme {
  return normalizeTheme(storage?.getItem(STORAGE_KEY));
}

export function applyTheme(theme: Theme, root: RootLike = getRoot()) {
  if (!root) return;

  if (theme === "dark") {
    root.classList.add("dark");
    return;
  }

  root.classList.remove("dark");
}

export function persistTheme(theme: Theme, storage: StorageLike = getStorage()) {
  storage?.setItem(STORAGE_KEY, theme);
}

export function commitTheme(theme: Theme): Theme {
  applyTheme(theme);
  persistTheme(theme);
  initializedTheme = theme;
  return theme;
}

export function initializeTheme(): Theme {
  const theme = readStoredTheme();
  return commitTheme(theme);
}

export function getCurrentTheme(): Theme {
  return initializedTheme ?? initializeTheme();
}

export function getNextTheme(theme: Theme): Theme {
  return theme === "dark" ? "light" : "dark";
}
