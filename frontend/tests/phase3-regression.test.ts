import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildInitializeRequest,
  WORKSPACE_SEGMENT_BOUNDARY_MODE,
  unwrapAcceptedExportJob,
  unwrapAcceptedRenderJob,
} from "../src/api/editSessionContract.ts";
import { ApiRequestError, extractStatusCode, resolveApiUrl, toApiRequestError } from "../src/api/requestSupport.ts";

describe("phase3 regression", () => {
beforeEach(() => {
  vi.resetModules();
});

it("buildInitializeRequest maps workspace draft to edit-session initialize payload", () => {
  const payload = buildInitializeRequest(
    {
      text: "第一句。第二句。",
      voiceId: "demo-voice",
      textLang: "zh",
      speed: 1.1,
      temperature: 0.85,
      topP: 0.9,
      topK: 12,
      pauseLength: 0.45,
      refSource: "preset",
      refText: "示例参考文本",
      refLang: "zh",
      customRefFile: null,
      customRefPath: null,
    },
    {
      refAudio: "voices/demo/reference.wav",
    },
  );

  expect(payload).toEqual({
    raw_text: "第一句。第二句。",
    text_language: "zh",
    voice_id: "demo-voice",
    reference_source: "preset",
    speed: 1.1,
    temperature: 0.85,
    top_p: 0.9,
    top_k: 12,
    pause_duration_seconds: 0.45,
    segment_boundary_mode: WORKSPACE_SEGMENT_BOUNDARY_MODE,
    reference_audio_path: "voices/demo/reference.wav",
    reference_text: "示例参考文本",
    reference_language: "zh",
  });
});

it("buildInitializeRequest uses the fixed workspace strong-terminal segmentation standard", () => {
  const payload = buildInitializeRequest({
    text: "第一句！第二句？第三句。",
    voiceId: "voice-a",
    textLang: "zh",
    speed: 1,
    temperature: 1,
    topP: 1,
    topK: 15,
    pauseLength: 0.3,
    refSource: "custom",
    refText: "",
    refLang: "auto",
    customRefFile: null,
    customRefPath: null,
  });

  expect(payload.segment_boundary_mode).toBe(WORKSPACE_SEGMENT_BOUNDARY_MODE);
});

it("buildInitializeRequest no longer accepts a user-provided segmentation mode", () => {
  const payload = buildInitializeRequest({
    text: "test",
    voiceId: "voice-a",
    textLang: "auto",
    speed: 1,
    temperature: 1,
    topP: 1,
    topK: 15,
    pauseLength: 0.3,
    refSource: "custom",
    refText: "",
    refLang: "auto",
    customRefFile: null,
    customRefPath: null,
  });

  expect(payload.segment_boundary_mode).toBe(WORKSPACE_SEGMENT_BOUNDARY_MODE);
  expect("reference_audio_path" in payload).toBe(false);
});

it("buildInitializeRequest uses uploaded custom reference path", () => {
  const payload = buildInitializeRequest({
    text: "test",
    voiceId: "voice-a",
    textLang: "auto",
    speed: 1,
    temperature: 1,
    topP: 1,
    topK: 15,
    pauseLength: 0.3,
    refSource: "custom",
    refText: "自定义参考文本",
    refLang: "zh",
    customRefFile: null,
    customRefPath: "managed_voices/_temp_refs/custom/custom.wav",
  });

  expect(payload.reference_audio_path).toBe("managed_voices/_temp_refs/custom/custom.wav");
  expect(payload.reference_text).toBe("自定义参考文本");
  expect(payload.reference_language).toBe("zh");
});

it("unwrapAcceptedRenderJob returns nested job payload", () => {
  const job = unwrapAcceptedRenderJob({
    job: {
      job_id: "job-123",
      document_id: "doc-1",
      status: "queued",
      progress: 0,
      message: "queued",
    },
  });

  expect(job).toEqual({
    job_id: "job-123",
    document_id: "doc-1",
    status: "queued",
    progress: 0,
    message: "queued",
  });
});

it("unwrapAcceptedExportJob returns nested export job payload", () => {
  const job = unwrapAcceptedExportJob({
    job: {
      export_job_id: "export-123",
      document_id: "doc-1",
      document_version: 2,
      timeline_manifest_id: "timeline-1",
      export_kind: "composition",
      status: "queued",
      target_dir: "exports/demo",
      overwrite_policy: "fail",
      progress: 0,
      message: "queued",
      output_manifest: null,
      staging_dir: null,
      updated_at: "2026-04-07T00:00:00Z",
    },
  });

  expect(job.export_job_id).toBe("export-123");
  expect(job.export_kind).toBe("composition");
});

it("resumeRenderJob unwraps accepted response payload", async () => {
  const post = vi.fn().mockResolvedValue({
    data: {
      job: {
        job_id: "job-resumed",
        document_id: "doc-1",
        status: "queued",
        progress: 0,
        message: "resumed",
      },
    },
  });

  vi.doMock("../src/api/http.ts", () => ({
    default: {
      post,
      get: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  }));

  const { resumeRenderJob } = await import("../src/api/editSession.ts");
  const job = await resumeRenderJob("job-paused");

  expect(post).toHaveBeenCalledWith("/v1/edit-session/render-jobs/job-paused/resume");
  expect(job).toEqual({
    job_id: "job-resumed",
    document_id: "doc-1",
    status: "queued",
    progress: 0,
    message: "resumed",
  });
});

it("uploadEditSessionReferenceAudio posts multipart form data", async () => {
  const post = vi.fn().mockResolvedValue({
    data: {
      reference_audio_path: "managed_voices/_temp_refs/custom/custom.wav",
      filename: "custom.wav",
    },
  });

  vi.doMock("../src/api/http.ts", () => ({
    default: {
      post,
      get: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  }));

  const { uploadEditSessionReferenceAudio } = await import("../src/api/editSession.ts");
  const file = new File(["RIFFcustom"], "custom.wav", { type: "audio/wav" });

  const response = await uploadEditSessionReferenceAudio(file);

  expect(post).toHaveBeenCalledTimes(1);
  const [url, body] = post.mock.calls[0] as [string, FormData];
  expect(url).toBe("/v1/edit-session/reference-audio");
  expect(body).toBeInstanceOf(FormData);
  expect(body.get("ref_audio_file")).toBe(file);
  expect(response).toEqual({
    reference_audio_path: "managed_voices/_temp_refs/custom/custom.wav",
    filename: "custom.wav",
  });
});

it("subscribeExportJobEvents uses export events endpoint and dispatches progress payload", async () => {
  const listeners = new Map<string, (event: MessageEvent<string>) => void>();

  class MockEventSource {
    readonly url: string;
    onerror: ((event: Event) => void) | null = null;

    constructor(url: string) {
      this.url = url;
    }

    addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
      listeners.set(type, listener as (event: MessageEvent<string>) => void);
    }

    removeEventListener(type: string) {
      listeners.delete(type);
    }

    close() {}
  }

  vi.stubGlobal("EventSource", MockEventSource);

  const { subscribeExportJobEvents } = await import("../src/api/editSession.ts");
  const onProgress = vi.fn();
  const onCompleted = vi.fn();

  const dispose = subscribeExportJobEvents("export-1", {
    onProgress,
    onCompleted,
  });

  expect(listeners.has("export_progress")).toBe(true);
  listeners.get("export_progress")?.({
    data: JSON.stringify({ progress: 0.5, message: "halfway" }),
  } as MessageEvent<string>);
  listeners.get("export_completed")?.({
    data: JSON.stringify({
      export_job_id: "export-1",
      document_id: "doc-1",
      document_version: 2,
      timeline_manifest_id: "timeline-1",
      export_kind: "segments",
      status: "completed",
      target_dir: "exports/demo",
      overwrite_policy: "fail",
      progress: 1,
      message: "done",
      output_manifest: null,
      staging_dir: null,
      updated_at: "2026-04-07T00:00:00Z",
    }),
  } as MessageEvent<string>);

  expect(onProgress).toHaveBeenCalledWith(0.5, "halfway");
  expect(onCompleted).toHaveBeenCalled();
  dispose();
});

it("toApiRequestError preserves HTTP status and detail text", () => {
  const error = toApiRequestError({
    response: {
      status: 404,
      data: {
        detail: "session not found",
      },
    },
  });

  expect(error).toBeInstanceOf(ApiRequestError);
  expect(error.message).toBe("session not found");
  expect(extractStatusCode(error)).toBe(404);
});

it("resolveApiUrl composes configured base url without duplicate slashes", () => {
  expect(
    resolveApiUrl("/v1/edit-session/render-jobs/job-1/events", "http://localhost:8000/api/"),
  ).toBe("http://localhost:8000/api/v1/edit-session/render-jobs/job-1/events");
});

});
