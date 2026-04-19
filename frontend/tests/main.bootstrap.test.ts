import { beforeEach, describe, expect, it, vi } from "vitest";

const useMock = vi.fn();
const mountMock = vi.fn();
const isReadyMock = vi.fn().mockResolvedValue(undefined);
const installRendererDiagnosticsMock = vi.fn();

vi.mock("vue", () => ({
  createApp: vi.fn(() => ({
    use: useMock,
    mount: mountMock,
  })),
}));

vi.mock("element-plus", () => ({
  default: { name: "element-plus" },
}));

vi.mock("@nuxt/ui/vue-plugin", () => ({
  default: { name: "nuxt-ui" },
}));

vi.mock("../src/App.vue", () => ({
  default: { name: "App" },
}));

vi.mock("../src/router", () => ({
  default: {
    isReady: isReadyMock,
  },
}));

vi.mock("../src/platform/rendererDiagnostics", () => ({
  installRendererDiagnostics: installRendererDiagnosticsMock,
}));

describe("frontend bootstrap", () => {
  beforeEach(() => {
    vi.resetModules();
    useMock.mockClear();
    mountMock.mockClear();
    isReadyMock.mockClear();
    installRendererDiagnosticsMock.mockClear();
    isReadyMock.mockResolvedValue(undefined);
  });

  it("does not install the legacy renderer diagnostics hook during bootstrap", async () => {
    await import("../src/main");
    await Promise.resolve();

    expect(installRendererDiagnosticsMock).not.toHaveBeenCalled();
  });
});
