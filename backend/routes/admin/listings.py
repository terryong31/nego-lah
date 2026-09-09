"""Listing-authoring aids: AI image analysis (streaming and one-shot) and market
valuation. These help an admin *write* a listing; the listing CRUD itself lives
in `items.py`.
"""

import asyncio
import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from logger import logger
from schemas import MarketValuationRequest

router = APIRouter()


async def _encode_images(images: list[UploadFile]) -> list[dict]:
    """Read and base64-encode uploads concurrently, preserving their order."""
    import asyncio
    import base64

    from core.images import process_upload

    def _normalize_and_encode(raw: bytes) -> tuple[str, str]:
        # SPEC-054: normalize BEFORE encoding. A HEIC straight off an iPhone is
        # undecodable by the vision model, and a 12 MP JPEG is an expensive way
        # to ask "what is this?" — the analysis only needs a normal photo.
        # Both steps are CPU work, so they share the one thread hop.
        normalized, content_type, _ = process_upload(raw)
        return base64.b64encode(normalized).decode('utf-8'), content_type

    async def encode(img: UploadFile) -> dict:
        contents = await img.read()
        # Keep it off the event loop so several images encode at once instead
        # of one after another.
        base64_image, mime_type = await asyncio.to_thread(_normalize_and_encode, contents)
        return {"base64_image": base64_image, "mime_type": mime_type}

    return list(await asyncio.gather(*(encode(img) for img in images)))


@router.post("/analyze-image/stream")
async def analyze_item_image_stream(
    images: list[UploadFile] = File(...),
    language: str = Form("all")
):
    """Streaming twin of /analyze-image.

    Emits Server-Sent Events as each pipeline stage genuinely completes, so the
    client can show a real progress percentage (and fill in fields early)
    instead of animating a fake bar. See agent.tools.listing_pipeline for why
    the stages overlap.
    """
    import asyncio

    from agent.tools.listing_pipeline import analyze_listing

    # Read the uploads before streaming starts — the request body is not
    # available once we've handed back a streaming response.
    images_data = await _encode_images(images)

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_progress(event: dict):
            await queue.put(event)

        async def run():
            try:
                try:
                    data = await analyze_listing(images_data, on_progress, language=language)
                except TypeError:
                    data = await analyze_listing(images_data, on_progress)
                await queue.put({"stage": "done", "progress": 100, "message": "Done", "result": data})
            except Exception as e:
                logger.error(f"Error analyzing image: {e}")
                await queue.put({"stage": "error", "progress": 100, "message": f"Failed to analyze image: {e}"})
            finally:
                await queue.put(None)

        worker = asyncio.create_task(run())
        try:
            yield f"data: {json.dumps({'stage': 'uploaded', 'progress': 10, 'message': 'Photos received'})}\n\n"
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            # The client hung up (or we're done) — don't leave the pipeline running.
            worker.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Tells nginx/Caddy-style proxies not to buffer, which would
            # defeat the whole point of streaming progress.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/analyze-image")
async def analyze_item_image(
    images: list[UploadFile] = File(...),
    language: str = Form("en")
):
    """
    Analyze uploaded images to generate item details (Name, Description, Condition).
    Uses custom Image Analyzer service (Gemini Vision).

    Non-streaming fallback for clients that can't read the SSE variant above.
    """
    from agent.tools.image_analyzer import image_analyzer
    from agent.tools.market_price import market_service

    try:
        images_data = await _encode_images(images)

        # --- Custom Image Analyzer (Gemini Vision) ---
        logger.info(f"Analyzing {len(images_data)} image(s) with custom Image Analyzer in language={language}...")
        try:
            data = await image_analyzer.analyze(images_data, language=language)
        except TypeError:
            data = await image_analyzer.analyze(images_data)
        logger.info(f"Image analysis result: {data}")

        # --- Market Valuation ---
        try:
            logger.info(f"Fetching market data for: {data.get('name')}")
            # Market valuation scrapes the web synchronously — seconds, not
            # milliseconds — so it cannot run on the event loop.
            market_data = await asyncio.to_thread(
                market_service.get_market_valuation,
                query=data.get('name', ''),
                condition=data.get('condition', 'good'),
                category=data.get('category')
            )
            data['market_data'] = market_data
        except Exception as market_error:
            logger.error(f"Market valuation failed: {market_error}")
            data['market_data'] = None

        return data

    except Exception as e:
        logger.error(f"Error analyzing image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze image: {str(e)}") from e


# =====================
# Market Valuation Endpoint
# =====================

@router.post("/market-valuation")
def get_market_valuation(request: MarketValuationRequest):
    """
    Get market valuation for an item directly.
    Uses custom Market Valuator (NO APIFY - implement your own scraper!).
    """
    from agent.tools.market_price import market_service

    try:
        logger.info(f"Fetching market data for: {request.query} ({request.condition})")
        market_data = market_service.get_market_valuation(
            query=request.query,
            condition=request.condition,
            category=request.category
        )
        return market_data
    except Exception as e:
        logger.error(f"Market valuation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
