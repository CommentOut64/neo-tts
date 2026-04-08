export interface EdgeBoundaryStrategyOption {
  value: string;
  label: string;
}

const EDGE_BOUNDARY_STRATEGY_LABELS: Record<string, string> = {
  latent_overlap_then_equal_power_crossfade:
    "智能交叉淡化（Adaptive Crossfade）",
  crossfade: "简单交叉淡化（Simple Crossfade）",
  hard_cut: "直接硬切（Hard Cut）",
  crossfade_only: "兼容交叉淡化（Fallback Crossfade）",
};

export const EDGE_BOUNDARY_STRATEGY_OPTIONS: EdgeBoundaryStrategyOption[] = [
  {
    value: "latent_overlap_then_equal_power_crossfade",
    label: EDGE_BOUNDARY_STRATEGY_LABELS.latent_overlap_then_equal_power_crossfade,
  },
  {
    value: "crossfade",
    label: EDGE_BOUNDARY_STRATEGY_LABELS.crossfade,
  },
  {
    value: "hard_cut",
    label: EDGE_BOUNDARY_STRATEGY_LABELS.hard_cut,
  },
];

export function formatEdgeBoundaryStrategyLabel(
  strategy: string | null | undefined,
): string {
  if (!strategy) {
    return "未设置";
  }
  return EDGE_BOUNDARY_STRATEGY_LABELS[strategy] ?? `自定义策略（${strategy}）`;
}

export function formatPauseDurationSeconds(
  seconds: number | null | undefined,
): string {
  if (seconds == null) {
    return "停顿";
  }
  return Number(seconds).toFixed(2);
}
