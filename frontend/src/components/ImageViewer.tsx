import { useEffect, useState } from 'react'
import LoadingSpinner from './LoadingSpinner'

interface Props { imageUrl: string; category: string | null; readOnly: true }

export default function ImageViewer({ imageUrl, category }: Props) {
  const [state, setState] = useState<'loading' | 'loaded' | 'error'>('loading')
  useEffect(() => setState('loading'), [imageUrl])
  return <section aria-label="Image classification" className="image-viewer">
    <h3 className="section-title">Image</h3>
    {state === 'loading' && <div role="status" aria-label="Loading image"><LoadingSpinner /></div>}
    {state === 'error' && <div className="image-error" role="alert"><span aria-hidden="true">▧</span> Image not available</div>}
    <img src={imageUrl} alt="Source image for classification" style={{ display: state === 'loaded' ? 'block' : 'none' }}
      onLoad={() => setState('loaded')} onError={() => setState('error')} />
    <div className="image-category">Category: <span className="pill">{category ?? 'Unclassified'}</span></div>
  </section>
}
