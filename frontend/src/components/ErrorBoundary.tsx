import { Component, type ReactNode } from "react";

/** Never show a blank screen on stage: catch render errors and offer a one-tap recovery. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error) {
    console.error("[SV] render error", error);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="mx-auto mt-10 flex max-w-xl flex-col gap-4 rounded-4xl border border-line bg-surface p-8 text-center shadow-card">
        <p className="text-3xl font-bold">Something went wrong on this screen.</p>
        <p className="text-lg text-muted">{this.state.error.message}</p>
        <button type="button" onClick={() => this.setState({ error: null })}
          className="min-h-16 rounded-2xl bg-ink px-6 text-xl font-bold text-white">Try again</button>
      </div>
    );
  }
}
