import json
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

from app.config import settings


class AIReviewError(RuntimeError):
    """Raised when the local model cannot produce a valid review."""


@dataclass(frozen=True)
class ReviewFindingResult:
    severity: str
    file_path: str
    line_number: int | None
    title: str
    explanation: str
    recommendation: str


@dataclass(frozen=True)
class ReviewResult:
    summary: str
    findings: list[ReviewFindingResult]


class OllamaReviewService:
    """Run code reviews against a locally hosted Ollama model."""

    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model

    def review(self, project_name: str, files: list[tuple[str, str]]) -> ReviewResult:
        prompt = self._build_prompt(project_name, files)
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "format": "json",
                    "stream": False,
                },
                timeout=120.0,
            )
            response.raise_for_status()
            payload = response.json()
            content = payload.get("message", {}).get("content")
            if not isinstance(content, str):
                raise AIReviewError("Ollama returned no message content")
            return self._parse_result(content)
        except httpx.HTTPError as error:
            raise AIReviewError(f"Ollama request failed: {error}") from error
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise AIReviewError("Ollama returned invalid review JSON") from error

    def stream_review(self, project_name: str, files: list[tuple[str, str]]) -> Iterator[str]:
        """Yield model content fragments while Ollama generates a review."""
        prompt = self._build_prompt(project_name, files)
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "format": "json",
                    "stream": True,
                },
                timeout=120.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    payload = json.loads(line)
                    content = payload.get("message", {}).get("content", "")
                    if content:
                        yield content
        except httpx.HTTPError as error:
            raise AIReviewError(f"Ollama streaming request failed: {error}") from error
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise AIReviewError("Ollama returned invalid streaming JSON") from error

    def parse_result(self, content: str) -> ReviewResult:
        """Validate accumulated streamed model content."""
        return self._parse_result(content)

    @staticmethod
    def _build_prompt(project_name: str, files: list[tuple[str, str]]) -> str:
        file_blocks = "\n\n".join(
            f"FILE: {path}\n```\n{content}\n```" for path, content in files
        )
        return f"""You are a careful code reviewer. Review project '{project_name}'.

Analyze the supplied source files for concrete bugs, security issues, performance problems,
and maintainability concerns. Do not invent issues. Return JSON only in this exact shape:
{{
  "summary": "short overall summary",
  "findings": [
    {{
      "severity": "low|medium|high|critical",
      "file_path": "relative/path.py",
      "line_number": 1,
      "title": "short title",
      "explanation": "why this is a problem",
      "recommendation": "how to improve it"
    }}
  ]
}}

If there are no findings, return an empty findings array.

{file_blocks}"""

    @staticmethod
    def _parse_result(content: str) -> ReviewResult:
        data = json.loads(content)
        summary = data.get("summary")
        findings = data.get("findings")
        if not isinstance(summary, str) or not isinstance(findings, list):
            raise AIReviewError("Review JSON must contain summary and findings")

        parsed_findings: list[ReviewFindingResult] = []
        for finding in findings:
            if not isinstance(finding, dict):
                raise AIReviewError("Each review finding must be an object")
            parsed_findings.append(
                ReviewFindingResult(
                    severity=str(finding.get("severity", "medium")).lower(),
                    file_path=str(finding.get("file_path", "unknown")),
                    line_number=finding.get("line_number"),
                    title=str(finding.get("title", "Unspecified finding")),
                    explanation=str(finding.get("explanation", "")),
                    recommendation=str(finding.get("recommendation", "")),
                )
            )
        return ReviewResult(summary=summary, findings=parsed_findings)
