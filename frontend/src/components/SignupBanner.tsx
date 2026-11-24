import { Link } from 'react-router-dom'
import { hasApiKey } from '../api'

export default function SignupBanner() {
  return hasApiKey() ? null : <div className="notice">Start your free trial to score and review labels. <Link to="/signup"><strong>Start your free trial →</strong></Link></div>
}
