const plans = [
  ['Starter', '$99/month', '10,000'],
  ['Professional', '$299/month', '100,000'],
  ['Business', '$799/month', '1,000,000'],
  ['Scale', 'Custom', 'Unlimited'],
]

export default function Pricing() {
  return <div className="page">
    <h1 id="pricing-heading">Pricing</h1>
    <div className="card table-wrap">
      <table className="table" aria-labelledby="pricing-heading">
        <thead><tr><th scope="col">Plan</th><th scope="col">Price</th><th scope="col">Labels per month</th></tr></thead>
        <tbody>{plans.map(([plan, price, labels]) =>
          <tr key={plan}><td>{plan}</td><td>{price}</td><td>{labels}</td></tr>
        )}</tbody>
      </table>
    </div>
  </div>
}
