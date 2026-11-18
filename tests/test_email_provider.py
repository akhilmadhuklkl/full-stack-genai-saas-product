from types import SimpleNamespace

import httpx
import pytest

from app import email


def test_resend_provider_sends_expected_payload(monkeypatch) -> None:
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"id": "email_test_123"}, request=request)

    monkeypatch.setattr(email, "settings", SimpleNamespace(
        email_provider="resend",
        resend_api_key="re_test_key",
        email_from="noreply@example.com",
    ))
    monkeypatch.setattr(email.httpx, "post", fake_post)

    email.send_email("akhilm939@gmail.com", "Verify", "Please verify your email.")

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"] == {"Authorization": "Bearer re_test_key"}
    assert captured["json"] == {
        "from": "noreply@example.com",
        "to": ["akhilm939@gmail.com"],
        "subject": "Verify",
        "text": "Please verify your email.",
    }
    assert captured["timeout"] == 10.0


def test_resend_provider_wraps_http_errors(monkeypatch) -> None:
    def failing_post(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(email, "settings", SimpleNamespace(
        email_provider="resend",
        resend_api_key="re_test_key",
        email_from="noreply@example.com",
    ))
    monkeypatch.setattr(email.httpx, "post", failing_post)

    with pytest.raises(email.EmailDeliveryError, match="delivery failed"):
        email.send_email("akhilm939@gmail.com", "Verify", "Please verify your email.")
