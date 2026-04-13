import { beforeEach, describe, expect, it } from "vitest";
import { nextTick } from "vue";

import { useWorkspaceAutoplay } from "../src/composables/useWorkspaceAutoplay";

describe("useWorkspaceAutoplay", () => {
  const workspaceAutoplay = useWorkspaceAutoplay();

  beforeEach(async () => {
    workspaceAutoplay.setAutoPlayEnabled(true);
    await nextTick();
  });

  it("默认开启自动播放", () => {
    expect(workspaceAutoplay.isAutoPlayEnabled.value).toBe(true);
  });

  it("toggleAutoPlay 会切换自动播放状态", async () => {
    workspaceAutoplay.toggleAutoPlay();
    await nextTick();

    expect(workspaceAutoplay.isAutoPlayEnabled.value).toBe(false);

    workspaceAutoplay.toggleAutoPlay();
    await nextTick();

    expect(workspaceAutoplay.isAutoPlayEnabled.value).toBe(true);
  });

  it("setAutoPlayEnabled 会显式覆盖当前状态", async () => {
    workspaceAutoplay.setAutoPlayEnabled(false);
    await nextTick();

    expect(workspaceAutoplay.isAutoPlayEnabled.value).toBe(false);
  });
});
