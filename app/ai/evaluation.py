from dataclasses import dataclass

from app.ai.ollama import ReviewResult


@dataclass(frozen=True)
class ExpectedFinding:
    file_path: str
    severity: str
    title_contains: str


@dataclass(frozen=True)
class EvaluationResult:
    matched: int
    expected: int
    score: float


def evaluate_review(
    result: ReviewResult, expected_findings: list[ExpectedFinding]
) -> EvaluationResult:
    """Score expected findings using conservative file/severity/title matching."""
    matched = 0
    for expected in expected_findings:
        if any(
            finding.file_path == expected.file_path
            and finding.severity == expected.severity
            and expected.title_contains.lower() in finding.title.lower()
            for finding in result.findings
        ):
            matched += 1
    expected_count = len(expected_findings)
    return EvaluationResult(
        matched=matched,
        expected=expected_count,
        score=matched / expected_count if expected_count else 1.0,
    )
