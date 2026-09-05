"""
Tests for agent/tools/listing_pipeline.py (analyze_listing).

The pipeline's whole reason to exist is the dependency shape: the market
valuation needs the item's *name*, so it waits for `identify`; the description
needs only the photos, so it must NOT wait for the valuation. These tests pin
that down with an event handshake rather than timing -- if the two stages were
run one after the other, the gated stage would block until its timeout instead
of completing.

Both collaborators are module-level singletons (`image_analyzer`,
`market_service`) imported by name into listing_pipeline, so we monkeypatch the
names *on the pipeline module* rather than on the singletons themselves.
"""

import asyncio
import json

import pytest

import agent.tools.listing_pipeline as pipeline_module
from agent.tools.listing_pipeline import analyze_listing

SAMPLE_IMAGES = [{"base64_image": "aGVsbG8=", "mime_type": "image/png"}]

IDENTIFIED = {
    "name": "Vintage Brass Lamp",
    "condition": "Like New",
    "category": "Home",
    "suggested_keywords": ["lamp", "brass"],
}

VALUATION = {"suggested_listing": 120.0, "market_average": 140.0, "currency": "MYR"}


class _FakeAnalyzer:
    def __init__(self, identified=None, description="A warm brass lamp."):
        self.identified = identified if identified is not None else dict(IDENTIFIED)
        self.description = description
        self.identify_calls = []
        self.describe_calls = []

    async def identify(self, images_data):
        self.identify_calls.append(images_data)
        return dict(self.identified)

    async def describe(self, images_data):
        self.describe_calls.append(images_data)
        return self.description


class _FakeMarket:
    def __init__(self, valuation=None):
        self.valuation = valuation if valuation is not None else dict(VALUATION)
        self.calls = []

    async def aget_market_valuation(self, query, condition="good", category=None):
        self.calls.append({"query": query, "condition": condition, "category": category})
        return dict(self.valuation)


@pytest.fixture
def fakes(monkeypatch):
    analyzer, market = _FakeAnalyzer(), _FakeMarket()
    monkeypatch.setattr(pipeline_module, "image_analyzer", analyzer)
    monkeypatch.setattr(pipeline_module, "market_service", market)
    return analyzer, market


async def collect(images=SAMPLE_IMAGES):
    """Run the pipeline, returning (result, events)."""
    events = []

    async def on_progress(event):
        events.append(event)

    result = await analyze_listing(images, on_progress)
    return result, events


# ---------------------------------------------------------------------------
# Merged result
# ---------------------------------------------------------------------------


async def test_merges_identify_description_and_market_data(fakes):
    result, _ = await collect()

    assert result["name"] == "Vintage Brass Lamp"
    assert result["condition"] == "Like New"
    assert result["category"] == "Home"
    assert result["suggested_keywords"] == ["lamp", "brass"]
    assert result["description"] == "A warm brass lamp."
    assert result["market_data"] == VALUATION


async def test_passes_the_same_images_to_both_vision_stages(fakes):
    analyzer, _ = fakes
    await collect()

    assert analyzer.identify_calls == [SAMPLE_IMAGES]
    assert analyzer.describe_calls == [SAMPLE_IMAGES]


async def test_prices_against_the_identified_name_condition_and_category(fakes):
    _, market = fakes
    await collect()

    assert market.calls == [{
        "query": "Vintage Brass Lamp",
        "condition": "Like New",
        "category": "Home",
    }]


async def test_missing_identify_fields_fall_back_to_safe_defaults(monkeypatch):
    analyzer = _FakeAnalyzer(identified={})
    market = _FakeMarket()
    monkeypatch.setattr(pipeline_module, "image_analyzer", analyzer)
    monkeypatch.setattr(pipeline_module, "market_service", market)

    result, events = await collect()

    assert market.calls[0]["query"] == ""
    assert market.calls[0]["condition"] == "Good"
    assert market.calls[0]["category"] is None
    # With no name to report, the identified event still says something useful.
    assert any(e["message"] == "Identified the item" for e in events)
    assert result["description"] == "A warm brass lamp."


# ---------------------------------------------------------------------------
# Concurrency: description and valuation must overlap
# ---------------------------------------------------------------------------


async def test_description_and_valuation_run_concurrently(monkeypatch):
    """The description waits on a gate only the valuation can open.

    Run sequentially, `describe` would time out waiting for a valuation that
    hasn't started; the pipeline only passes if both are in flight at once.
    """
    gate = asyncio.Event()

    class _GatedAnalyzer(_FakeAnalyzer):
        async def describe(self, images_data):
            await asyncio.wait_for(gate.wait(), timeout=2)
            return "described after the valuation started"

    class _GatingMarket(_FakeMarket):
        async def aget_market_valuation(self, query, condition="good", category=None):
            gate.set()
            return dict(VALUATION)

    monkeypatch.setattr(pipeline_module, "image_analyzer", _GatedAnalyzer())
    monkeypatch.setattr(pipeline_module, "market_service", _GatingMarket())

    result, _ = await collect()

    assert result["description"] == "described after the valuation started"
    assert result["market_data"] == VALUATION


async def test_valuation_waits_for_identify(monkeypatch):
    """The valuation can't start before identify finishes -- it needs the name."""
    order = []

    class _OrderedAnalyzer(_FakeAnalyzer):
        async def identify(self, images_data):
            await asyncio.sleep(0)
            order.append("identify")
            return dict(IDENTIFIED)

    class _OrderedMarket(_FakeMarket):
        async def aget_market_valuation(self, query, condition="good", category=None):
            order.append("market")
            return dict(VALUATION)

    monkeypatch.setattr(pipeline_module, "image_analyzer", _OrderedAnalyzer())
    monkeypatch.setattr(pipeline_module, "market_service", _OrderedMarket())

    await collect()

    assert order == ["identify", "market"]


# ---------------------------------------------------------------------------
# Progress events
# ---------------------------------------------------------------------------


async def test_emits_monotonically_increasing_progress(fakes):
    _, events = await collect()

    stages = [e["stage"] for e in events]
    assert stages[:2] == ["identifying", "identified"]
    assert set(stages[2:]) == {"described", "priced"}

    values = [e["progress"] for e in events]
    assert values == sorted(values)
    assert values[0] == 20
    assert values[1] == 50
    # The two concurrent stages each claim a slice, whichever lands first.
    assert values[2:] == [72, 94]


async def test_identified_event_patches_the_name_and_condition(fakes):
    _, events = await collect()

    identified = next(e for e in events if e["stage"] == "identified")
    assert identified["patch"] == {"name": "Vintage Brass Lamp", "condition": "Like New"}
    assert identified["message"] == "Identified: Vintage Brass Lamp"


async def test_parallel_stages_patch_the_description_and_price(fakes):
    _, events = await collect()

    described = next(e for e in events if e["stage"] == "described")
    priced = next(e for e in events if e["stage"] == "priced")
    assert described["patch"] == {"description": "A warm brass lamp."}
    assert priced["patch"] == {"price": 120.0}


async def test_first_event_carries_no_patch(fakes):
    _, events = await collect()

    assert "patch" not in events[0]


async def test_runs_without_a_progress_callback(fakes):
    result = await analyze_listing(SAMPLE_IMAGES)

    assert result["name"] == "Vintage Brass Lamp"
    assert result["market_data"] == VALUATION


# ---------------------------------------------------------------------------
# Degraded paths -- one slow stage failing must not sink the whole listing
# ---------------------------------------------------------------------------


async def test_description_failure_leaves_an_empty_description_but_keeps_the_price(monkeypatch):
    class _BrokenDescribe(_FakeAnalyzer):
        async def describe(self, images_data):
            raise RuntimeError("gemini exploded")

    monkeypatch.setattr(pipeline_module, "image_analyzer", _BrokenDescribe())
    monkeypatch.setattr(pipeline_module, "market_service", _FakeMarket())

    result, events = await collect()

    assert result["description"] == ""
    assert result["market_data"] == VALUATION
    described = next(e for e in events if e["stage"] == "described")
    assert "patch" not in described


async def test_valuation_failure_leaves_market_data_none_but_keeps_the_description(monkeypatch):
    class _BrokenMarket(_FakeMarket):
        async def aget_market_valuation(self, query, condition="good", category=None):
            raise RuntimeError("search unavailable")

    monkeypatch.setattr(pipeline_module, "image_analyzer", _FakeAnalyzer())
    monkeypatch.setattr(pipeline_module, "market_service", _BrokenMarket())

    result, events = await collect()

    assert result["market_data"] is None
    assert result["description"] == "A warm brass lamp."
    priced = next(e for e in events if e["stage"] == "priced")
    assert "patch" not in priced


async def test_both_parallel_stages_failing_still_returns_the_identified_item(monkeypatch):
    class _BrokenDescribe(_FakeAnalyzer):
        async def describe(self, images_data):
            raise RuntimeError("nope")

    class _BrokenMarket(_FakeMarket):
        async def aget_market_valuation(self, query, condition="good", category=None):
            raise RuntimeError("nope")

    monkeypatch.setattr(pipeline_module, "image_analyzer", _BrokenDescribe())
    monkeypatch.setattr(pipeline_module, "market_service", _BrokenMarket())

    result, _ = await collect()

    assert result["name"] == "Vintage Brass Lamp"
    assert result["description"] == ""
    assert result["market_data"] is None


async def test_a_none_description_is_normalized_to_an_empty_string(monkeypatch):
    monkeypatch.setattr(pipeline_module, "image_analyzer", _FakeAnalyzer(description=None))
    monkeypatch.setattr(pipeline_module, "market_service", _FakeMarket())

    result, events = await collect()

    assert result["description"] == ""
    described = next(e for e in events if e["stage"] == "described")
    assert "patch" not in described


async def test_pipeline_parses_trilingual_translations_when_json(monkeypatch):
    trilingual_json = json.dumps({
        "en": {"name": "Lamp", "description": "English desc", "condition": "Good"},
        "ms": {"name": "Lampu", "description": "Penerangan BM", "condition": "Elok"},
        "zh": {"name": "台灯", "description": "中文描述", "condition": "良好"},
    })
    monkeypatch.setattr(pipeline_module, "image_analyzer", _FakeAnalyzer(description=trilingual_json))
    monkeypatch.setattr(pipeline_module, "market_service", _FakeMarket())

    result, events = await collect()

    assert result["description"] == "English desc"
    assert result["translations"]["ms"]["name"] == "Lampu"
    assert result["translations"]["zh"]["description"] == "中文描述"

    described = next(e for e in events if e["stage"] == "described")
    assert described["patch"]["translations"]["zh"]["name"] == "台灯"


async def test_pipeline_parses_trilingual_translations_with_raw_newlines_and_commentary(monkeypatch):
    raw_llm_response = """Here is the listing:
```json
{
  "en": {
    "name": "Apple AirPods Max",
    "description": "Line 1 of English description.\nLine 2.\n- Feature 1\n- Feature 2",
    "condition": "Like New"
  },
  "ms": {
    "name": "Apple AirPods Max BM",
    "description": "Penerangan dalam Bahasa Melayu.
Baris kedua dengan newline sebenar.
- Ciri 1
- Ciri 2",
    "condition": "Seperti Baru"
  },
  "zh": {
    "name": "Apple AirPods Max 中文",
    "description": "中文描述。\n第二行。\n- 特点 1",
    "condition": "良好"
  }
}
```
Hope this is helpful!"""
    monkeypatch.setattr(pipeline_module, "image_analyzer", _FakeAnalyzer(description=raw_llm_response))
    monkeypatch.setattr(pipeline_module, "market_service", _FakeMarket())

    result, events = await collect()

    assert "Line 1 of English description" in result["description"]
    assert "Line 2" in result["description"]
    assert result["translations"]["ms"]["name"] == "Apple AirPods Max BM"
    assert "Baris kedua dengan newline sebenar" in result["translations"]["ms"]["description"]
    assert result["translations"]["zh"]["name"] == "Apple AirPods Max 中文"
