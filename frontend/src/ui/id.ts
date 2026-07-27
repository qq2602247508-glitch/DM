let fallbackSequence = 0;

/**
 * Generates request/UI identifiers without assuming Web Crypto randomUUID.
 *
 * Older Safari/WebKit builds can expose `crypto` but not `randomUUID`, which
 * previously made every player action fail before the request left the page.
 */
export function createClientId(prefix = "client"): string {
  const secureUuid = globalThis.crypto?.randomUUID?.();
  if (secureUuid) return secureUuid;
  fallbackSequence = (fallbackSequence + 1) % Number.MAX_SAFE_INTEGER;
  const random = Math.random().toString(36).slice(2, 12);
  return `${prefix}-${Date.now().toString(36)}-${fallbackSequence.toString(36)}-${random}`;
}
