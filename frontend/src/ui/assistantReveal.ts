export function splitAssistantRevealChunks(text: string): string[] {
  const normalized = text.replace(/\r\n/g, "\n").trim();
  if (!normalized) return [];
  const lines = normalized.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  if (lines.length > 1) return lines;
  return normalized.match(/[^。！？；]+[。！？；]?/g)?.map((line) => line.trim()).filter(Boolean)
    ?? [normalized];
}
