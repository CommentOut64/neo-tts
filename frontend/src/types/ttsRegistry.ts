import type { BindingReference } from "@/types/editSession";

export type RegistryStatus =
  | "ready"
  | "needs_secret"
  | "invalid"
  | "disabled"
  | "pending_delete";

export interface TtsRegistryFieldSchema {
  field_key: string;
  label: string;
  scope?: "workspace" | "main_model" | "submodel" | "preset";
  visibility: "required" | "optional" | "advanced" | "hidden";
  input_kind?: string;
  required?: boolean;
  default_value?: unknown;
  validation?: Record<string, unknown> | null;
  secret_name?: string | null;
  help_text?: string | null;
}

export interface TtsRegistryFamilyDefinition {
  family_id: string;
  adapter_id: string;
  display_name: string;
  route_slug: string;
  supports_main_models: boolean;
  supports_submodels: boolean;
  supports_presets: boolean;
  auto_singleton_submodel: boolean;
  auto_singleton_preset: boolean;
  workspace_form_schema: TtsRegistryFieldSchema[];
  main_model_form_schema: TtsRegistryFieldSchema[];
  submodel_form_schema: TtsRegistryFieldSchema[];
  preset_form_schema: TtsRegistryFieldSchema[];
  binding_display_strategy: string;
}

export interface TtsRegistryAdapterDefinition {
  adapter_id: string;
  display_name: string;
  adapter_family: string;
  runtime_kind: string;
  supported_families?: string[];
  option_schema?: Record<string, unknown>;
}

export interface TtsRegistryWorkspaceRecord {
  workspace_id: string;
  adapter_id: string;
  family_id: string;
  display_name: string;
  slug: string;
  status: Extract<RegistryStatus, "ready" | "disabled" | "invalid" | "pending_delete">;
  ui_order?: number;
  created_at?: string;
  updated_at?: string;
}

export interface TtsRegistryWorkspaceSummary extends TtsRegistryWorkspaceRecord {
  family_display_name: string;
  family_route_slug: string;
  binding_display_strategy: string;
}

export interface TtsRegistryPresetOption {
  display_name: string;
  preset_id: string;
  status: Extract<RegistryStatus, "ready" | "invalid" | "disabled" | "pending_delete">;
  is_hidden_singleton: boolean;
  binding_ref: BindingReference;
  reference_audio_path: string | null;
  reference_text: string | null;
  reference_language: string | null;
  defaults: Record<string, unknown>;
  fixed_fields: Record<string, unknown>;
}

export interface TtsRegistrySubmodelOption {
  display_name: string;
  submodel_id: string;
  status: RegistryStatus;
  is_hidden_singleton: boolean;
  presets: TtsRegistryPresetOption[];
}

export interface TtsRegistryMainModelOption {
  display_name: string;
  main_model_id: string;
  status: Extract<RegistryStatus, "ready" | "disabled" | "invalid" | "pending_delete">;
  default_submodel_id: string | null;
  submodels: TtsRegistrySubmodelOption[];
}

export interface TtsRegistryWorkspaceOption {
  workspace_id: string;
  adapter_id: string;
  family_id: string;
  display_name: string;
  slug: string;
  status: Extract<RegistryStatus, "ready" | "disabled" | "invalid" | "pending_delete">;
  family_display_name: string;
  family_route_slug: string;
  binding_display_strategy: string;
  main_models: TtsRegistryMainModelOption[];
}

export interface BindingCatalogResponse {
  items: TtsRegistryWorkspaceOption[];
}

export interface RegistryBindingOption {
  bindingKey: string;
  bindingRef: BindingReference;
  workspaceId: string;
  workspaceDisplayName: string;
  familyId: string;
  familyRouteSlug: string;
  familyDisplayName: string;
  adapterId: string;
  mainModelId: string;
  mainModelDisplayName: string;
  submodelId: string;
  submodelDisplayName: string;
  presetId: string;
  presetDisplayName: string;
  label: string;
  status: RegistryStatus;
  referenceAudioPath: string | null;
  referenceText: string | null;
  referenceLanguage: string | null;
  defaults: Record<string, unknown>;
  fixedFields: Record<string, unknown>;
}

export interface TtsRegistryPresetRecord {
  preset_id: string;
  workspace_id: string;
  main_model_id: string;
  submodel_id: string;
  display_name: string;
  status: Extract<RegistryStatus, "ready" | "invalid" | "disabled" | "pending_delete">;
  kind: "builtin" | "imported" | "remote" | "user";
  defaults: Record<string, unknown>;
  fixed_fields: Record<string, unknown>;
  preset_assets: Record<string, unknown>;
  is_hidden_singleton: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface TtsRegistryPresetNode extends TtsRegistryPresetRecord {}

export interface TtsRegistrySubmodelRecord {
  submodel_id: string;
  workspace_id: string;
  main_model_id: string;
  display_name: string;
  status: RegistryStatus;
  instance_assets: Record<string, unknown>;
  endpoint: Record<string, unknown> | null;
  account_binding: Record<string, unknown> | null;
  adapter_options: Record<string, unknown>;
  runtime_profile: Record<string, unknown>;
  is_hidden_singleton: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface TtsRegistrySubmodelNode extends TtsRegistrySubmodelRecord {
  presets: TtsRegistryPresetNode[];
}

export interface TtsRegistryMainModelRecord {
  main_model_id: string;
  workspace_id: string;
  display_name: string;
  status: Extract<RegistryStatus, "ready" | "disabled" | "invalid" | "pending_delete">;
  source_type: "local_package" | "external_api" | "builtin";
  main_model_metadata: Record<string, unknown>;
  default_submodel_id: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface TtsRegistryMainModelNode extends TtsRegistryMainModelRecord {
  submodels: TtsRegistrySubmodelNode[];
}

export interface TtsRegistryWorkspaceTree {
  workspace: TtsRegistryWorkspaceRecord;
  main_models: TtsRegistryMainModelNode[];
}

export interface CreateRegistryWorkspacePayload {
  adapter_id: string;
  family_id: string;
  display_name: string;
  slug: string;
}

export interface PatchRegistryWorkspacePayload {
  display_name?: string;
  slug?: string;
  status?: Extract<RegistryStatus, "ready" | "disabled" | "invalid" | "pending_delete">;
  ui_order?: number;
}

export interface CreateRegistryMainModelPayload {
  main_model_id: string;
  display_name: string;
  source_type?: "local_package" | "external_api" | "builtin";
  main_model_metadata?: Record<string, unknown>;
}

export interface PatchRegistryMainModelPayload {
  display_name?: string;
  status?: Extract<RegistryStatus, "ready" | "disabled" | "invalid" | "pending_delete">;
  main_model_metadata?: Record<string, unknown>;
  default_submodel_id?: string | null;
}

export interface CreateRegistrySubmodelPayload {
  submodel_id: string;
  display_name: string;
  status?: RegistryStatus;
  instance_assets?: Record<string, unknown>;
  endpoint?: Record<string, unknown> | null;
  account_binding?: Record<string, unknown> | null;
  adapter_options?: Record<string, unknown>;
  runtime_profile?: Record<string, unknown>;
  is_hidden_singleton?: boolean;
}

export interface PatchRegistrySubmodelPayload {
  display_name?: string;
  status?: RegistryStatus;
  instance_assets?: Record<string, unknown>;
  endpoint?: Record<string, unknown> | null;
  account_binding?: Record<string, unknown> | null;
  adapter_options?: Record<string, unknown>;
  runtime_profile?: Record<string, unknown>;
}

export interface PutRegistrySubmodelSecretsPayload {
  secrets: Record<string, string>;
}

export interface TtsRegistrySubmodelConnectivityCheckResult {
  status: RegistryStatus;
  workspace_id: string;
  main_model_id: string;
  submodel_id: string;
}

export interface CreateRegistryPresetPayload {
  preset_id: string;
  display_name: string;
  kind?: "builtin" | "imported" | "remote" | "user";
  status?: Extract<RegistryStatus, "ready" | "invalid" | "disabled" | "pending_delete">;
  defaults?: Record<string, unknown>;
  fixed_fields?: Record<string, unknown>;
  preset_assets?: Record<string, unknown>;
  is_hidden_singleton?: boolean;
}

export interface PatchRegistryPresetPayload {
  display_name?: string;
  status?: Extract<RegistryStatus, "ready" | "invalid" | "disabled" | "pending_delete">;
  defaults?: Record<string, unknown>;
  fixed_fields?: Record<string, unknown>;
  preset_assets?: Record<string, unknown>;
}

export interface TtsRegistryDeleteResult {
  status: "deleted";
  workspace_id: string;
  main_model_id?: string;
  submodel_id?: string;
  preset_id?: string;
}

export function buildBindingKey(bindingRef: BindingReference): string {
  return [
    bindingRef.workspace_id,
    bindingRef.main_model_id,
    bindingRef.submodel_id,
    bindingRef.preset_id,
  ].join(":");
}

export function flattenBindingCatalog(
  catalog: BindingCatalogResponse,
): RegistryBindingOption[] {
  const bindings: RegistryBindingOption[] = [];

  for (const workspace of catalog.items) {
    for (const mainModel of workspace.main_models) {
      for (const submodel of mainModel.submodels) {
        for (const preset of submodel.presets) {
          const bindingKey = buildBindingKey(preset.binding_ref);
          bindings.push({
            bindingKey,
            bindingRef: preset.binding_ref,
            workspaceId: workspace.workspace_id,
            workspaceDisplayName: workspace.display_name,
            familyId: workspace.family_id,
            familyRouteSlug: workspace.family_route_slug,
            familyDisplayName: workspace.family_display_name,
            adapterId: workspace.adapter_id,
            mainModelId: mainModel.main_model_id,
            mainModelDisplayName: mainModel.display_name,
            submodelId: submodel.submodel_id,
            submodelDisplayName: submodel.display_name,
            presetId: preset.preset_id,
            presetDisplayName: preset.display_name,
            label: [
              workspace.display_name,
              mainModel.display_name,
              submodel.is_hidden_singleton ? null : submodel.display_name,
              preset.is_hidden_singleton ? null : preset.display_name,
            ]
              .filter((part): part is string => Boolean(part && part.trim().length > 0))
              .join(" / "),
            status: preset.status,
            referenceAudioPath: preset.reference_audio_path,
            referenceText: preset.reference_text,
            referenceLanguage: preset.reference_language,
            defaults: preset.defaults,
            fixedFields: preset.fixed_fields,
          });
        }
      }
    }
  }

  return bindings;
}
