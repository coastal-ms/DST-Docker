/** Docker administrators choose the action itself; no second browser dialog. */
export function confirmAction(message: string): boolean {
  return import.meta.env.VITE_DST_EDITION === 'docker' || window.confirm(message)
}

export function promptConfirmation(expected: string, message: string): string | null {
  return import.meta.env.VITE_DST_EDITION === 'docker' ? expected : window.prompt(message)
}
