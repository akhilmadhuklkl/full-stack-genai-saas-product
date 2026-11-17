import json

import httpx

from app.ai.ollama import OllamaReviewService


def test_ollama_result_parser() -> None:
    result = OllamaReviewService._parse_result(
        json.dumps(
            {
                "summary": "One issue found.",
                "findings": [
                    {
                        "severity": "HIGH",
                        "file_path": "app.py",
                        "line_number": 3,
                        "title": "Unsafe operation",
                        "explanation": "The operation is risky.",
                        "recommendation": "Validate the input.",
                    }
                ],
            }
        )
    )

    assert result.summary == "One issue found."
    assert result.findings[0].severity == "high"
    assert result.findings[0].file_path == "app.py"


def test_ollama_service_builds_code_review_request(monkeypatch) -> None:
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["payload"] = kwargs["json"]
        return httpx.Response(
            200,
            json={"message": {"content": '{"summary":"Clean","findings":[]}'}},
        )

    monkeypatch.setattr("app.ai.ollama.httpx.post", fake_post)
    result = OllamaReviewService(base_url="http://ollama", model="test-model").review(
        "demo", [("app.py", "print('hello')")]
    )

    assert result.summary == "Clean"
    assert captured["url"] == "http://ollama/api/chat"
    assert captured["payload"]["model"] == "test-model"
    assert "print('hello')" in captured["payload"]["messages"][0]["content"]


def test_ollama_result_parser_is_exposed_for_streaming() -> None:
    service = OllamaReviewService()

    result = service.parse_result('{"summary":"Clean","findings":[]}')

    assert result.summary == "Clean"
    assert result.findings == []
