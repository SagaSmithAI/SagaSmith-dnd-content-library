from __future__ import annotations

import pytest

from scripts import check_catalog_freshness as freshness


@pytest.fixture(autouse=True)
def catalog_index(monkeypatch: pytest.MonkeyPatch) -> None:
    # Freshness cases must exercise dates and commits independently of future
    # catalog publications, including the equal-date/wrong-commit rejection.
    monkeypatch.setattr(
        freshness, "_read_local_index", lambda: {"generated_on": "2026-09-09"},
    )


def test_check_accepts_marker_matching_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = freshness._read_local_index()
    generated_on = str(catalog["generated_on"])
    monkeypatch.setattr(
        freshness,
        "_read_json",
        lambda url, timeout: {
            "generated_on": generated_on,
            "source_commit": "a" * 40,
        },
    )
    monkeypatch.setattr(freshness, "_latest_catalog_commit", lambda: "a" * 40)

    result = freshness.check(status_url="https://example.test/status.json", timeout=1)

    assert result["fresh"] == "true"
    assert result["generated_on"] == generated_on


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
