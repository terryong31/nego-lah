"""
Listing analysis pipeline.

The naive version of this is three network calls in a row: describe the photos,
then look up a market price, then hand the whole thing back. That is as slow as
the sum of its parts, and the admin stares at a bar that has no idea what it is
doing.

This module splits the work by what actually depends on what:

    identify  ──▶  market valuation ─┐
       │                             ├──▶ merged result
       └──────▶  description ────────┘

Only the valuation needs the item's *name*, so it is the only thing that has to
wait for `identify`. The description needs nothing but the photos, so it runs
alongside the valuation instead of before it. Wall-clock cost drops from
`identify + describe + market` to `identify + max(describe, market)`.

Progress is reported through an `on_progress` callback as each stage genuinely
lands, so the caller can stream real percentages rather than animating a guess.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable

try:
    import jiter
except ImportError:
    jiter = None

from agent.tools.image_analyzer import image_analyzer
from agent.tools.market_price import market_service
from logger import logger

ProgressCallback = Callable[[dict], Awaitable[None]]

# Progress budget. Encoding is charged by the caller (it owns the upload), the
# identify pass takes us to IDENTIFIED, and the two concurrent stages split the
# remainder — whichever finishes first claims the first half.
PROGRESS_IDENTIFYING = 20
PROGRESS_IDENTIFIED = 50
PROGRESS_PER_PARALLEL_STAGE = 22  # 50 -> 72 -> 94, leaving the last 6 for the caller


async def analyze_listing(
    images_data: list[dict],
    on_progress: ProgressCallback | None = None,
    language: str = "en",
) -> dict:
    """Run the full listing analysis, reporting progress as stages complete.

    Args:
        images_data: list of dicts with 'base64_image' and 'mime_type'
        on_progress: awaited with an event dict for each stage transition.
            Events carry `stage`, `progress` (0-100), `message`, and — once
            there is something worth showing — a `patch` of fields the caller
            can drop straight into the form.
        language: target language for the generated listing ('en', 'ms', 'zh')

    Returns:
        The same shape `/analyze-image` has always returned: name, description,
        condition, category, suggested_keywords, market_data.
    """
    async def emit(stage: str, progress: int, message: str, patch: dict | None = None):
        if on_progress is None:
            return
        event = {"stage": stage, "progress": progress, "message": message}
        if patch:
            event["patch"] = patch
        await on_progress(event)

    await emit("identifying", PROGRESS_IDENTIFYING, "Looking at your photos…")

    try:
        identified = await image_analyzer.identify(images_data, language=language)
    except TypeError:
        identified = await image_analyzer.identify(images_data)

    name = identified.get("name") or ""
    condition = identified.get("condition") or "Good"
    category = identified.get("category")

    await emit(
        "identified",
        PROGRESS_IDENTIFIED,
        f"Identified: {name}" if name else "Identified the item",
        patch={"name": name, "condition": condition},
    )

    # Everything below runs concurrently — see the module docstring.
    progress = PROGRESS_IDENTIFIED

    async def run_stage(key: str, coro, message: str, to_patch):
        nonlocal progress
        try:
            value = await coro
        except Exception as e:
            logger.error(f"Listing stage '{key}' failed: {e}")
            value = None
        progress += PROGRESS_PER_PARALLEL_STAGE
        await emit(key, progress, message, patch=to_patch(value) if value else None)
        return key, value

    try:
        desc_coro = image_analyzer.describe(images_data, language=language)
    except TypeError:
        desc_coro = image_analyzer.describe(images_data)

    def _parse_described(val):
        if not val:
            return {"description": ""}
        if isinstance(val, dict):
            desc = val.get("en", {}).get("description") or ""
            return {"description": desc, "translations": val}
        if not isinstance(val, str):
            return {"description": str(val)}

        clean_str = val.strip()
        match = re.search(r"(\{[\s\S]*\})", clean_str)
        candidate = match.group(1).strip() if match else clean_str

        parsed = None
        try:
            parsed = json.loads(candidate, strict=False)
        except Exception as exc:
            logger.debug(f"json.loads failed on candidate: {exc}")

        if not parsed and jiter:
            try:
                parsed = jiter.from_json(candidate.encode("utf-8"), partial_mode=True)
            except Exception as exc:
                logger.debug(f"jiter failed on candidate: {exc}")

        if isinstance(parsed, dict):
            norm = {}
            for k, v in parsed.items():
                if not isinstance(v, dict):
                    continue
                k_lower = str(k).lower()
                if k_lower in ("en", "english"):
                    norm["en"] = v
                elif k_lower in ("ms", "malay", "bahasa", "bahasa melayu"):
                    norm["ms"] = v
                elif k_lower in ("zh", "chinese", "mandarin", "simplified chinese", "zh-cn"):
                    norm["zh"] = v
                else:
                    norm[k] = v

            if any(k in norm for k in ("en", "ms", "zh")):
                en_desc = norm.get("en", {}).get("description") or ""
                return {"description": en_desc, "translations": norm}

        return {"description": val}

    stages = [
        run_stage(
            "described",
            desc_coro,
            "Description written",
            _parse_described,
        ),
        run_stage(
            "priced",
            market_service.aget_market_valuation(query=name, condition=condition, category=category),
            "Market price checked",
            lambda market: {"price": market.get("suggested_listing")},
        ),
    ]

    results = dict(await asyncio.gather(*stages))
    parsed_desc = _parse_described(results.get("described"))

    return {
        **identified,
        "description": parsed_desc.get("description") or "",
        "market_data": results.get("priced"),
        "translations": parsed_desc.get("translations"),
    }
