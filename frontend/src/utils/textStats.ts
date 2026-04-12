export function countNonPunctuationCharacters(text: string): number {
  const normalized = text.replace(/[\p{P}\s]/gu, "")
  return Array.from(normalized).length
}
