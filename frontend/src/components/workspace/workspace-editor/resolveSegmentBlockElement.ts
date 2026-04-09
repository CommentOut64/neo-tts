export function resolveSegmentBlockElement(
  target: EventTarget | Element | null,
): HTMLElement | null {
  if (!(target instanceof Element)) {
    return null;
  }

  const block = target.closest("[data-segment-id]");
  return block instanceof HTMLElement ? block : null;
}
