import { describe, expect, it } from "vitest";

import {
  buildScopedRegistryIdentifier,
  pickInitialWorkspaceSelection,
  restoreWorkspaceSelection,
} from "../src/composables/useModelWorkspaceAdmin";
import type { TtsRegistryWorkspaceTree } from "../src/types/ttsRegistry";

function buildWorkspaceTree(overrides: Partial<TtsRegistryWorkspaceTree> = {}): TtsRegistryWorkspaceTree {
  return {
    workspace: {
      workspace_id: "ws_demo",
      adapter_id: "external_http_tts",
      family_id: "external_http_tts_default",
      display_name: "Demo Workspace",
      slug: "demo-workspace",
      status: "ready",
    },
    main_models: [],
    ...overrides,
  };
}

describe("useModelWorkspaceAdmin", () => {
  it("builds a stable scoped identifier from display names and keeps it unique", () => {
    expect(
      buildScopedRegistryIdentifier({
        displayName: "Main Model Alpha",
        existingIds: ["main_model_alpha"],
        fallbackBaseId: "main_model",
      }),
    ).toBe("main_model_alpha_2");
  });

  it("selects the first available main model and submodel by default", () => {
    const tree = buildWorkspaceTree({
      main_models: [
        {
          main_model_id: "main_a",
          workspace_id: "ws_demo",
          display_name: "Main A",
          status: "ready",
          source_type: "builtin",
          main_model_metadata: {},
          default_submodel_id: null,
          submodels: [
            {
              submodel_id: "sub_a",
              workspace_id: "ws_demo",
              main_model_id: "main_a",
              display_name: "Sub A",
              status: "ready",
              instance_assets: {},
              endpoint: null,
              account_binding: null,
              adapter_options: {},
              runtime_profile: {},
              is_hidden_singleton: false,
              presets: [],
            },
          ],
        },
      ],
    });

    expect(pickInitialWorkspaceSelection(tree)).toEqual({
      selectedMainModelId: "main_a",
      selectedSubmodelId: "sub_a",
    });
  });

  it("restores selection to the next available sibling when the current node disappears", () => {
    const previousTree = buildWorkspaceTree({
      main_models: [
        {
          main_model_id: "main_a",
          workspace_id: "ws_demo",
          display_name: "Main A",
          status: "ready",
          source_type: "builtin",
          main_model_metadata: {},
          default_submodel_id: null,
          submodels: [],
        },
        {
          main_model_id: "main_b",
          workspace_id: "ws_demo",
          display_name: "Main B",
          status: "ready",
          source_type: "builtin",
          main_model_metadata: {},
          default_submodel_id: null,
          submodels: [
            {
              submodel_id: "sub_b1",
              workspace_id: "ws_demo",
              main_model_id: "main_b",
              display_name: "Sub B1",
              status: "ready",
              instance_assets: {},
              endpoint: null,
              account_binding: null,
              adapter_options: {},
              runtime_profile: {},
              is_hidden_singleton: false,
              presets: [],
            },
            {
              submodel_id: "sub_b2",
              workspace_id: "ws_demo",
              main_model_id: "main_b",
              display_name: "Sub B2",
              status: "ready",
              instance_assets: {},
              endpoint: null,
              account_binding: null,
              adapter_options: {},
              runtime_profile: {},
              is_hidden_singleton: false,
              presets: [],
            },
          ],
        },
      ],
    });
    const nextTree = buildWorkspaceTree({
      main_models: [
        {
          main_model_id: "main_b",
          workspace_id: "ws_demo",
          display_name: "Main B",
          status: "ready",
          source_type: "builtin",
          main_model_metadata: {},
          default_submodel_id: null,
          submodels: [
            {
              submodel_id: "sub_b1",
              workspace_id: "ws_demo",
              main_model_id: "main_b",
              display_name: "Sub B1",
              status: "ready",
              instance_assets: {},
              endpoint: null,
              account_binding: null,
              adapter_options: {},
              runtime_profile: {},
              is_hidden_singleton: false,
              presets: [],
            },
            {
              submodel_id: "sub_b2",
              workspace_id: "ws_demo",
              main_model_id: "main_b",
              display_name: "Sub B2",
              status: "ready",
              instance_assets: {},
              endpoint: null,
              account_binding: null,
              adapter_options: {},
              runtime_profile: {},
              is_hidden_singleton: false,
              presets: [],
            },
          ],
        },
        {
          main_model_id: "main_c",
          workspace_id: "ws_demo",
          display_name: "Main C",
          status: "ready",
          source_type: "builtin",
          main_model_metadata: {},
          default_submodel_id: null,
          submodels: [],
        },
      ],
    });

    expect(
      restoreWorkspaceSelection(previousTree, nextTree, {
        selectedMainModelId: "main_a",
        selectedSubmodelId: null,
      }),
    ).toEqual({
      selectedMainModelId: "main_b",
      selectedSubmodelId: "sub_b1",
    });
  });
});
