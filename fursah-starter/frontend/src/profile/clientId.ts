/**
 * Browser-scoped client identity for saved ("مهتم") opportunities.
 *
 * FURSAH has no authentication, so this is NOT a real user id: it is a random id kept in this
 * browser's localStorage. It scopes saved opportunities to this device/browser only, and the
 * UI never presents it as a signed-in user. If storage is unavailable, an ephemeral id is used
 * for the session so the feature still works without pretending there is an account.
 */
const KEY = 'fursah.client_id';
let ephemeral: string | null = null;

function fresh(): string {
  return globalThis.crypto?.randomUUID?.() ?? `c-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function getClientId(): string {
  try {
    let id = localStorage.getItem(KEY);
    if (!id) { id = fresh(); localStorage.setItem(KEY, id); }
    return id;
  } catch {
    return (ephemeral ??= fresh());
  }
}
