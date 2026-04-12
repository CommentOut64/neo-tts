import axios from "./http";
import type { PrepareExitResponse } from "@/types/system";

export interface FolderSelectResponse {
  path: string | null;
}

export async function openFolderDialog(
  initialDir?: string,
): Promise<string | null> {
  const { data } = await axios.get<FolderSelectResponse>(
    "/v1/system/dialog/folder",
    {
      params: { initial_dir: initialDir },
    },
  );
  return data.path;
}

export async function prepareExit(): Promise<PrepareExitResponse> {
  const { data } = await axios.post<PrepareExitResponse>("/v1/system/prepare-exit");
  return data;
}
