import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const patch = vi.fn();
const del = vi.fn();

vi.mock("../src/api/http", () => ({
  default: {
    get,
    post,
    put,
    patch,
    delete: del,
  },
}));

function resolveFromTests(relativePath: string) {
  return resolve(dirname(fileURLToPath(import.meta.url)), relativePath);
}

const ttsRegistryApiSource = readFileSync(resolveFromTests("../src/api/ttsRegistry.ts"), "utf8");

describe("ttsRegistry api", () => {
  beforeEach(() => {
    vi.resetModules();
    get.mockReset();
    post.mockReset();
    put.mockReset();
    patch.mockReset();
    del.mockReset();
  });

  it("formal registry api no longer exposes flat model routes", () => {
    expect(ttsRegistryApiSource).not.toContain("/v1/tts-registry/models");
    expect(ttsRegistryApiSource).not.toContain("/v1/tts-registry/reload");
    expect(ttsRegistryApiSource).not.toContain("createExternalModel");
    expect(ttsRegistryApiSource).not.toContain("createModelPreset");
    expect(ttsRegistryApiSource).not.toContain("putModelSecrets");
  });

  it("workspace-oriented helpers use registry workspace routes", async () => {
    get.mockResolvedValue({ data: [] });
    post.mockResolvedValue({
      data: {
        workspace_id: "ws_demo",
        adapter_id: "external_http_tts",
        family_id: "external_http_tts_default",
      },
    });
    const { fetchRegistryWorkspaces, createRegistryWorkspace, fetchBindingCatalog } = await import("../src/api/ttsRegistry");

    await fetchRegistryWorkspaces();
    await createRegistryWorkspace({
      adapter_id: "external_http_tts",
      family_id: "external_http_tts_default",
      display_name: "Demo Workspace",
      slug: "demo-workspace",
    });
    await fetchBindingCatalog();

    expect(get).toHaveBeenCalledWith("/v1/tts-registry/workspaces");
    expect(post).toHaveBeenCalledWith("/v1/tts-registry/workspaces", {
      adapter_id: "external_http_tts",
      family_id: "external_http_tts_default",
      display_name: "Demo Workspace",
      slug: "demo-workspace",
    });
    expect(get).toHaveBeenCalledWith("/v1/tts-registry/bindings/catalog");
  });
});
