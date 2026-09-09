import { Component, type ReactNode } from 'react';
import { Link } from 'react-router';

/** A failed route chunk or renderer still leaves an accessible recovery path. */
export class RouteErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return (
      <main className="route-message">
        <h1>Preview could not open</h1>
        <p role="alert">Please reload to try again.</p>
        <button onClick={() => window.location.reload()}>Reload preview</button>{' '}
        <Link to="/">FurnitureOS home</Link>
      </main>
    );
    return this.props.children;
  }
}
