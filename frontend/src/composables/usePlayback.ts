import { ref, computed, shallowRef, watch } from "vue";
import { resolvePlaybackCursor, useTimeline } from "./useTimeline";
import type { PlaybackCursor } from "@/types/editSession";
import { useRuntimeState } from "./useRuntimeState";

type BlockCacheEntry = {
  buffer: AudioBuffer | null;
  promise: Promise<AudioBuffer>;
};

// module-level singletons (preserves state across route changes if needed)
const isPlaying = ref(false);
const currentSample = ref(0);
const currentCursor = ref<PlaybackCursor | null>(null);
const playbackCursorError = ref<Error | null>(null);

const audioCtx = shallowRef<AudioContext | null>(null);
const masterGainNode = shallowRef<GainNode | null>(null);
const blockCache = new Map<string, BlockCacheEntry>();

const SEEK_FADE_OUT_SECONDS = 0.01;
const SEEK_FADE_IN_SECONDS = 0.012;

// Scheduling state
let activeNodes: Array<{ node: AudioBufferSourceNode; blockIndex: number }> =
  [];
let startTimeSeconds = 0; // AudioContext.currentTime when playback started/seeked
let startOffsetSamples = 0; // The exact timeline sample value corresponding to startTimeSeconds
let animationFrameId: number | null = null;
let prefetchTimeoutId: number | null = null;
let playbackSessionId = 0;
let cursorSyncInitialized = false;

export function usePlayback() {
  const {
    timelineManifest,
    blockEntries,
    sampleRate,
    totalSamples,
    segmentIdToSampleRange,
  } = useTimeline();
  const { canMutate, lockedSegmentIds } = useRuntimeState();

  function stopScheduledPlayback() {
    isPlaying.value = false;
    playbackSessionId += 1;

    clearScheduledTimers();
    clearActiveNodes();
  }

  function clearScheduledTimers() {
    if (animationFrameId !== null) {
      cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }
    if (prefetchTimeoutId !== null) {
      clearTimeout(prefetchTimeoutId);
      prefetchTimeoutId = null;
    }
  }

  function syncCursorState() {
    if (!timelineManifest.value) {
      currentCursor.value = null;
      playbackCursorError.value = null;
      return;
    }

    try {
      currentCursor.value = resolvePlaybackCursor(
        timelineManifest.value,
        currentSample.value,
      );
      playbackCursorError.value = null;
    } catch (error) {
      currentCursor.value = null;
      playbackCursorError.value =
        error instanceof Error
          ? error
          : new Error("[playback] failed to resolve playback cursor");
      stopScheduledPlayback();
    }
  }

  function setCurrentSample(sample: number) {
    currentSample.value = sample;
    syncCursorState();
  }

  if (!cursorSyncInitialized) {
    cursorSyncInitialized = true;
    watch(
      timelineManifest,
      () => {
        syncCursorState();
      },
      { immediate: true, flush: "sync" },
    );
  }

  function getAudioCtx() {
    if (!audioCtx.value) {
      audioCtx.value = new AudioContext({
        sampleRate: sampleRate.value || 24000,
      });
    }
    if (audioCtx.value.state === "suspended") {
      void audioCtx.value.resume();
    }
    return audioCtx.value;
  }

  function getOutputGainNode() {
    const ctx = getAudioCtx();
    if (!masterGainNode.value) {
      const gainNode = ctx.createGain();
      gainNode.gain.setValueAtTime(1, ctx.currentTime);
      gainNode.connect(ctx.destination);
      masterGainNode.value = gainNode;
    }
    return masterGainNode.value;
  }

  function scheduleFadeOut(startTime: number, durationSeconds: number) {
    const gainNode = getOutputGainNode();
    gainNode.gain.cancelScheduledValues(startTime);
    gainNode.gain.setValueAtTime(gainNode.gain.value, startTime);
    gainNode.gain.linearRampToValueAtTime(0, startTime + durationSeconds);
    return startTime + durationSeconds;
  }

  function scheduleFadeIn(startTime: number, durationSeconds: number) {
    const gainNode = getOutputGainNode();
    gainNode.gain.cancelScheduledValues(startTime);
    if (durationSeconds <= 0) {
      gainNode.gain.setValueAtTime(1, startTime);
      return;
    }
    gainNode.gain.setValueAtTime(0, startTime);
    gainNode.gain.linearRampToValueAtTime(1, startTime + durationSeconds);
  }

  function fetchBlock(audioUrl: string): Promise<AudioBuffer> {
    if (blockCache.has(audioUrl)) {
      console.debug("[playback] reusing cached block", { audioUrl });
      return blockCache.get(audioUrl)!.promise;
    }

    const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
    const fullUrl = API_BASE
      ? `${API_BASE.replace(/\/$/, "")}${audioUrl}`
      : audioUrl;

    const promise = fetch(fullUrl)
      .then((res) => {
        console.info("[playback] fetched block response", {
          audioUrl,
          fullUrl,
          status: res.status,
          contentType: res.headers.get("content-type"),
        });
        if (!res.ok) {
          throw new Error(`Fetch block audio failed: ${res.status}`);
        }
        return res.arrayBuffer();
      })
      .then((ab) => {
        console.info("[playback] decoding block", {
          audioUrl,
          byteLength: ab.byteLength,
          timelineSampleRate: sampleRate.value,
        });
        return getAudioCtx().decodeAudioData(ab);
      })
      .then((buffer) => {
        const entry = blockCache.get(audioUrl);
        if (entry) entry.buffer = buffer;
        console.info("[playback] decoded block", {
          audioUrl,
          sampleRate: buffer.sampleRate,
          length: buffer.length,
          durationSeconds: buffer.duration,
          numberOfChannels: buffer.numberOfChannels,
        });
        return buffer;
      });

    blockCache.set(audioUrl, { promise, buffer: null });
    return promise;
  }

  function clearActiveNodes() {
    for (const { node } of activeNodes) {
      node.onended = null;
      try {
        node.stop();
      } catch (e) {
        /* ignore */
      }
      try {
        node.disconnect();
      } catch (e) {
        /* ignore */
      }
    }
    activeNodes = [];
  }

  function isStalePlaybackSession(sessionId: number) {
    return !isPlaying.value || sessionId !== playbackSessionId;
  }

  function pause() {
    if (!isPlaying.value) return;
    stopScheduledPlayback();

    // Calculate accurate pause position before clearing
    const ctx = getAudioCtx();
    const elapsedSeconds = Math.max(0, ctx.currentTime - startTimeSeconds);
    setCurrentSample(Math.min(
      totalSamples.value,
      startOffsetSamples + Math.floor(elapsedSeconds * sampleRate.value),
    ));
  }

  function pauseForProcessing() {
    pause();
  }

  function updatePlayState() {
    if (!isPlaying.value) return;
    const ctx = getAudioCtx();
    const elapsedSeconds = Math.max(0, ctx.currentTime - startTimeSeconds);
    const newSample =
      startOffsetSamples + Math.floor(elapsedSeconds * sampleRate.value);

    if (newSample >= totalSamples.value) {
      setCurrentSample(totalSamples.value);
      isPlaying.value = false;
      return;
    }

    setCurrentSample(newSample);
    animationFrameId = requestAnimationFrame(updatePlayState);
  }

  // Determine which block covers the requested sample
  function findBlockIndexForSample(sample: number) {
    const blocks = blockEntries.value;
    for (let i = 0; i < blocks.length; i++) {
      if (sample >= blocks[i].start_sample && sample < blocks[i].end_sample) {
        return i;
      }
    }
    return -1;
  }

  async function scheduleBlock(
    blockIndex: number,
    scheduleStartCtxTime: number,
    offsetSamplesInBlock: number,
    sessionId: number,
    fadeInDurationSeconds = 0,
  ) {
    if (blockIndex < 0 || blockIndex >= blockEntries.value.length) return;
    const block = blockEntries.value[blockIndex];

    try {
      console.info("[playback] scheduling block", {
        blockIndex,
        blockAssetId: block.block_asset_id,
        audioUrl: block.audio_url,
        startSample: block.start_sample,
        endSample: block.end_sample,
        offsetSamplesInBlock,
        totalSamples: totalSamples.value,
      });
      const buffer = await fetchBlock(block.audio_url);
      // Seek / pause 后，旧会话的异步调度结果必须直接作废，不能混入新播放。
      if (isStalePlaybackSession(sessionId)) return;

      const ctx = getAudioCtx();

      // If the schedule time is in the past, or very close, shift everything to "now" to avoid drops
      let startCtxTime = scheduleStartCtxTime;
      // We need offset in seconds to start reading from buffer
      let initialBufferOffset = offsetSamplesInBlock / sampleRate.value;

      if (startCtxTime < ctx.currentTime) {
        // We're late scheduling this block.
        const delay = ctx.currentTime - startCtxTime;
        startCtxTime = ctx.currentTime;
        initialBufferOffset += delay;
      }

      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(getOutputGainNode());
      scheduleFadeIn(startCtxTime, fadeInDurationSeconds);
      source.start(startCtxTime, initialBufferOffset);
      console.info("[playback] block started", {
        blockIndex,
        blockAssetId: block.block_asset_id,
        contextSampleRate: ctx.sampleRate,
        bufferSampleRate: buffer.sampleRate,
        bufferDurationSeconds: buffer.duration,
        startCtxTime,
        initialBufferOffset,
      });

      activeNodes.push({ node: source, blockIndex });

      // Schedule prefetching the next block before this one ends
      // Calculate how long this block will play
      const durationSeconds =
        buffer.length / buffer.sampleRate - initialBufferOffset;
      const nextBlockIndex = blockIndex + 1;

      if (nextBlockIndex < blockEntries.value.length) {
        // Start fetching early
        prefetchTimeoutId = window.setTimeout(
          () => {
            if (!isStalePlaybackSession(sessionId)) {
              void fetchBlock(blockEntries.value[nextBlockIndex].audio_url);
            }
          },
          Math.max(0, (durationSeconds - 2) * 1000),
        );

        source.onended = () => {
          // Check if this node is still relevant
          const t = activeNodes.findIndex((n) => n.node === source);
          if (t >= 0) activeNodes.splice(t, 1);

          if (!isStalePlaybackSession(sessionId)) {
            const nextCtxTime = startCtxTime + durationSeconds;
            void scheduleBlock(nextBlockIndex, nextCtxTime, 0, sessionId, 0);
          }
        };
      } else {
        source.onended = () => {
          const t = activeNodes.findIndex((n) => n.node === source);
          if (t >= 0) activeNodes.splice(t, 1);
          if (activeNodes.length === 0 && !isStalePlaybackSession(sessionId)) {
            isPlaying.value = false;
            setCurrentSample(totalSamples.value);
          }
        };
      }
    } catch (e) {
      console.error("[playback] failed to schedule block", {
        error: e,
        blockIndex,
        blockAssetId: block.block_asset_id,
        audioUrl: block.audio_url,
        totalSamples: totalSamples.value,
        timelineSampleRate: sampleRate.value,
      });
      pause();
    }
  }

  function play(options?: {
    startCtxTime?: number;
    fadeInDurationSeconds?: number;
  }) {
    if (!canMutate.value || isPlaying.value || playbackCursorError.value) {
      console.warn("[playback] play ignored", {
        canMutate: canMutate.value,
        isPlaying: isPlaying.value,
        playbackCursorError: playbackCursorError.value?.message ?? null,
        totalSamples: totalSamples.value,
        blockCount: blockEntries.value.length,
      });
      return;
    }

    if (currentSample.value >= totalSamples.value) {
      setCurrentSample(0);
    } else {
      syncCursorState();
    }

    if (playbackCursorError.value) {
      console.warn("[playback] play aborted due to cursor error", {
        currentSample: currentSample.value,
        error: playbackCursorError.value.message,
      });
      return;
    }

    console.info("[playback] play requested", {
      currentSample: currentSample.value,
      totalSamples: totalSamples.value,
      sampleRate: sampleRate.value,
      blockCount: blockEntries.value.length,
      timelineManifestLoaded: timelineManifest.value !== null,
    });
    isPlaying.value = true;
    playbackSessionId += 1;
    const sessionId = playbackSessionId;
    const ctx = getAudioCtx();
    const scheduleStartCtxTime = options?.startCtxTime ?? ctx.currentTime;
    const fadeInDurationSeconds = options?.fadeInDurationSeconds ?? 0;
    startTimeSeconds = scheduleStartCtxTime;
    startOffsetSamples = currentSample.value;

    const startBlkIndex = findBlockIndexForSample(startOffsetSamples);
    if (startBlkIndex !== -1) {
      const block = blockEntries.value[startBlkIndex];
      const offsetInBlock = startOffsetSamples - block.start_sample;
      void scheduleBlock(
        startBlkIndex,
        scheduleStartCtxTime,
        offsetInBlock,
        sessionId,
        fadeInDurationSeconds,
      );

      if (animationFrameId !== null) cancelAnimationFrame(animationFrameId);
      animationFrameId = requestAnimationFrame(updatePlayState);
    } else {
      console.warn("[playback] no block found for current sample", {
        currentSample: currentSample.value,
        totalSamples: totalSamples.value,
        blockCount: blockEntries.value.length,
      });
      isPlaying.value = false;
    }
  }

  function seekToSample(sample: number) {
    const targetSample = Math.max(0, Math.min(sample, totalSamples.value));
    const wasPlaying = isPlaying.value;
    if (!wasPlaying) {
      setCurrentSample(targetSample);
      return;
    }

    const ctx = getAudioCtx();
    const restartAt = scheduleFadeOut(ctx.currentTime, SEEK_FADE_OUT_SECONDS);
    isPlaying.value = false;
    playbackSessionId += 1;
    clearScheduledTimers();
    for (const { node } of activeNodes) {
      node.onended = null;
      try {
        node.stop(restartAt);
      } catch (e) {
        /* ignore */
      }
    }
    activeNodes = [];

    setCurrentSample(targetSample);
    if (playbackCursorError.value) {
      return;
    }
    play({
      startCtxTime: restartAt,
      fadeInDurationSeconds: SEEK_FADE_IN_SECONDS,
    });
  }

  function seekToSegment(segmentId: string) {
    if (lockedSegmentIds.value.has(segmentId)) return; // cannot seek to locked segment
    const range = segmentIdToSampleRange(segmentId);
    if (range) {
      seekToSample(range.start);
    }
  }

  async function warmAudioUrls(audioUrls: string[]) {
    const uniqueAudioUrls = Array.from(new Set(audioUrls.filter(Boolean)));
    await Promise.all(uniqueAudioUrls.map((audioUrl) => fetchBlock(audioUrl)));
  }

  return {
    isPlaying: computed(() => isPlaying.value),
    currentSample,
    currentCursor: computed(() => currentCursor.value),
    currentSegmentId: computed(() =>
      currentCursor.value?.kind === "segment" ? currentCursor.value.segmentId : null,
    ),
    playbackCursorError: computed(() => playbackCursorError.value),
    play,
    pause,
    pauseForProcessing,
    seekToSample,
    seekToSegment,
    warmAudioUrls,
  };
}
