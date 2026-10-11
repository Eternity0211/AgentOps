"use client";

export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="error-state">
      <p className="eyebrow">CONSOLE ERROR</p>
      <h1>The console could not load</h1>
      <p>No backend action was attempted. Retry when you are ready.</p>
      <button type="button" onClick={reset}>
        Retry
      </button>
    </main>
  );
}
