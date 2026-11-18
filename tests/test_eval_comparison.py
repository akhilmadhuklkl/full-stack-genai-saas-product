import json
from pathlib import Path

from evals.compare_reports import compare_reports


def test_compare_reports_calculates_case_and_aggregate_delta(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(
        json.dumps(
            {
                "model": "old",
                "prompt_version": "v1",
                "aggregate_score": 0.5,
                "results": [{"name": "case", "score": 0.5}],
            }
        ),
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps(
            {
                "model": "new",
                "prompt_version": "v2",
                "aggregate_score": 1.0,
                "results": [{"name": "case", "score": 1.0}],
            }
        ),
        encoding="utf-8",
    )

    comparison = compare_reports(baseline, candidate)

    assert comparison["aggregate_delta"] == 0.5
    assert comparison["cases"][0]["delta"] == 0.5
