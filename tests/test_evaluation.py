from app.ai.evaluation import ExpectedFinding, evaluate_review
from app.ai.ollama import ReviewFindingResult, ReviewResult


def test_evaluation_matches_expected_finding() -> None:
    result = ReviewResult(
        summary="One issue",
        findings=[
            ReviewFindingResult(
                severity="high",
                file_path="users.py",
                line_number=2,
                title="SQL injection risk",
                explanation="Unsafe query construction.",
                recommendation="Use parameters.",
            )
        ],
    )

    score = evaluate_review(
        result,
        [ExpectedFinding(file_path="users.py", severity="high", title_contains="sql")],
    )

    assert score.matched == 1
    assert score.score == 1.0


def test_evaluation_scores_clean_case_as_perfect() -> None:
    score = evaluate_review(ReviewResult(summary="Clean", findings=[]), [])

    assert score.matched == 0
    assert score.expected == 0
    assert score.score == 1.0
