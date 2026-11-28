/** Returns false when the visible input must be used for manual copy. */
export async function copyKey(input: HTMLInputElement): Promise<boolean> {
  const value = input.value
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(value)
      return true
    }
  } catch { /* Some browser or embedding policies deny clipboard access. */ }
  if (!input.isConnected || input.value !== value) return false
  input.focus()
  input.select()
  if (input.type === 'password') return false
  try { return document.execCommand('copy') } catch { return false }
}
