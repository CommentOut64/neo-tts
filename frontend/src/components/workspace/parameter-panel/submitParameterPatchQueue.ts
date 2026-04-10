export interface ParameterPatchTask {
  kind: "voice-binding" | "render-profile" | "edge";
  submit: () => Promise<void>;
}

export function createParameterPatchQueue() {
  async function run(tasks: ParameterPatchTask[]) {
    for (const task of tasks) {
      try {
        await task.submit();
      } catch (error) {
        return {
          status: "failed" as const,
          failedTaskKind: task.kind,
          error,
        };
      }
    }

    return {
      status: "completed" as const,
      failedTaskKind: null,
      error: null,
    };
  }

  return {
    run,
  };
}
