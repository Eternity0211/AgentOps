import { consoleConfig } from "@/lib/config";

const foundations = [
  ["Evidence first", "Every diagnosis remains linked to resolvable evidence."],
  ["Human authority", "Approvals stay proposal-bound and time-limited."],
  [
    "Observed recovery",
    "Only deterministic verification can close an incident.",
  ],
] as const;

export default function Home() {
  return (
    <main>
      <header className="hero">
        <p className="eyebrow">CONTROL PLANE / ADMINISTRATION</p>
        <div className="hero-row">
          <div>
            <h1>AgentOps Incident Commander</h1>
            <p className="lede">
              Evidence-driven diagnosis and controlled recovery, with every
              decision auditable.
            </p>
          </div>
          <span className="status" role="status">
            Console foundation ready
          </span>
        </div>
      </header>

      <section aria-labelledby="foundation-heading" className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">SAFETY MODEL</p>
            <h2 id="foundation-heading">Authority stays deterministic</h2>
          </div>
          <code>{consoleConfig.apiBaseUrl}</code>
        </div>
        <ul className="foundation-grid">
          {foundations.map(([title, description], index) => (
            <li key={title}>
              <span className="index">0{index + 1}</span>
              <h3>{title}</h3>
              <p>{description}</p>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
