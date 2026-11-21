export default function ErrorBanner({ message }: { message: string | null }) { return message ? <div className="error" role="alert">{message}</div> : null }
