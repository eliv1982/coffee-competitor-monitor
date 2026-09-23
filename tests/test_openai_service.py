"""Tests for backend.services.openai_service — the structured-output OpenAI adapter.

Every OpenAI call is mocked (client.beta.chat.completions.parse). No live API calls.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    OpenAI,
)
from pydantic import ValidationError

from backend.errors import InvalidInputError, ServiceUnavailableError, UpstreamError, UpstreamTimeoutError
from backend.models.schemas import CompetitorAnalysis
from backend.services import openai_service


def _fake_request():
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _client_returning(completion) -> OpenAI:
    client = MagicMock()
    client.beta.chat.completions.parse = MagicMock(return_value=completion)
    return client


def _client_raising(exc: Exception) -> OpenAI:
    client = MagicMock()
    client.beta.chat.completions.parse = MagicMock(side_effect=exc)
    return client


def _completion_with(*, refusal=None, parsed=None, finish_reason="stop"):
    message = SimpleNamespace(refusal=refusal, parsed=parsed)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def test_offline_client_construction_does_not_call_network():
    """Constructing an OpenAI client must not perform any network I/O by itself."""
    client = OpenAI(api_key="sk-test-does-not-matter", timeout=1.0)
    assert client.api_key == "sk-test-does-not-matter"


def test_analyze_text_valid_structured_output():
    expected = CompetitorAnalysis(summary="Хорошая кофейня", strengths=["Уютно"], content_quality=8)
    client = _client_returning(_completion_with(parsed=expected))
    result = openai_service.analyze_text(client, "gpt-4o-mini", "Some competitor text " * 3)
    assert result == expected
    assert result.content_quality == 8


def test_refusal_raises_upstream_error():
    client = _client_returning(_completion_with(refusal="I can't help with that."))
    with pytest.raises(UpstreamError):
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")


def test_missing_parsed_result_raises_upstream_error():
    """SDK returned a completion but no parsed object and no refusal -> malformed structured result."""
    client = _client_returning(_completion_with(refusal=None, parsed=None, finish_reason="content_filter"))
    with pytest.raises(UpstreamError):
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")


def test_timeout_raises_upstream_timeout_error():
    client = _client_raising(APITimeoutError(request=_fake_request()))
    with pytest.raises(UpstreamTimeoutError):
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")


def test_connection_error_raises_upstream_error():
    client = _client_raising(APIConnectionError(request=_fake_request()))
    with pytest.raises(UpstreamError):
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")


def test_api_status_error_raises_upstream_error():
    resp = httpx.Response(500, request=_fake_request())
    client = _client_raising(APIStatusError("server error", response=resp, body=None))
    with pytest.raises(UpstreamError):
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")


def test_authentication_error_raises_service_unavailable():
    resp = httpx.Response(401, request=_fake_request())
    client = _client_raising(AuthenticationError("bad key", response=resp, body=None))
    with pytest.raises(ServiceUnavailableError):
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")


def test_bad_request_error_raises_invalid_input():
    resp = httpx.Response(400, request=_fake_request())
    client = _client_raising(BadRequestError("bad request", response=resp, body=None))
    with pytest.raises(InvalidInputError):
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")


def test_length_finish_reason_error_raises_upstream_error():
    fake_completion = MagicMock()
    client = _client_raising(LengthFinishReasonError(completion=fake_completion))
    with pytest.raises(UpstreamError):
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")


def test_no_result_is_never_silently_defaulted():
    """A failure must raise, never return a CompetitorAnalysis with misleading zero/default values."""
    client = _client_raising(APITimeoutError(request=_fake_request()))
    with pytest.raises(UpstreamTimeoutError):
        result = openai_service.analyze_text(client, "gpt-4o-mini", "some text")
        assert result is None  # unreachable; the call above must raise


def test_empty_choices_raises_upstream_error_not_index_error():
    """Regression (final corrective pass, item 5): a malformed/empty structured-output
    completion (choices=[]) previously reached `completion.choices[0]` directly and raised an
    unhandled IndexError -> 500. Must be treated as a malformed upstream response -> 502."""
    empty_completion = SimpleNamespace(choices=[])
    client = _client_returning(empty_completion)
    with pytest.raises(UpstreamError):
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")


def test_content_filter_finish_reason_raises_upstream_error():
    """Raised by the SDK's own .parse() when finish_reason=="content_filter" — distinct from
    (and previously uncaught alongside) choice.message.refusal; used to fall through to the
    generic 500 handler instead of a proper upstream classification."""
    client = _client_raising(ContentFilterFinishReasonError())
    with pytest.raises(UpstreamError):
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")


def _real_pydantic_validation_error() -> ValidationError:
    try:
        CompetitorAnalysis.model_validate_json('{"content_quality": "not-a-number"}')
    except ValidationError as e:
        return e
    raise AssertionError("expected model_validate_json to raise ValidationError")


def test_structured_output_schema_mismatch_raises_upstream_error():
    """client.beta.chat.completions.parse() validates the model's JSON against response_model
    internally (model_validate_json) — a mismatch raises pydantic.ValidationError directly,
    uncaught by any openai.* exception type. Must map to a clean upstream error, not a raw
    validation-error leak or an unhandled 500."""
    client = _client_raising(_real_pydantic_validation_error())
    with pytest.raises(UpstreamError):
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")


def test_validation_error_message_is_sanitized_not_raw_pydantic_detail():
    client = _client_raising(_real_pydantic_validation_error())
    try:
        openai_service.analyze_text(client, "gpt-4o-mini", "some text")
        raise AssertionError("expected UpstreamError")
    except UpstreamError as e:
        assert "content_quality" not in e.message
        assert "not-a-number" not in e.message


def test_get_openai_client_uses_official_api_only():
    """No OPENAI_BASE_URL/provider-abstraction mechanism — only the official OpenAI API is
    supported (see docs.md); the client must never point anywhere but api.openai.com."""
    settings = SimpleNamespace(openai_api_key="sk-test-000000000000000000000000000000", openai_timeout=42.0)
    client = openai_service.get_openai_client(settings)
    assert str(client.base_url).startswith("https://api.openai.com")
    assert client.timeout == 42.0


def test_get_openai_client_ignores_ambient_openai_base_url_env_var(monkeypatch):
    """Regression (final corrective pass, item 1): the OpenAI SDK itself falls back to the
    ambient OPENAI_BASE_URL environment variable whenever base_url is left as None
    (openai._client.OpenAI.__init__: `if base_url is None: base_url = os.environ.get(...)`),
    which could otherwise silently redirect every request to an arbitrary third-party host.
    get_openai_client must always pin base_url explicitly so this ambient variable is never
    consulted. No live OpenAI request is made — this only inspects client construction."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://third-party.invalid/v1/")
    settings = SimpleNamespace(openai_api_key="sk-test-000000000000000000000000000000", openai_timeout=42.0)

    client = openai_service.get_openai_client(settings)

    assert str(client.base_url).startswith("https://api.openai.com")
    assert "third-party.invalid" not in str(client.base_url)


def test_get_openai_client_raises_when_api_key_missing():
    settings = SimpleNamespace(openai_api_key="", openai_timeout=60.0)
    with pytest.raises(ServiceUnavailableError):
        openai_service.get_openai_client(settings)


def test_analyze_parsed_page_caps_input_to_configured_max_ai_text_chars():
    """title/h1/first_paragraph come straight from parsed page HTML with no a-priori size
    bound (e.g. a pathological <title> tag) — each must be capped before being sent."""
    expected = CompetitorAnalysis(summary="ok")
    captured = {}

    def fake_parse(**kwargs):
        captured.update(kwargs)
        return _completion_with(parsed=expected)

    client = MagicMock()
    client.beta.chat.completions.parse = MagicMock(side_effect=fake_parse)
    huge_title = "A" * 50_000

    openai_service.analyze_parsed_page(client, "gpt-4o-mini", huge_title, "h1", "paragraph", max_ai_text_chars=100)

    sent_text = captured["messages"][1]["content"]
    # Well below the raw 50,000-char title plus the (short, fixed) template boilerplate.
    assert len(sent_text) < 2000
    assert huge_title not in sent_text
