import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.evaluation import ExpectedFinding, evaluate_review
from app.ai.ollama import AIReviewError, OllamaReviewService
from app.config import settings


def load_cases(cases_dir: Path, selected_case: str | None, max_cases: int) -> list[dict]:
    paths = sorted(cases_dir.glob("*.json"))
    if selected_case:
        paths = [path for path in paths if path.stem == selected_case]
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths[:max_cases]]


def run_case(service: OllamaReviewService, case: dict) -> dict:
    files = [(item["path"], item["content"]) for item in case["files"]]
    expected = [ExpectedFinding(**finding) for finding in case["expected_findings"]]
    started = datetime.now(timezone.utc)
    try:
        result = service.review(case["name"], files, settings.prompt_version)
        score = evaluate_review(result, expected)
        return {
            "name": case["name"],
            "status": "completed",
            "summary": result.summary,
            "finding_count": len(result.findings),
            "matched": score.matched,
            "expected": score.expected,
            "score": score.score,
            "duration_seconds": (datetime.now(timezone.utc) - started).total_seconds(),
        }
    except AIReviewError as error:
        return {"name": case["name"], "status": "failed", "error": str(error)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bounded Ollama review evaluations.")
    parser.add_argument("--case", help="Run one case by filename stem.")
    parser.add_argument("--max-cases", type=int, default=1, help="Maximum cases to run.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/results/latest.json"),
        help="JSON report output path.",
    )
    args = parser.parse_args()
    if args.max_cases < 1:
        parser.error("--max-cases must be at least 1")

    cases = load_cases(Path("evals/cases"), args.case, args.max_cases)
    if not cases:
        parser.error("No evaluation cases matched the selection")

    service = OllamaReviewService()
    results = [run_case(service, case) for case in cases]
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": service.model,
        "prompt_version": settings.prompt_version,
        "aggregate_score": (
            sum(result.get("score", 0.0) for result in results)
            / len(results)
            if results
            else 0.0
        ),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
