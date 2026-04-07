import axios from "./http";

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
