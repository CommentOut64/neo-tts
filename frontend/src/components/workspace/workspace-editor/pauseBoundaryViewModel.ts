export function shouldHighlightPauseBoundaryAsDirty(input: {
  edgeId: string | null;
  dirtyEdgeIds: ReadonlySet<string>;
}): boolean {
  return Boolean(input.edgeId && input.dirtyEdgeIds.has(input.edgeId));
}

export function resolvePauseBoundaryChipClass(input: {
  isCrossBlock: boolean;
  isDirty: boolean;
}): string {
  const classes = input.isCrossBlock
    ? [
        "inline-flex",
        "h-6",
        "items-center",
        "gap-1",
        "rounded",
        "border",
        "border-dashed",
        "border-border",
        "bg-card",
        "px-2",
        "text-[11px]",
        "font-medium",
        "text-muted-fg",
        "transition-colors",
        "hover:bg-muted/70",
      ]
    : [
        "inline-flex",
        "h-6",
        "items-center",
        "gap-1",
        "rounded",
        "border",
        "border-border",
        "bg-muted",
        "px-2",
        "text-[11px]",
        "font-medium",
        "text-muted-fg",
        "transition-colors",
        "hover:bg-muted/80",
      ];

  if (input.isDirty) {
    classes.push("pause-boundary-dirty");
  }

  return classes.join(" ");
}
