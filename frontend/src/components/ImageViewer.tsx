import { Fragment, useEffect, useMemo, useState } from 'react'
import { useDomain } from '../domain'
import LoadingSpinner from './LoadingSpinner'

interface Props {
  imageUrl: string
  altText?: string
  readOnly?: boolean
  category?: string | null
}

function imageSourceLabel(imageUrl: string): string {
  if (imageUrl.startsWith('data:')) return 'Embedded image'
  try {
    const hostname = new URL(imageUrl).hostname.replace(/[^a-zA-Z0-9.:-]/g, '')
    return hostname || 'Image source'
  } catch { return 'Image source' }
}

export default function ImageViewer(props: Props) {
  const { projectId } = useDomain()
  return <Fragment key={projectId}><ImageContent key={props.imageUrl} {...props} projectId={projectId} /></Fragment>
}

function ImageContent({ imageUrl, altText = 'Source image for classification', readOnly = true, category, projectId }: Props & { projectId: string | null }) {
  const embedded = imageUrl.startsWith('data:')
  const consentKey = projectId ? `dlj-image-consent:${projectId}` : null
  const [consented, setConsented] = useState(() => embedded || Boolean(consentKey && sessionStorage.getItem(consentKey) === 'yes'))
  const [state, setState] = useState<'waiting' | 'loading' | 'loaded' | 'error'>(consented ? 'loading' : 'waiting')
  const sourceLabel = useMemo(() => imageSourceLabel(imageUrl), [imageUrl])
  useEffect(() => {
    const clear = () => { if (!embedded) { setConsented(false); setState('waiting') } }
    window.addEventListener('dlj-account-changing', clear)
    return () => window.removeEventListener('dlj-account-changing', clear)
  }, [embedded])
  const loadExternal = () => {
    if (consentKey) sessionStorage.setItem(consentKey, 'yes')
    setConsented(true)
    setState('loading')
  }
  return <section aria-label="Image classification" aria-readonly={readOnly} className="image-viewer">
    <h3 className="section-title">Image</h3>
    {altText && <p className="image-caption">{altText}</p>}
    {state === 'waiting' && <div className="image-consent" role="note"><strong>External image</strong>
      <p>Loading from {sourceLabel} shares your IP address with that host.</p>
      <button type="button" className="button secondary" onClick={loadExternal}>Load external image</button></div>}
    {state === 'loading' && <div className="image-skeleton" role="status" aria-label="Loading image"><LoadingSpinner /></div>}
    {state === 'error' && <div className="image-error" role="alert"><span aria-hidden="true">▧</span><strong>Image not available</strong><small>{sourceLabel}</small></div>}
    {consented && <img key={imageUrl} src={imageUrl} alt={projectId ? altText : 'Source image for classification'} loading="lazy" decoding="async" referrerPolicy="no-referrer"
      style={{ opacity: state === 'loaded' ? 1 : 0 }}
      onLoad={() => setState('loaded')} onError={() => setState('error')} />}
    {category !== undefined && <div className="image-category">Category: <span className="pill">{category ?? 'Unclassified'}</span></div>}
  </section>
}
