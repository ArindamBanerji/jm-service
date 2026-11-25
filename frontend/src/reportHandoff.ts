// A one-use in-memory handoff. Browser history holds only an opaque reference.
const files = new Map<string, { file: File; ownerKey: string }>()

export function storeReportFile(file: File): string {
  const id = crypto.randomUUID()
  files.set(id, { file, ownerKey: localStorage.getItem('rgi-api-key') ?? '' })
  return id
}

export function takeReportFile(id: string | undefined): File | null {
  if (!id) return null
  const entry = files.get(id)
  files.delete(id)
  return entry && entry.ownerKey === (localStorage.getItem('rgi-api-key') ?? '') ? entry.file : null
}

window.addEventListener('dlj-account-changing', () => files.clear())
