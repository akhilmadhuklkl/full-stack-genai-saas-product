import argparse
import json
from pathlib import Path


def compare_reports(baseline_path: Path, candidate_path: Path) -> dict:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    baseline_cases = {result["name"]: result for result in baseline["results"]}
    comparisons = []
    for result in candidate["results"]:
        previous = baseline_cases.get(result["name"])
        comparisons.append(
            {
                "name": result["name"],
                "baseline_score": previous.get("score") if previous else None,
                "candidate_score": result.get("score"),
                "delta": (
                    result.get("score", 0.0) - previous.get("score", 0.0)
                    if previous
                    else None
                ),
            }
        )
    return {
        "baseline": {
            "model": baseline.get("model"),
            "prompt_version": baseline.get("prompt_version"),
            "aggregate_score": baseline.get("aggregate_score", 0.0),
        },
        "candidate": {
            "model": candidate.get("model"),
            "prompt_version": candidate.get("prompt_version"),
            "aggregate_score": candidate.get("aggregate_score", 0.0),
        },
        "aggregate_delta": candidate.get("aggregate_score", 0.0)
        - baseline.get("aggregate_score", 0.0),
        "cases": comparisons,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two evaluation reports.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, default=Path("evals/results/comparison.json"))
    args = parser.parse_args()
    report = compare_reports(args.baseline, args.candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
