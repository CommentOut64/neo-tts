import { beforeEach, describe, expect, it, vi } from "vitest";

function createClassList() {
  const classes = new Set<string>();

  return {
    add(token: string) {
      classes.add(token);
    },
    remove(token: string) {
      classes.delete(token);
    },
    contains(token: string) {
      return classes.has(token);
    },
    reset() {
      classes.clear();
    },
  };
}

function createStorage() {
  const store = new Map<string, string>();

  return {
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    setItem(key: string, value: string) {
      store.set(key, value);
    },
    clear() {
      store.clear();
    },
  };
}

async function loadUseThemeModule() {
  vi.resetModules();
  return import("../src/composables/useTheme");
}

describe("useTheme", () => {
  const classList = createClassList();
  const localStorageMock = createStorage();

  beforeEach(() => {
    classList.reset();
    localStorageMock.clear();
    vi.stubGlobal("localStorage", localStorageMock);
    vi.stubGlobal("document", {
      createElement() {
        return {};
      },
      createElementNS() {
        return {};
      },
      createTextNode() {
        return {};
      },
      createComment() {
        return {};
      },
      querySelector() {
        return null;
      },
      documentElement: {
        classList,
      },
    });
  });

  it("切换主题时会立即同步 localStorage，避免刷新后回退到默认深色", async () => {
    localStorage.setItem("gpt-sovits-theme", "dark");

    const { useTheme } = await loadUseThemeModule();
    const theme = useTheme();

    theme.toggleTheme();

    expect(theme.currentTheme.value).toBe("light");
    expect(localStorage.getItem("gpt-sovits-theme")).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
