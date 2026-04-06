import type { ReferenceAudioUploadResponse } from "@/types/editSession";

export interface ResolveInitializeReferenceAudioPathOptions {
  refSource: "preset" | "custom";
  presetReferenceAudioPath: string | null | undefined;
  customReferenceAudioPath: string | null | undefined;
  customReferenceAudioFile: File | null | undefined;
  upload: (file: File) => Promise<ReferenceAudioUploadResponse>;
}

export async function resolveInitializeReferenceAudioPath(
  options: ResolveInitializeReferenceAudioPathOptions,
): Promise<string | undefined> {
  if (options.refSource === "preset") {
    return options.presetReferenceAudioPath ?? undefined;
  }

  if (options.customReferenceAudioPath) {
    return options.customReferenceAudioPath;
  }

  if (!options.customReferenceAudioFile) {
    return undefined;
  }

  const response = await options.upload(options.customReferenceAudioFile);
  return response.reference_audio_path;
}
