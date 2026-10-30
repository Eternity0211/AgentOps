"""Repository-local entry point for read-only runtime prerequisite checks."""

from agentops_incident_commander.runtime_prerequisites import main

if __name__ == "__main__":
    raise SystemExit(main())
