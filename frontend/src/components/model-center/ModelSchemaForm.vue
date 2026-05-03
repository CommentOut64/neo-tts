<script setup lang="ts">
import { computed, reactive } from "vue";

import {
  buildSchemaFormModel,
  filterVisibleSchemaFields,
  getSchemaFieldValue,
  isSchemaObjectLikeValue,
  setSchemaFieldValue,
} from "@/features/model-center/schemaForm";
import type { TtsRegistryFieldSchema } from "@/types/ttsRegistry";

const props = withDefaults(defineProps<{
  schema: TtsRegistryFieldSchema[];
  modelValue?: Record<string, unknown> | null;
  disabled?: boolean;
  showAdvanced?: boolean;
}>(), {
  modelValue: null,
  disabled: false,
  showAdvanced: true,
});

const emit = defineEmits<{
  "update:modelValue": [value: Record<string, unknown>];
}>();

const jsonDrafts = reactive<Record<string, string>>({});
const jsonErrors = reactive<Record<string, string>>({});

const visibleFields = computed(() => filterVisibleSchemaFields(props.schema));
const requiredFields = computed(() =>
  visibleFields.value.filter((field) => field.visibility === "required"),
);
const optionalFields = computed(() =>
  visibleFields.value.filter((field) => field.visibility === "optional"),
);
const advancedFields = computed(() =>
  props.showAdvanced
    ? visibleFields.value.filter((field) => field.visibility === "advanced")
    : [],
);
const formModel = computed(() => buildSchemaFormModel(props.schema, props.modelValue));

function updateFieldValue(fieldKey: string, value: unknown) {
  emit("update:modelValue", setSchemaFieldValue(formModel.value, fieldKey, value));
}

function getFieldValue(field: TtsRegistryFieldSchema): unknown {
  return getSchemaFieldValue(formModel.value, field.field_key);
}

function getTextValue(field: TtsRegistryFieldSchema): string {
  const value = getFieldValue(field);
  if (value === undefined || value === null) {
    return "";
  }
  return typeof value === "string" ? value : String(value);
}

function getNumberValue(field: TtsRegistryFieldSchema): number | null {
  const value = getFieldValue(field);
  if (typeof value === "number") {
    return value;
  }
  if (value === undefined || value === null || value === "") {
    return null;
  }
  const normalizedValue = Number(value);
  return Number.isFinite(normalizedValue) ? normalizedValue : null;
}

function getSwitchValue(field: TtsRegistryFieldSchema): boolean {
  return Boolean(getFieldValue(field));
}

function getSelectValue(field: TtsRegistryFieldSchema): string | number | boolean | null {
  const value = getFieldValue(field);
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  return null;
}

function isJsonFallbackField(field: TtsRegistryFieldSchema): boolean {
  const inputKind = field.input_kind ?? "text";
  if (inputKind === "number" || inputKind === "switch" || inputKind === "select") {
    return false;
  }
  const currentValue = getFieldValue(field);
  return isSchemaObjectLikeValue(currentValue ?? field.default_value);
}

function getJsonValue(field: TtsRegistryFieldSchema): string {
  const draftValue = jsonDrafts[field.field_key];
  if (draftValue !== undefined) {
    return draftValue;
  }
  const value = getFieldValue(field);
  if (value === undefined || value === null || value === "") {
    return "";
  }
  return JSON.stringify(value, null, 2);
}

function handleJsonInput(field: TtsRegistryFieldSchema, rawValue: string) {
  jsonDrafts[field.field_key] = rawValue;
  if (!rawValue.trim()) {
    delete jsonErrors[field.field_key];
    delete jsonDrafts[field.field_key];
    updateFieldValue(field.field_key, isSchemaObjectLikeValue(field.default_value) ? field.default_value : {});
    return;
  }

  try {
    const parsedValue = JSON.parse(rawValue);
    delete jsonErrors[field.field_key];
    delete jsonDrafts[field.field_key];
    updateFieldValue(field.field_key, parsedValue);
  } catch {
    jsonErrors[field.field_key] = "请输入合法 JSON";
  }
}

function resolveSelectOptions(field: TtsRegistryFieldSchema): Array<{ label: string; value: string | number | boolean }> {
  const validation = field.validation ?? {};
  const rawOptions =
    (Array.isArray(validation.options) && validation.options) ||
    (Array.isArray(validation.enum) && validation.enum) ||
    (Array.isArray(validation.choices) && validation.choices) ||
    [];

  return rawOptions
    .map((option) => {
      if (
        typeof option === "string" ||
        typeof option === "number" ||
        typeof option === "boolean"
      ) {
        return {
          label: String(option),
          value: option,
        };
      }
      if (
        typeof option === "object" &&
        option !== null &&
        "value" in option &&
        (
          typeof option.value === "string" ||
          typeof option.value === "number" ||
          typeof option.value === "boolean"
        )
      ) {
        return {
          label: typeof option.label === "string" ? option.label : String(option.value),
          value: option.value,
        };
      }
      return null;
    })
    .filter((option): option is { label: string; value: string | number | boolean } => option !== null);
}

function isRequiredField(field: TtsRegistryFieldSchema): boolean {
  return field.required === true || field.visibility === "required";
}

function isEmptyValue(value: unknown): boolean {
  if (value === undefined || value === null) {
    return true;
  }
  if (typeof value === "string") {
    return value.trim().length === 0;
  }
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  if (isSchemaObjectLikeValue(value)) {
    return Object.keys(value).length === 0;
  }
  return false;
}

function resolveValidationMessage(field: TtsRegistryFieldSchema): string {
  if (jsonErrors[field.field_key]) {
    return jsonErrors[field.field_key];
  }

  const value = getFieldValue(field);
  if (isRequiredField(field) && isEmptyValue(value)) {
    return "必填项";
  }

  if ((field.input_kind ?? "text") === "number" && value !== undefined && value !== null && value !== "") {
    const normalizedValue = Number(value);
    if (!Number.isFinite(normalizedValue)) {
      return "请输入数字";
    }
    const validation = field.validation ?? {};
    if (typeof validation.min === "number" && normalizedValue < validation.min) {
      return `不能小于 ${validation.min}`;
    }
    if (typeof validation.max === "number" && normalizedValue > validation.max) {
      return `不能大于 ${validation.max}`;
    }
  }

  if (typeof value === "string") {
    const validation = field.validation ?? {};
    if (typeof validation.min_length === "number" && value.length < validation.min_length) {
      return `至少输入 ${validation.min_length} 个字符`;
    }
    if (typeof validation.max_length === "number" && value.length > validation.max_length) {
      return `最多输入 ${validation.max_length} 个字符`;
    }
  }

  return "";
}

function resolveInputKind(field: TtsRegistryFieldSchema): string {
  if (isJsonFallbackField(field)) {
    return "json";
  }
  const inputKind = field.input_kind ?? "text";
  if (["text", "textarea", "number", "password", "switch", "select"].includes(inputKind)) {
    return inputKind;
  }
  return "text";
}

function resolvePlaceholder(field: TtsRegistryFieldSchema): string {
  if (resolveInputKind(field) === "json") {
    return "请输入 JSON";
  }
  return `请输入${field.label}`;
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="requiredFields.length > 0" class="space-y-3">
      <h3 class="text-sm font-semibold text-foreground">required</h3>
      <div
        v-for="field in requiredFields"
        :key="field.field_key"
        class="rounded-card border border-border/60 bg-secondary/10 p-3"
      >
        <div class="mb-2 flex items-center gap-2">
          <span class="text-sm font-medium text-foreground">{{ field.label }}</span>
          <span v-if="isRequiredField(field)" class="text-xs text-danger">*</span>
        </div>
        <p v-if="field.help_text" class="mb-2 text-xs text-muted-fg">{{ field.help_text }}</p>

        <el-input
          v-if="resolveInputKind(field) === 'text' || resolveInputKind(field) === 'password'"
          :model-value="getTextValue(field)"
          :type="resolveInputKind(field) === 'password' ? 'password' : 'text'"
          :show-password="resolveInputKind(field) === 'password'"
          :disabled="disabled"
          :placeholder="resolvePlaceholder(field)"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        />
        <el-input
          v-else-if="resolveInputKind(field) === 'textarea'"
          :model-value="getTextValue(field)"
          :disabled="disabled"
          :rows="4"
          type="textarea"
          :placeholder="resolvePlaceholder(field)"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        />
        <el-input
          v-else-if="resolveInputKind(field) === 'json'"
          :model-value="getJsonValue(field)"
          :disabled="disabled"
          :rows="5"
          type="textarea"
          placeholder="请输入 JSON"
          @update:model-value="handleJsonInput(field, $event)"
        />
        <el-input-number
          v-else-if="resolveInputKind(field) === 'number'"
          :model-value="getNumberValue(field)"
          :disabled="disabled"
          class="w-full"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        />
        <el-select
          v-else-if="resolveInputKind(field) === 'select'"
          :model-value="getSelectValue(field)"
          :disabled="disabled"
          class="w-full"
          :placeholder="resolvePlaceholder(field)"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        >
          <el-option
            v-for="option in resolveSelectOptions(field)"
            :key="`${field.field_key}-${String(option.value)}`"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <div v-else-if="resolveInputKind(field) === 'switch'" class="flex items-center justify-between gap-3">
          <span class="text-sm text-muted-fg">开关</span>
          <el-switch
            :model-value="getSwitchValue(field)"
            :disabled="disabled"
            @update:model-value="updateFieldValue(field.field_key, $event)"
          />
        </div>

        <p v-if="resolveValidationMessage(field)" class="mt-2 text-xs text-danger">
          {{ resolveValidationMessage(field) }}
        </p>
      </div>
    </div>

    <div v-if="optionalFields.length > 0" class="space-y-3">
      <h3 class="text-sm font-semibold text-foreground">optional</h3>
      <div
        v-for="field in optionalFields"
        :key="field.field_key"
        class="rounded-card border border-border/60 bg-secondary/10 p-3"
      >
        <div class="mb-2 flex items-center gap-2">
          <span class="text-sm font-medium text-foreground">{{ field.label }}</span>
          <span v-if="isRequiredField(field)" class="text-xs text-danger">*</span>
        </div>
        <p v-if="field.help_text" class="mb-2 text-xs text-muted-fg">{{ field.help_text }}</p>

        <el-input
          v-if="resolveInputKind(field) === 'text' || resolveInputKind(field) === 'password'"
          :model-value="getTextValue(field)"
          :type="resolveInputKind(field) === 'password' ? 'password' : 'text'"
          :show-password="resolveInputKind(field) === 'password'"
          :disabled="disabled"
          :placeholder="resolvePlaceholder(field)"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        />
        <el-input
          v-else-if="resolveInputKind(field) === 'textarea'"
          :model-value="getTextValue(field)"
          :disabled="disabled"
          :rows="4"
          type="textarea"
          :placeholder="resolvePlaceholder(field)"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        />
        <el-input
          v-else-if="resolveInputKind(field) === 'json'"
          :model-value="getJsonValue(field)"
          :disabled="disabled"
          :rows="5"
          type="textarea"
          placeholder="请输入 JSON"
          @update:model-value="handleJsonInput(field, $event)"
        />
        <el-input-number
          v-else-if="resolveInputKind(field) === 'number'"
          :model-value="getNumberValue(field)"
          :disabled="disabled"
          class="w-full"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        />
        <el-select
          v-else-if="resolveInputKind(field) === 'select'"
          :model-value="getSelectValue(field)"
          :disabled="disabled"
          class="w-full"
          :placeholder="resolvePlaceholder(field)"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        >
          <el-option
            v-for="option in resolveSelectOptions(field)"
            :key="`${field.field_key}-${String(option.value)}`"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <div v-else-if="resolveInputKind(field) === 'switch'" class="flex items-center justify-between gap-3">
          <span class="text-sm text-muted-fg">开关</span>
          <el-switch
            :model-value="getSwitchValue(field)"
            :disabled="disabled"
            @update:model-value="updateFieldValue(field.field_key, $event)"
          />
        </div>

        <p v-if="resolveValidationMessage(field)" class="mt-2 text-xs text-danger">
          {{ resolveValidationMessage(field) }}
        </p>
      </div>
    </div>

    <div v-if="advancedFields.length > 0" class="space-y-3">
      <h3 class="text-sm font-semibold text-foreground">advanced</h3>
      <div
        v-for="field in advancedFields"
        :key="field.field_key"
        class="rounded-card border border-border/60 bg-secondary/10 p-3"
      >
        <div class="mb-2 flex items-center gap-2">
          <span class="text-sm font-medium text-foreground">{{ field.label }}</span>
          <span v-if="isRequiredField(field)" class="text-xs text-danger">*</span>
        </div>
        <p v-if="field.help_text" class="mb-2 text-xs text-muted-fg">{{ field.help_text }}</p>

        <el-input
          v-if="resolveInputKind(field) === 'text' || resolveInputKind(field) === 'password'"
          :model-value="getTextValue(field)"
          :type="resolveInputKind(field) === 'password' ? 'password' : 'text'"
          :show-password="resolveInputKind(field) === 'password'"
          :disabled="disabled"
          :placeholder="resolvePlaceholder(field)"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        />
        <el-input
          v-else-if="resolveInputKind(field) === 'textarea'"
          :model-value="getTextValue(field)"
          :disabled="disabled"
          :rows="4"
          type="textarea"
          :placeholder="resolvePlaceholder(field)"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        />
        <el-input
          v-else-if="resolveInputKind(field) === 'json'"
          :model-value="getJsonValue(field)"
          :disabled="disabled"
          :rows="5"
          type="textarea"
          placeholder="请输入 JSON"
          @update:model-value="handleJsonInput(field, $event)"
        />
        <el-input-number
          v-else-if="resolveInputKind(field) === 'number'"
          :model-value="getNumberValue(field)"
          :disabled="disabled"
          class="w-full"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        />
        <el-select
          v-else-if="resolveInputKind(field) === 'select'"
          :model-value="getSelectValue(field)"
          :disabled="disabled"
          class="w-full"
          :placeholder="resolvePlaceholder(field)"
          @update:model-value="updateFieldValue(field.field_key, $event)"
        >
          <el-option
            v-for="option in resolveSelectOptions(field)"
            :key="`${field.field_key}-${String(option.value)}`"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <div v-else-if="resolveInputKind(field) === 'switch'" class="flex items-center justify-between gap-3">
          <span class="text-sm text-muted-fg">开关</span>
          <el-switch
            :model-value="getSwitchValue(field)"
            :disabled="disabled"
            @update:model-value="updateFieldValue(field.field_key, $event)"
          />
        </div>

        <p v-if="resolveValidationMessage(field)" class="mt-2 text-xs text-danger">
          {{ resolveValidationMessage(field) }}
        </p>
      </div>
    </div>
  </div>
</template>
