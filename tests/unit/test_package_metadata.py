"""Package-level contract tests."""

from agentops_incident_commander import __version__


def test_distribution_version_matches_project_version() -> None:
    """The installed distribution exposes the version declared by the project."""
    assert __version__ == "0.1.0"
