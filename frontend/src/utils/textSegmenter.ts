export function computeSegments(text: string): string[] {
  if (!text) return []
  const blocks = text.split(/\n+/)
  const result: string[] = []
  
  const puncRegex = /([。！？.!?]+)/
  for (const block of blocks) {
    const parts = block.split(puncRegex)
    let currentPart = ''
    for (let i = 0; i < parts.length; i++) {
      if (puncRegex.test(parts[i])) {
        currentPart += parts[i]
        if (currentPart.trim()) {
          result.push(currentPart.trim())
        }
        currentPart = ''
      } else {
        if (currentPart) {
          if (currentPart.trim()) result.push(currentPart.trim())
        }
        currentPart = parts[i]
      }
    }
    if (currentPart.trim()) {
      result.push(currentPart.trim())
    }
  }
  return result
}
