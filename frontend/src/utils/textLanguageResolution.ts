import type { InputTextLanguage } from "@/composables/useInputDraft";

export interface TextLanguageResolutionOption {
  value: InputTextLanguage;
  label: string;
  actionLabel: string;
  description: string;
}

export interface TextLanguageResolutionDialogModel {
  title: string;
  intro: string;
  currentOption: TextLanguageResolutionOption;
  nextOption: TextLanguageResolutionOption;
}

const LANGUAGE_LABELS: Record<InputTextLanguage, string> = {
  auto: "自动检测",
  zh: "中文",
  en: "英文",
  ja: "日文",
  ko: "韩文",
};

const LANGUAGE_ACTION_LABELS: Record<InputTextLanguage, string> = {
  auto: "统一按自动检测处理",
  zh: "统一按中文处理",
  en: "统一按英文处理",
  ja: "统一按日文处理",
  ko: "统一按韩文设置处理",
};

const LANGUAGE_DESCRIPTIONS: Record<InputTextLanguage, string> = {
  auto: "系统会重新分析全文，按段识别 zh / ja / en，并据此决定标准化和推理语言提示。",
  zh: "句末标点、标准化和正式推理都以中文规则为主。",
  en: "句末标点、标准化和正式推理都以英文规则为主。",
  ja: "句末标点、标准化和正式推理都以日文规则为主。",
  ko: "当前文档会记录为韩文；标准化暂不提供韩文专门规则，正式推理将按当前韩文设置提交。",
};

function buildLanguageOption(value: InputTextLanguage): TextLanguageResolutionOption {
  return {
    value,
    label: LANGUAGE_LABELS[value],
    actionLabel: LANGUAGE_ACTION_LABELS[value],
    description: LANGUAGE_DESCRIPTIONS[value],
  };
}

export function buildTextLanguageResolutionDialogModel(
  currentLanguage: InputTextLanguage,
  nextLanguage: InputTextLanguage,
): TextLanguageResolutionDialogModel {
  return {
    title: "检测到文本语言设置不一致",
    intro: `文本输入页当前为「${LANGUAGE_LABELS[currentLanguage]}」，语音合成页刚选择了「${LANGUAGE_LABELS[nextLanguage]}」。请选择当前文档后续标准化与正式推理统一采用的文本语言规则。`,
    currentOption: buildLanguageOption(currentLanguage),
    nextOption: buildLanguageOption(nextLanguage),
  };
}
