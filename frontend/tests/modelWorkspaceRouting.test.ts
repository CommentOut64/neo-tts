import { describe, expect, it } from "vitest";

import {
  buildNextWorkspaceDraft,
  buildWorkspaceDraftFromSummary,
  buildModelWorkspaceRouteLocation,
  findWorkspaceSummaryByRoute,
  type ModelWorkspaceRouteLocation,
} from "../src/features/model-center/workspaceRouting";
import type { TtsRegistryWorkspaceSummary } from "../src/types/ttsRegistry";

function buildWorkspaceSummary(overrides: Partial<TtsRegistryWorkspaceSummary> = {}): TtsRegistryWorkspaceSummary {
  return {
    workspace_id: "ws_remote_demo",
    adapter_id: "external_http_tts",
    family_id: "external_http_tts_default",
    display_name: "Remote Demo",
    slug: "remote-demo",
    status: "ready",
    family_display_name: "External HTTP TTS",
    family_route_slug: "external-http-tts",
    binding_display_strategy: "workspace/main-model",
    ...overrides,
  };
}

describe("model workspace routing helpers", () => {
  it("builds route location from workspace summary route fields", () => {
    const summary = buildWorkspaceSummary();

    const routeLocation = buildModelWorkspaceRouteLocation(summary);

    expect(routeLocation).toEqual<ModelWorkspaceRouteLocation>({
      name: "ModelWorkspace",
      params: {
        familyRoute: "external-http-tts",
        workspaceSlug: "remote-demo",
      },
    });
  });

  it("finds the matching workspace summary from route params", () => {
    const target = buildWorkspaceSummary();
    const workspaces = [
      buildWorkspaceSummary({
        workspace_id: "ws_other",
        slug: "other",
      }),
      target,
    ];

    const matched = findWorkspaceSummaryByRoute(workspaces, "external-http-tts", "remote-demo");

    expect(matched).toEqual(target);
  });

  it("returns null when route params do not match a known workspace", () => {
    const workspaces = [buildWorkspaceSummary()];

    expect(findWorkspaceSummaryByRoute(workspaces, "gpt-sovits-local", "remote-demo")).toBeNull();
    expect(findWorkspaceSummaryByRoute(workspaces, "external-http-tts", "missing")).toBeNull();
  });

  it("builds a unique default workspace draft from existing workspace slugs", () => {
    const draft = buildNextWorkspaceDraft([
      buildWorkspaceSummary({ slug: "new-workspace", display_name: "New Workspace" }),
      buildWorkspaceSummary({ workspace_id: "ws_new_workspace_2", slug: "new-workspace-2", display_name: "New Workspace 2" }),
    ]);

    expect(draft).toEqual({
      display_name: "New Workspace 3",
      slug: "new-workspace-3",
    });
  });

  it("builds an editable workspace draft from an existing workspace summary", () => {
    expect(
      buildWorkspaceDraftFromSummary(
        buildWorkspaceSummary({
          display_name: "Workspace Alpha",
          slug: "workspace-alpha",
        }),
      ),
    ).toEqual({
      display_name: "Workspace Alpha",
      slug: "workspace-alpha",
    });
  });
});
