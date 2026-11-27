// One owner for every multi-request browser operation. The generation also
// invalidates an A -> B -> A credential rotation, even if the key text matches.
let generation = 0
let accountGeneration = 0
export const getAccountGeneration = () => accountGeneration
const controllers = new Map<AbortController, string>()
const invalidate = () => {
  generation += 1
  for (const controller of controllers.keys()) controller.abort()
  controllers.clear()
}
window.addEventListener('dlj-account-changing', () => { accountGeneration++; invalidate() })
window.addEventListener('dlj-route-changing', () => {
  const route = window.location.hash.split('?')[0]
  for (const [controller, ownerRoute] of controllers) {
    if (ownerRoute !== route) {
      controller.abort()
      controllers.delete(controller)
    }
  }
})
window.addEventListener('dlj-project-changing', invalidate)

export interface OperationContext {
  credential: string | null
  domainId: string
  projectId: string | null
  generation: number
  operationId: string
  signal: AbortSignal
  isCurrent: () => boolean
  finish: () => void
}

export function captureOperation(domainId: string, projectId: string | null): OperationContext {
  const credential = localStorage.getItem('rgi-api-key')
  const route = window.location.hash.split('?')[0]
  const capturedGeneration = generation
  const controller = new AbortController()
  const operationId = crypto.randomUUID()
  controllers.set(controller, route)
  const isCurrent = () => {
    const routeProject = /^#\/projects\/([^/]+)/.exec(window.location.hash)?.[1] ?? null
    return !controller.signal.aborted && generation === capturedGeneration && window.location.hash.split('?')[0] === route &&
      localStorage.getItem('rgi-api-key') === credential && routeProject === projectId &&
      (projectId !== null || (localStorage.getItem('rgi-domain') ?? '') === domainId)
  }
  return { credential, domainId, projectId, generation: capturedGeneration, operationId,
    signal: controller.signal, isCurrent, finish: () => { controllers.delete(controller); controller.abort() } }
}
