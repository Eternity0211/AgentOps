export default function Loading() {
  return (
    <main aria-busy="true" className="centered-state">
      <p className="eyebrow">LOADING VIEW</p>
      <h1>Loading incident data</h1>
      <p role="status">Waiting for an authorized backend response…</p>
    </main>
  );
}
