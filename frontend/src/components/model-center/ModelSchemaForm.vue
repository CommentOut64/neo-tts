<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  schema: Array<Record<string, unknown>>;
}>();

const visibleFields = computed(() =>
  props.schema.filter((field) => field.visibility !== 'hidden'),
);

const requiredFields = computed(() =>
  visibleFields.value.filter((field) => field.visibility === "required"),
);
const optionalFields = computed(() =>
  visibleFields.value.filter((field) => field.visibility === "optional"),
);
const advancedFields = computed(() =>
  visibleFields.value.filter((field) => field.visibility === "advanced"),
);
</script>

<template>
  <div class="space-y-4">
    <div v-if="requiredFields.length > 0">
      <h3 class="mb-2 text-sm font-semibold text-foreground">required</h3>
      <div v-for="field in requiredFields" :key="String(field.field_key)" class="text-sm text-foreground">
        {{ field.label }}
      </div>
    </div>

    <div v-if="optionalFields.length > 0">
      <h3 class="mb-2 text-sm font-semibold text-foreground">optional</h3>
      <div v-for="field in optionalFields" :key="String(field.field_key)" class="text-sm text-foreground">
        {{ field.label }}
      </div>
    </div>

    <div v-if="advancedFields.length > 0">
      <h3 class="mb-2 text-sm font-semibold text-foreground">advanced</h3>
      <div v-for="field in advancedFields" :key="String(field.field_key)" class="text-sm text-foreground">
        {{ field.label }}
      </div>
    </div>
  </div>
</template>
