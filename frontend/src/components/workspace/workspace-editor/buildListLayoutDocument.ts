import type {
  WorkspaceRenderPlan,
  WorkspaceSemanticDocument,
} from "./layoutTypes";
import { buildListSegmentBlockDocument } from "./list/buildListSegmentBlockDocument";

export function buildListLayoutDocument(
  semanticDocument: WorkspaceSemanticDocument,
): WorkspaceRenderPlan {
  return buildListSegmentBlockDocument(semanticDocument);
}
