from __future__ import annotations

from repo_review_automation import __version__


def test_package_version_matches_release_bump() -> None:
    assert __version__ == "1.0.2"
