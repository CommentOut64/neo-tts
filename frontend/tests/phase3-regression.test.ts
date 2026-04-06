import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildInitializeRequest, unwrapAcceptedRenderJob } from "../src/api/editSessionContract.ts";
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
      textSplitMethod: "cut5",
      refSource: "preset",
      refText: "示例参考文本",
      refLang: "zh",
      customRefFile: null,
    },
    {
      refAudio: "voices/demo/reference.wav",
    },
  );

  expect(payload).toEqual({
    raw_text: "第一句。第二句。",
    text_language: "zh",
    voice_id: "demo-voice",
    speed: 1.1,
    temperature: 0.85,
    top_p: 0.9,
    top_k: 12,
    pause_duration_seconds: 0.45,
    segment_boundary_mode: "zh_period",
    reference_audio_path: "voices/demo/reference.wav",
    reference_text: "示例参考文本",
    reference_language: "zh",
  });
});

it("buildInitializeRequest preserves supported boundary modes", () => {
  const payload = buildInitializeRequest({
    text: "test",
    voiceId: "voice-a",
    textLang: "auto",
    speed: 1,
    temperature: 1,
    topP: 1,
    topK: 15,
    pauseLength: 0.3,
    textSplitMethod: "zh_period",
    refSource: "custom",
    refText: "",
    refLang: "auto",
    customRefFile: null,
  });

  expect(payload.segment_boundary_mode).toBe("zh_period");
  expect("reference_audio_path" in payload).toBe(false);
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

it("VoiceSelect does not pass invalid medium size to Element Plus select", () => {
  const source = readFileSync(new URL("../src/components/VoiceSelect.vue", import.meta.url), "utf8");
  expect(source.includes('size="medium"')).toBe(false);
});
});
