export function ErrorState({ message }: { message: string }) {
  return <div className="state-box error">{message}</div>
}
