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
    patch.mockResolvedValue({
      data: {
        workspace_id: "ws_demo",
        adapter_id: "external_http_tts",
        family_id: "external_http_tts_default",
      },
    });
    del.mockResolvedValue({ data: { status: "deleted", workspace_id: "ws_demo" } });
    const {
      fetchRegistryWorkspaces,
      createRegistryWorkspace,
      patchRegistryWorkspace,
      deleteRegistryWorkspace,
      fetchBindingCatalog,
      fetchRegistryWorkspaceTree,
    } = await import("../src/api/ttsRegistry");

    await fetchRegistryWorkspaces();
    await createRegistryWorkspace({
      adapter_id: "external_http_tts",
      family_id: "external_http_tts_default",
      display_name: "Demo Workspace",
      slug: "demo-workspace",
    });
    await patchRegistryWorkspace("ws_demo", {
      display_name: "Updated Workspace",
      slug: "updated-workspace",
    });
    await deleteRegistryWorkspace("ws_demo");
    await fetchBindingCatalog();
    await fetchRegistryWorkspaceTree("ws_demo");

    expect(get).toHaveBeenCalledWith("/v1/tts-registry/workspaces");
    expect(post).toHaveBeenCalledWith("/v1/tts-registry/workspaces", {
      adapter_id: "external_http_tts",
      family_id: "external_http_tts_default",
      display_name: "Demo Workspace",
      slug: "demo-workspace",
    });
    expect(patch).toHaveBeenCalledWith("/v1/tts-registry/workspaces/ws_demo", {
      display_name: "Updated Workspace",
      slug: "updated-workspace",
    });
    expect(del).toHaveBeenCalledWith("/v1/tts-registry/workspaces/ws_demo");
    expect(get).toHaveBeenCalledWith("/v1/tts-registry/bindings/catalog");
    expect(get).toHaveBeenCalledWith("/v1/tts-registry/workspaces/ws_demo");
  });

  it("main model and submodel helpers use nested workspace routes", async () => {
    post.mockResolvedValue({ data: {} });
    patch.mockResolvedValue({ data: {} });
    put.mockResolvedValue({ data: {} });
    del.mockResolvedValue({ data: {} });
    const {
      createRegistryMainModel,
      patchRegistryMainModel,
      deleteRegistryMainModel,
      createRegistrySubmodel,
      patchRegistrySubmodel,
      deleteRegistrySubmodel,
      putRegistrySubmodelSecrets,
      checkRegistrySubmodelConnectivity,
    } = await import("../src/api/ttsRegistry");

    await createRegistryMainModel("ws_demo", {
      main_model_id: "main_demo",
      display_name: "Main Demo",
      source_type: "external_api",
      main_model_metadata: { provider: "example" },
    });
    await patchRegistryMainModel("ws_demo", "main_demo", {
      display_name: "Main Demo Updated",
      default_submodel_id: "sub_demo",
    });
    await deleteRegistryMainModel("ws_demo", "main_demo");
    await createRegistrySubmodel("ws_demo", "main_demo", {
      submodel_id: "sub_demo",
      display_name: "Sub Demo",
      endpoint: { url: "https://api.example.com/tts" },
      runtime_profile: { timeout_ms: 3000 },
    });
    await patchRegistrySubmodel("ws_demo", "main_demo", "sub_demo", {
      display_name: "Sub Demo Updated",
      adapter_options: { voice: "demo" },
    });
    await putRegistrySubmodelSecrets("ws_demo", "main_demo", "sub_demo", {
      secrets: { api_key: "secret-value" },
    });
    await checkRegistrySubmodelConnectivity("ws_demo", "main_demo", "sub_demo");
    await deleteRegistrySubmodel("ws_demo", "main_demo", "sub_demo");

    expect(post).toHaveBeenCalledWith("/v1/tts-registry/workspaces/ws_demo/main-models", {
      main_model_id: "main_demo",
      display_name: "Main Demo",
      source_type: "external_api",
      main_model_metadata: { provider: "example" },
    });
    expect(patch).toHaveBeenCalledWith("/v1/tts-registry/workspaces/ws_demo/main-models/main_demo", {
      display_name: "Main Demo Updated",
      default_submodel_id: "sub_demo",
    });
    expect(del).toHaveBeenCalledWith("/v1/tts-registry/workspaces/ws_demo/main-models/main_demo");
    expect(post).toHaveBeenCalledWith(
      "/v1/tts-registry/workspaces/ws_demo/main-models/main_demo/submodels",
      {
        submodel_id: "sub_demo",
        display_name: "Sub Demo",
        endpoint: { url: "https://api.example.com/tts" },
        runtime_profile: { timeout_ms: 3000 },
      },
    );
    expect(patch).toHaveBeenCalledWith(
      "/v1/tts-registry/workspaces/ws_demo/main-models/main_demo/submodels/sub_demo",
      {
        display_name: "Sub Demo Updated",
        adapter_options: { voice: "demo" },
      },
    );
    expect(put).toHaveBeenCalledWith(
      "/v1/tts-registry/workspaces/ws_demo/main-models/main_demo/submodels/sub_demo/secrets",
      {
        secrets: { api_key: "secret-value" },
      },
    );
    expect(post).toHaveBeenCalledWith(
      "/v1/tts-registry/workspaces/ws_demo/main-models/main_demo/submodels/sub_demo/connectivity-check",
    );
    expect(del).toHaveBeenCalledWith(
      "/v1/tts-registry/workspaces/ws_demo/main-models/main_demo/submodels/sub_demo",
    );
  });

  it("preset helpers use nested submodel preset routes", async () => {
    post.mockResolvedValue({ data: {} });
    patch.mockResolvedValue({ data: {} });
    del.mockResolvedValue({ data: {} });
    const {
      createRegistryPreset,
      patchRegistryPreset,
      deleteRegistryPreset,
    } = await import("../src/api/ttsRegistry");

    await createRegistryPreset("ws_demo", "main_demo", "sub_demo", {
      preset_id: "voice_a",
      display_name: "Voice A",
      defaults: { speed: 1.0 },
      fixed_fields: { remote_voice_id: "voice_a" },
    });
    await patchRegistryPreset("ws_demo", "main_demo", "sub_demo", "voice_a", {
      display_name: "Voice A Updated",
      preset_assets: { reference_audio: { path: "demo.wav" } },
    });
    await deleteRegistryPreset("ws_demo", "main_demo", "sub_demo", "voice_a");

    expect(post).toHaveBeenCalledWith(
      "/v1/tts-registry/workspaces/ws_demo/main-models/main_demo/submodels/sub_demo/presets",
      {
        preset_id: "voice_a",
        display_name: "Voice A",
        defaults: { speed: 1.0 },
        fixed_fields: { remote_voice_id: "voice_a" },
      },
    );
    expect(patch).toHaveBeenCalledWith(
      "/v1/tts-registry/workspaces/ws_demo/main-models/main_demo/submodels/sub_demo/presets/voice_a",
      {
        display_name: "Voice A Updated",
        preset_assets: { reference_audio: { path: "demo.wav" } },
      },
    );
    expect(del).toHaveBeenCalledWith(
      "/v1/tts-registry/workspaces/ws_demo/main-models/main_demo/submodels/sub_demo/presets/voice_a",
    );
  });
});
