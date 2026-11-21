import type { Tier } from '../api'
export default function TierBadge({ tier }: { tier: Tier }) { return <span className={`tier tier-${tier}`}>{tier.toUpperCase()}</span> }
