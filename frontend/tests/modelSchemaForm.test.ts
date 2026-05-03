import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  buildSchemaFormModel,
  filterVisibleSchemaFields,
  getSchemaFieldValue,
  setSchemaFieldValue,
} from "../src/features/model-center/schemaForm";
import type { TtsRegistryFieldSchema } from "../src/types/ttsRegistry";

function resolveFromTests(relativePath: string) {
  return resolve(dirname(fileURLToPath(import.meta.url)), relativePath);
}

const modelSchemaFormPath = resolveFromTests("../src/components/model-center/ModelSchemaForm.vue");
const modelSchemaFormSource = readFileSync(modelSchemaFormPath, "utf8");

function buildFieldSchema(overrides: Partial<TtsRegistryFieldSchema>): TtsRegistryFieldSchema {
  return {
    field_key: "display_name",
    label: "字段",
    visibility: "optional",
    input_kind: "text",
    ...overrides,
  };
}

describe("model schema form", () => {
  it("schema form component exists and exposes modelValue update flow", () => {
    expect(existsSync(modelSchemaFormPath)).toBe(true);
    expect(modelSchemaFormSource).toContain("modelValue");
    expect(modelSchemaFormSource).toContain("update:modelValue");
    expect(modelSchemaFormSource).toContain("showAdvanced");
    expect(modelSchemaFormSource).toContain("el-input");
    expect(modelSchemaFormSource).toContain("el-input-number");
    expect(modelSchemaFormSource).toContain("el-select");
    expect(modelSchemaFormSource).toContain("el-switch");
  });

  it("filters hidden fields and merges schema defaults into the form model", () => {
    const schema: TtsRegistryFieldSchema[] = [
      buildFieldSchema({
        field_key: "display_name",
        visibility: "required",
        default_value: "默认工作区",
      }),
      buildFieldSchema({
        field_key: "endpoint.url",
        visibility: "required",
        default_value: "https://default.example.com/tts",
      }),
      buildFieldSchema({
        field_key: "runtime_profile",
        input_kind: "textarea",
        default_value: { timeout_ms: 3000 },
      }),
      buildFieldSchema({
        field_key: "api_key",
        visibility: "hidden",
        input_kind: "password",
        secret_name: "api_key",
      }),
    ];

    expect(filterVisibleSchemaFields(schema).map((field) => field.field_key)).toEqual([
      "display_name",
      "endpoint.url",
      "runtime_profile",
    ]);

    expect(
      buildSchemaFormModel(schema, {
        display_name: "自定义工作区",
        endpoint: {
          url: "https://custom.example.com/tts",
        },
      }),
    ).toEqual({
      display_name: "自定义工作区",
      endpoint: {
        url: "https://custom.example.com/tts",
      },
      runtime_profile: {
        timeout_ms: 3000,
      },
    });
  });

  it("reads and writes dotted path fields against nested models", () => {
    const initialModel = buildSchemaFormModel([], {
      endpoint: {
        url: "https://before.example.com/tts",
      },
    });

    expect(getSchemaFieldValue(initialModel, "endpoint.url")).toBe("https://before.example.com/tts");

    const updatedModel = setSchemaFieldValue(initialModel, "endpoint.url", "https://after.example.com/tts");

    expect(getSchemaFieldValue(updatedModel, "endpoint.url")).toBe("https://after.example.com/tts");
    expect(updatedModel).toEqual({
      endpoint: {
        url: "https://after.example.com/tts",
      },
    });
  });
});
