import { describe, expect, it } from "vitest";

import createViteConfig from "../vite.config";

describe("vite config", () => {
  it("uses relative asset base for production builds so electron file URLs can load assets", () => {
    const config = createViteConfig({
      command: "build",
      mode: "production",
      isSsrBuild: false,
      isPreview: false,
    });

    expect(config.base).toBe("./");
  });
});
