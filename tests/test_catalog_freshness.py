from __future__ import annotations

import pytest

from scripts import check_catalog_freshness as freshness


def test_check_accepts_marker_matching_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        freshness,
        "_read_json",
        lambda url, timeout: {
            "generated_on": "2026-09-09",
            "source_commit": "a" * 40,
        },
    )
    monkeypatch.setattr(freshness, "_latest_catalog_commit", lambda: "a" * 40)

    result = freshness.check(status_url="https://example.test/status.json", timeout=1)

    assert result["fresh"] == "true"
    assert result["generated_on"] == "2026-09-09"


@pytest.mark.parametrize(
    "status",
    [
        {"generated_on": "2026-09-08", "source_commit": "a" * 40},
        {"generated_on": "2026-09-09", "source_commit": "b" * 40},
        {"generated_on": "2026-09-09"},
    ],
)
def test_check_rejects_stale_or_incomplete_marker(
    monkeypatch: pytest.MonkeyPatch,
    status: dict[str, str],
) -> None:
    monkeypatch.setattr(freshness, "_read_json", lambda url, timeout: status)
    monkeypatch.setattr(freshness, "_latest_catalog_commit", lambda: "a" * 40)

    with pytest.raises(ValueError, match="published catalog"):
        freshness.check(status_url="https://example.test/status.json", timeout=1)
