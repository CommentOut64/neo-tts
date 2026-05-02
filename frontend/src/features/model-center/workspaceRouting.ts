import type { TtsRegistryWorkspaceSummary } from "@/types/ttsRegistry";

export interface ModelWorkspaceRouteLocation {
  name: "ModelWorkspace";
  params: {
    familyRoute: string;
    workspaceSlug: string;
  };
}

export interface CreateWorkspaceDraft {
  display_name: string;
  slug: string;
}

const DEFAULT_WORKSPACE_BASE_NAME = "New Workspace";
const DEFAULT_WORKSPACE_BASE_SLUG = "new-workspace";

export function buildModelWorkspaceRouteLocation(
  workspace: TtsRegistryWorkspaceSummary,
): ModelWorkspaceRouteLocation {
  return {
    name: "ModelWorkspace",
    params: {
      familyRoute: workspace.family_route_slug,
      workspaceSlug: workspace.slug,
    },
  };
}

export function findWorkspaceSummaryByRoute(
  workspaces: TtsRegistryWorkspaceSummary[],
  familyRoute: string,
  workspaceSlug: string,
): TtsRegistryWorkspaceSummary | null {
  const normalizedFamilyRoute = familyRoute.trim();
  const normalizedWorkspaceSlug = workspaceSlug.trim();
  if (!normalizedFamilyRoute || !normalizedWorkspaceSlug) {
    return null;
  }

  return (
    workspaces.find(
      (workspace) =>
        workspace.family_route_slug === normalizedFamilyRoute && workspace.slug === normalizedWorkspaceSlug,
    ) ?? null
  );
}

export function buildNextWorkspaceDraft(
  workspaces: TtsRegistryWorkspaceSummary[],
): CreateWorkspaceDraft {
  const existingSlugs = new Set(workspaces.map((workspace) => workspace.slug));
  let sequence = 1;

  while (true) {
    const suffix = sequence === 1 ? "" : ` ${sequence}`;
    const slugSuffix = sequence === 1 ? "" : `-${sequence}`;
    const display_name = `${DEFAULT_WORKSPACE_BASE_NAME}${suffix}`;
    const slug = `${DEFAULT_WORKSPACE_BASE_SLUG}${slugSuffix}`;
    if (!existingSlugs.has(slug)) {
      return { display_name, slug };
    }
    sequence += 1;
  }
}
