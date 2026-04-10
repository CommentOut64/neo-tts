export function resolveSegmentBlockElement(
  target: EventTarget | Element | null,
): HTMLElement | null {
  if (!(target instanceof Element)) {
    return null;
  }

  const block = target.closest("[data-segment-block]");
  return block instanceof HTMLElement ? block : null;
}
