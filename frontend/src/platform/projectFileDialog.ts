import { openFileDialog } from "@/api/system";

export async function chooseNeoProjectFile(initialDir?: string): Promise<string | null> {
  const native = typeof window !== "undefined" ? window.neoTTS?.openProjectFileDialog : undefined;
  if (typeof native === "function") {
    return native(initialDir);
  }
  return openFileDialog(".neo", initialDir);
}

export async function chooseNeoProjectSavePath(
  initialDir?: string,
  suggestedName = "project.neo",
): Promise<string | null> {
  const native = typeof window !== "undefined" ? window.neoTTS?.saveProjectFileDialog : undefined;
  if (typeof native === "function") {
    return native(initialDir, suggestedName);
  }
  // The web fallback has no save dialog endpoint.  Choosing a folder keeps
  // path selection inside the existing narrow system-dialog bridge; callers
  // append the filename without exposing arbitrary local paths to the UI.
  const folder = await import("@/api/system").then(({ openFolderDialog }) => openFolderDialog(initialDir));
  return folder ? `${folder.replace(/[\\/]$/, "")}/${suggestedName}` : null;
}
