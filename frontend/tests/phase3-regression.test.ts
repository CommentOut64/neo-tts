import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { buildInitializeRequest, unwrapAcceptedRenderJob } from '../src/api/editSessionContract.ts'
import { ApiRequestError, extractStatusCode, resolveApiUrl, toApiRequestError } from '../src/api/requestSupport.ts'

test('buildInitializeRequest maps workspace draft to edit-session initialize payload', () => {
  const payload = buildInitializeRequest(
    {
      text: '第一句。第二句。',
      voiceId: 'demo-voice',
      textLang: 'zh',
      speed: 1.1,
      temperature: 0.85,
      topP: 0.9,
      topK: 12,
      pauseLength: 0.45,
      textSplitMethod: 'cut5',
      refSource: 'preset',
      refText: '示例参考文本',
      refLang: 'zh',
      customRefFile: null,
    },
    {
      refAudio: 'voices/demo/reference.wav',
    },
  )

  assert.deepStrictEqual(payload, {
    raw_text: '第一句。第二句。',
    text_language: 'zh',
    voice_id: 'demo-voice',
    speed: 1.1,
    temperature: 0.85,
    top_p: 0.9,
    top_k: 12,
    pause_duration_seconds: 0.45,
    segment_boundary_mode: 'raw_strong_punctuation',
    reference_audio_path: 'voices/demo/reference.wav',
    reference_text: '示例参考文本',
    reference_language: 'zh',
  })
})

test('buildInitializeRequest preserves supported boundary modes', () => {
  const payload = buildInitializeRequest({
    text: 'test',
    voiceId: 'voice-a',
    textLang: 'auto',
    speed: 1,
    temperature: 1,
    topP: 1,
    topK: 15,
    pauseLength: 0.3,
    textSplitMethod: 'zh_period',
    refSource: 'custom',
    refText: '',
    refLang: 'auto',
    customRefFile: null,
  })

  assert.equal(payload.segment_boundary_mode, 'zh_period')
  assert.ok(!('reference_audio_path' in payload))
})

test('unwrapAcceptedRenderJob returns nested job payload', () => {
  const job = unwrapAcceptedRenderJob({
    job: {
      job_id: 'job-123',
      document_id: 'doc-1',
      status: 'queued',
      progress: 0,
      message: 'queued',
    },
  })

  assert.deepStrictEqual(job, {
    job_id: 'job-123',
    document_id: 'doc-1',
    status: 'queued',
    progress: 0,
    message: 'queued',
  })
})

test('toApiRequestError preserves HTTP status and detail text', () => {
  const error = toApiRequestError({
    response: {
      status: 404,
      data: {
        detail: 'session not found',
      },
    },
  })

  assert.ok(error instanceof ApiRequestError)
  assert.equal(error.message, 'session not found')
  assert.equal(extractStatusCode(error), 404)
})

test('resolveApiUrl composes configured base url without duplicate slashes', () => {
  assert.equal(
    resolveApiUrl('/v1/edit-session/render-jobs/job-1/events', 'http://localhost:8000/api/'),
    'http://localhost:8000/api/v1/edit-session/render-jobs/job-1/events',
  )
})

test('VoiceSelect does not pass invalid medium size to Element Plus select', () => {
  const source = readFileSync(new URL('../src/components/VoiceSelect.vue', import.meta.url), 'utf8')
  assert.ok(!source.includes('size="medium"'))
})
