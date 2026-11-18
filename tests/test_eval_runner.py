from pathlib import Path

from evals.run_evals import load_cases


def test_eval_runner_respects_case_limit() -> None:
    cases = load_cases(Path("evals/cases"), selected_case=None, max_cases=1)

    assert len(cases) == 1
