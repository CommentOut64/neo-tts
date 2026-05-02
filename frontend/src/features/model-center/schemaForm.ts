import type { TtsRegistryFieldSchema } from "@/types/ttsRegistry";

type SchemaFormModel = Record<string, unknown>;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cloneValue<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => cloneValue(item)) as T;
  }
  if (isPlainObject(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, nestedValue]) => [key, cloneValue(nestedValue)]),
    ) as T;
  }
  return value;
}

function mergeValueWithDefault(defaultValue: unknown, currentValue: unknown): unknown {
  if (currentValue === undefined) {
    return cloneValue(defaultValue);
  }
  if (isPlainObject(defaultValue) && isPlainObject(currentValue)) {
    const merged: Record<string, unknown> = cloneValue(defaultValue);
    for (const [key, value] of Object.entries(currentValue)) {
      merged[key] = key in merged ? mergeValueWithDefault(merged[key], value) : cloneValue(value);
    }
    return merged;
  }
  return cloneValue(currentValue);
}

function getPathSegments(fieldKey: string): string[] {
  return fieldKey
    .split(".")
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);
}

function cloneModel(model: SchemaFormModel | null | undefined): SchemaFormModel {
  if (!isPlainObject(model)) {
    return {};
  }
  return cloneValue(model);
}

export function filterVisibleSchemaFields(schema: TtsRegistryFieldSchema[]): TtsRegistryFieldSchema[] {
  return schema.filter((field) => field.visibility !== "hidden");
}

export function getSchemaFieldValue(model: Record<string, unknown> | null | undefined, fieldKey: string): unknown {
  const segments = getPathSegments(fieldKey);
  let current: unknown = model ?? {};
  for (const segment of segments) {
    if (!isPlainObject(current) || !(segment in current)) {
      return undefined;
    }
    current = current[segment];
  }
  return current;
}

export function setSchemaFieldValue(
  model: Record<string, unknown> | null | undefined,
  fieldKey: string,
  value: unknown,
): SchemaFormModel {
  const segments = getPathSegments(fieldKey);
  const nextModel = cloneModel(model);
  if (segments.length === 0) {
    return nextModel;
  }

  let cursor: Record<string, unknown> = nextModel;
  for (const segment of segments.slice(0, -1)) {
    const existingValue = cursor[segment];
    if (!isPlainObject(existingValue)) {
      cursor[segment] = {};
    }
    cursor = cursor[segment] as Record<string, unknown>;
  }
  cursor[segments[segments.length - 1]] = cloneValue(value);
  return nextModel;
}

export function buildSchemaFormModel(
  schema: TtsRegistryFieldSchema[],
  modelValue: Record<string, unknown> | null | undefined,
): SchemaFormModel {
  const nextModel = cloneModel(modelValue);
  for (const field of filterVisibleSchemaFields(schema)) {
    if (field.default_value === undefined) {
      continue;
    }
    const currentValue = getSchemaFieldValue(nextModel, field.field_key);
    const mergedValue = mergeValueWithDefault(field.default_value, currentValue);
    if (mergedValue !== undefined) {
      Object.assign(nextModel, setSchemaFieldValue(nextModel, field.field_key, mergedValue));
    }
  }
  return nextModel;
}

export function isSchemaObjectLikeValue(value: unknown): value is Record<string, unknown> | unknown[] {
  return isPlainObject(value) || Array.isArray(value);
}
