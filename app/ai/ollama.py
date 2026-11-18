import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

import httpx

from app.ai.prompts import CURRENT_PROMPT_VERSION, build_code_review_prompt
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

    def review(
        self,
        project_name: str,
        files: list[tuple[str, str]],
        prompt_version: str = CURRENT_PROMPT_VERSION,
        review_instructions: str | None = None,
    ) -> ReviewResult:
        prompt = build_code_review_prompt(project_name, files, prompt_version, review_instructions)
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "format": "json",
                    "stream": False,
                },
                timeout=settings.ollama_timeout_seconds,
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

    def stream_review(
        self,
        project_name: str,
        files: list[tuple[str, str]],
        prompt_version: str = CURRENT_PROMPT_VERSION,
        review_instructions: str | None = None,
    ) -> Iterator[str]:
        """Yield model content fragments while Ollama generates a review."""
        prompt = build_code_review_prompt(project_name, files, prompt_version, review_instructions)
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
                timeout=settings.ollama_timeout_seconds,
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
    def _parse_result(content: str) -> ReviewResult:
        data = json.loads(content)
        summary = data.get("summary")
        findings = data.get("findings")
        if not isinstance(summary, str) or len(summary) > 50_000 or not isinstance(findings, list):
            raise AIReviewError("Review JSON must contain summary and findings")
        if len(findings) > 100:
            raise AIReviewError("Review JSON contains too many findings")

        parsed_findings: list[ReviewFindingResult] = []
        for finding in findings:
            if not isinstance(finding, dict):
                raise AIReviewError("Each review finding must be an object")
            severity = str(finding.get("severity", "medium")).lower()
            if severity not in {"critical", "high", "medium", "low"}:
                raise AIReviewError("Review finding has an invalid severity")
            file_path = str(finding.get("file_path", "unknown"))
            path = PurePosixPath(file_path)
            if path.is_absolute() or ".." in path.parts:
                raise AIReviewError("Review finding has an unsafe file path")
            line_number = finding.get("line_number")
            if line_number is not None and (not isinstance(line_number, int) or line_number < 1):
                raise AIReviewError("Review finding has an invalid line number")
            parsed_findings.append(
                ReviewFindingResult(
                    severity=severity,
                    file_path=file_path,
                    line_number=line_number,
                    title=str(finding.get("title", "Unspecified finding")),
                    explanation=str(finding.get("explanation", "")),
                    recommendation=str(finding.get("recommendation", "")),
                )
            )
        return ReviewResult(summary=summary, findings=parsed_findings)
