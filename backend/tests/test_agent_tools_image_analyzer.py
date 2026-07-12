"""
Tests for agent/tools/image_analyzer.py (ImageAnalyzerService).

The module-level `image_analyzer` singleton constructs a real (but never
network-called) ChatGoogleGenerativeAI because conftest.py sets a
dummy-but-truthy GEMINI_API_KEY. We never let it actually run -- every test
that needs a "response" swaps the whole `.model` attribute for a tiny fake
object exposing an `.invoke` MagicMock, so no network call is ever made.

Note: ChatGoogleGenerativeAI is a pydantic model, so you cannot
`monkeypatch.setattr(image_analyzer.model, "invoke", ...)` directly --
pydantic rejects setting an attribute that isn't a declared field
("... object has no field \"invoke\""). Swapping the entire `.model`
attribute (a plain attribute on the non-pydantic ImageAnalyzerService) sidesteps
that restriction while still exercising the exact same `self.model.invoke(...)`
call site in `analyze()`.
"""

import json
from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage

from agent.tools.image_analyzer import ImageAnalyzerService, image_analyzer

SAMPLE_IMAGES = [
    {"base64_image": "aGVsbG8=", "mime_type": "image/png"},
    {"base64_image": "d29ybGQ=", "mime_type": "image/jpeg"},
]


class _FakeModel:
    """Stand-in for ChatGoogleGenerativeAI exposing only what analyze() uses."""

    def __init__(self, invoke_mock):
        self.invoke = invoke_mock


def _fake_response(content):
    """Build a lightweight stand-in for the LangChain AIMessage response."""

    class _FakeResponse:
        pass

    resp = _FakeResponse()
    resp.content = content
    return resp


def _patch_invoke(monkeypatch, target=image_analyzer, **mock_kwargs):
    """Replace target.model with a fake exposing a MagicMock .invoke, return that mock."""
    mock_invoke = MagicMock(**mock_kwargs)
    monkeypatch.setattr(target, "model", _FakeModel(mock_invoke))
    return mock_invoke


# ---------------------------------------------------------------------------
# __init__ behavior
# ---------------------------------------------------------------------------


def test_singleton_has_real_model_since_gemini_key_set():
    # conftest sets GEMINI_API_KEY to a truthy dummy value, so the singleton
    # (constructed at import time) should have a real model instance.
    assert image_analyzer.model is not None


def test_init_without_gemini_key_leaves_model_none(monkeypatch):
    # GEMINI_API_KEY was imported by name into this module at import time
    # (`from env import GEMINI_API_KEY`), so patch it on the *consuming*
    # module directly rather than via os.environ (which would have no
    # effect on the already-bound name).
    monkeypatch.setattr("agent.tools.image_analyzer.GEMINI_API_KEY", "", raising=False)
    service = ImageAnalyzerService()
    assert service.model is None


def test_init_with_none_gemini_key_leaves_model_none(monkeypatch):
    monkeypatch.setattr("agent.tools.image_analyzer.GEMINI_API_KEY", None, raising=False)
    service = ImageAnalyzerService()
    assert service.model is None


# ---------------------------------------------------------------------------
# analyze() -- no-model fallback path
# ---------------------------------------------------------------------------


async def test_analyze_returns_fallback_immediately_when_model_is_none(monkeypatch):
    monkeypatch.setattr("agent.tools.image_analyzer.GEMINI_API_KEY", "", raising=False)
    service = ImageAnalyzerService()
    assert service.model is None

    result = await service.analyze(SAMPLE_IMAGES)

    assert result == service._get_fallback_response()
    assert result["error"] == "Image analysis unavailable. Please set GEMINI_API_KEY."
    assert result["name"] == "Item"
    assert result["condition"] == "Good"
    assert result["category"] == "Other"
    assert result["suggested_keywords"] == []


async def test_analyze_with_model_none_never_calls_invoke():
    # Directly forcing .model = None on a fresh instance (per the assignment
    # notes) should also short-circuit before any invoke() call is made.
    service = ImageAnalyzerService()
    service.model = None
    result = await service.analyze(SAMPLE_IMAGES)
    assert result["error"] == "Image analysis unavailable. Please set GEMINI_API_KEY."


def test_get_fallback_response_shape():
    service = ImageAnalyzerService()
    fallback = service._get_fallback_response()
    assert fallback == {
        "name": "Item",
        "description": "Please add a description for this item.",
        "condition": "Good",
        "category": "Other",
        "suggested_keywords": [],
        "error": "Image analysis unavailable. Please set GEMINI_API_KEY.",
    }


# ---------------------------------------------------------------------------
# analyze() -- success path (valid JSON in ```json fenced response)
# ---------------------------------------------------------------------------


async def test_analyze_success_parses_fenced_json(monkeypatch):
    payload = {
        "name": "Vintage Leather Jacket",
        "description": "A **great** jacket.\n- warm\n- stylish",
        "condition": "Like New",
        "category": "Fashion",
        "suggested_keywords": ["jacket", "leather", "vintage"],
    }
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    mock_invoke = _patch_invoke(monkeypatch, return_value=_fake_response(fenced))

    result = await image_analyzer.analyze(SAMPLE_IMAGES)

    assert result == payload
    mock_invoke.assert_called_once()
    # Verify the single HumanMessage passed contains the text prompt plus
    # one image_url block per input image.
    (call_args,), _ = mock_invoke.call_args
    assert len(call_args) == 1
    msg = call_args[0]
    assert isinstance(msg, HumanMessage)
    assert msg.content[0]["type"] == "text"
    image_blocks = [c for c in msg.content if c["type"] == "image_url"]
    assert len(image_blocks) == len(SAMPLE_IMAGES)
    assert image_blocks[0]["image_url"]["url"] == "data:image/png;base64,aGVsbG8="
    assert image_blocks[1]["image_url"]["url"] == "data:image/jpeg;base64,d29ybGQ="


async def test_analyze_success_unfenced_json(monkeypatch):
    # Plain JSON with no ```json fence should also parse fine (strip() +
    # a no-op replace of the (absent) fence markers).
    payload = {
        "name": "Bluetooth Speaker",
        "description": "Compact speaker.",
        "condition": "Good",
        "category": "Electronics",
        "suggested_keywords": ["speaker", "bluetooth"],
    }
    _patch_invoke(monkeypatch, return_value=_fake_response(json.dumps(payload)))

    result = await image_analyzer.analyze(SAMPLE_IMAGES)
    assert result == payload


async def test_analyze_success_fills_defaults_for_missing_fields(monkeypatch):
    # Response JSON that omits every optional field entirely -- setdefault()
    # should backfill each one.
    _patch_invoke(monkeypatch, return_value=_fake_response("{}"))

    result = await image_analyzer.analyze(SAMPLE_IMAGES)

    assert result == {
        "name": "Unknown Item",
        "description": "No description available.",
        "condition": "Good",
        "category": "Other",
        "suggested_keywords": [],
    }


async def test_analyze_success_with_partial_fields(monkeypatch):
    partial = {"name": "Custom Name"}
    _patch_invoke(monkeypatch, return_value=_fake_response(json.dumps(partial)))

    result = await image_analyzer.analyze(SAMPLE_IMAGES)

    assert result["name"] == "Custom Name"
    assert result["description"] == "No description available."
    assert result["condition"] == "Good"
    assert result["category"] == "Other"
    assert result["suggested_keywords"] == []


async def test_analyze_success_content_as_list_of_dicts(monkeypatch):
    # LangChain multimodal responses can return `.content` as a list of
    # dict "parts" with a 'text' key instead of a plain string.
    payload = {"name": "Multi-part response", "description": "d", "condition": "Fair"}
    parts = [{"type": "text", "text": json.dumps(payload)}]
    _patch_invoke(monkeypatch, return_value=_fake_response(parts))

    result = await image_analyzer.analyze(SAMPLE_IMAGES)
    assert result["name"] == "Multi-part response"
    assert result["condition"] == "Fair"


async def test_analyze_success_content_list_skips_unrecognized_parts(monkeypatch):
    # A list item that is neither a plain string nor a dict with a 'text'
    # key (e.g. a dict without 'text', or some other type) is silently
    # skipped by the text-extraction loop rather than raising.
    payload = {"name": "Skips unknown parts"}
    parts = [
        {"type": "image_url", "image_url": {"url": "irrelevant"}},  # no 'text' key
        json.dumps(payload),
    ]
    _patch_invoke(monkeypatch, return_value=_fake_response(parts))

    result = await image_analyzer.analyze(SAMPLE_IMAGES)
    assert result["name"] == "Skips unknown parts"


async def test_analyze_success_content_as_list_of_strings(monkeypatch):
    payload = {"name": "String parts"}
    # Split the fenced JSON string across two list entries -- the code joins
    # all string parts together before attempting json.loads.
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    half = len(fenced) // 2
    parts = [fenced[:half], fenced[half:]]
    _patch_invoke(monkeypatch, return_value=_fake_response(parts))

    result = await image_analyzer.analyze(SAMPLE_IMAGES)
    assert result["name"] == "String parts"


async def test_analyze_with_empty_images_list(monkeypatch):
    # No images at all -- content list should just be the text prompt, and
    # a valid JSON response should still be parsed normally.
    payload = {"name": "No image item"}
    mock_invoke = _patch_invoke(monkeypatch, return_value=_fake_response(json.dumps(payload)))

    result = await image_analyzer.analyze([])

    assert result["name"] == "No image item"
    (call_args,), _ = mock_invoke.call_args
    msg = call_args[0]
    assert len(msg.content) == 1
    assert msg.content[0]["type"] == "text"


# ---------------------------------------------------------------------------
# analyze() -- failure paths
# ---------------------------------------------------------------------------


async def test_analyze_malformed_json_returns_fallback(monkeypatch):
    _patch_invoke(
        monkeypatch, return_value=_fake_response("```json\n{not valid json!!\n```")
    )

    result = await image_analyzer.analyze(SAMPLE_IMAGES)

    assert result == image_analyzer._get_fallback_response()


async def test_analyze_generic_exception_from_invoke_returns_fallback(monkeypatch):
    _patch_invoke(monkeypatch, side_effect=RuntimeError("boom"))

    result = await image_analyzer.analyze(SAMPLE_IMAGES)

    assert result == image_analyzer._get_fallback_response()


async def test_analyze_malformed_images_data_returns_fallback(monkeypatch):
    # A missing 'mime_type' key raises a KeyError while building the content
    # list -- this happens before model.invoke is ever called, and should
    # still be swallowed by the generic `except Exception` branch.
    mock_invoke = _patch_invoke(monkeypatch)

    bad_images = [{"base64_image": "aGVsbG8="}]  # no mime_type
    result = await image_analyzer.analyze(bad_images)

    assert result == image_analyzer._get_fallback_response()
    mock_invoke.assert_not_called()


async def test_analyze_non_dict_json_result_returns_fallback(monkeypatch):
    # If the model returns valid JSON that isn't an object (e.g. a bare
    # list), json.loads succeeds but result.setdefault(...) raises
    # AttributeError, which is caught by the generic except -> fallback.
    _patch_invoke(monkeypatch, return_value=_fake_response("[1, 2, 3]"))

    result = await image_analyzer.analyze(SAMPLE_IMAGES)

    assert result == image_analyzer._get_fallback_response()
