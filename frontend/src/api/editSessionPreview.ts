import axios from "./http";

import type {
  StandardizationPreviewRequest,
  StandardizationPreviewResponse,
} from "@/types/editSession";

export async function requestStandardizationPreview(
  body: StandardizationPreviewRequest,
  options: { signal?: AbortSignal } = {},
): Promise<StandardizationPreviewResponse> {
  const { data } = await axios.post<StandardizationPreviewResponse>(
    "/v1/edit-session/standardization-preview",
    body,
    {
      signal: options.signal,
    },
  );
  return data;
}
