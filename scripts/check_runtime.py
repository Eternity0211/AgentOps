"""Repository-local entry point for bounded local runtime health checks."""

from agentops_incident_commander.runtime_health import main

if __name__ == "__main__":
    raise SystemExit(main())
