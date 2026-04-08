export interface ParameterPatchTask {
  kind: "voice-binding" | "render-profile" | "edge";
  submit: () => Promise<void>;
}

export function createParameterPatchQueue() {
  async function run(tasks: ParameterPatchTask[]) {
    for (const task of tasks) {
      try {
        await task.submit();
      } catch {
        return {
          status: "failed" as const,
          failedTaskKind: task.kind,
        };
      }
    }

    return {
      status: "completed" as const,
      failedTaskKind: null,
    };
  }

  return {
    run,
  };
}
