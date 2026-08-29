"""
Custom Image Analyzer Service
Analyzes images using Gemini Vision API directly (no Apify dependency).

Two ways in:

* `analyze()` — one round trip that returns every field at once. Simple, and
  what the non-streaming /analyze-image endpoint still uses.
* `identify()` + `describe()` — the same work split into a short, fast call
  (what is this item?) and a slow one (write the listing copy). Splitting them
  lets the caller start the market-price lookup, which only needs the item's
  name, while the description is still being written. See
  `agent.tools.listing_pipeline`.
"""

import asyncio
import json

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from env import GEMINI_API_KEY
from logger import logger

# Every extra photo costs upload bandwidth and vision-model latency while
# adding almost no signal — the first few angles already describe the item.
MAX_ANALYSIS_IMAGES = 4

ANALYZE_PROMPT = """
You are an expert e-commerce listing assistant for a Malaysian marketplace.
Analyze these images and generate a compelling listing.

Return a JSON object with EXACTLY these fields:
{
    "name": "A short, catchy product title (max 60 chars)",
    "description": "A detailed, compelling description in Markdown. Include key features, specifications, and selling points. Use bullet points for features.",
    "condition": "One of: New, Like New, Good, Fair",
    "category": "Best fitting category (Electronics, Fashion, Home, Sports, etc.)",
    "suggested_keywords": ["keyword1", "keyword2", "keyword3"]
}

Guidelines:
- Assess condition from visual cues: packaging, wear, scratches, dust
- Default to 'Good' if condition is unclear
- Write description as if listing on Carousell/Facebook Marketplace
- Be specific about what you see
- DO NOT make up features you can't verify from the images
"""

# Deliberately short output — this call is on the critical path for everything
# that follows, so it must come back fast. No description is requested here.
IDENTIFY_PROMPT = """
You are an expert e-commerce listing assistant for a Malaysian marketplace.
Identify the item in these images. Be fast and precise — no prose.

Return ONLY a JSON object with EXACTLY these fields:
{
    "name": "A short, catchy product title (max 60 chars)",
    "condition": "One of: New, Like New, Good, Fair",
    "category": "Best fitting category (Electronics, Fashion, Home, Sports, etc.)",
    "suggested_keywords": ["keyword1", "keyword2", "keyword3"]
}

Guidelines:
- Include brand and model in the name whenever they are visible — the name is
  used verbatim to search for market prices, so it must be specific
- Assess condition from visual cues: packaging, wear, scratches, dust
- Default to 'Good' if condition is unclear
- Return ONLY the raw JSON, no markdown fences
"""

DESCRIBE_PROMPT = """
You are an expert e-commerce listing assistant for a Malaysian marketplace.
Write the listing description for the item in these images.

Return ONLY the description as Markdown — no JSON, no code fences, no title,
no preamble. Include key features, specifications and selling points, using
bullet points for features.

Guidelines:
- Write as if listing on Carousell/Facebook Marketplace
- Be specific about what you see, including any visible wear
- DO NOT make up features you can't verify from the images
"""


class ImageAnalyzerService:
    """
    Analyzes product images to extract:
    - Product name/title
    - Description
    - Condition (New, Like New, Good, Fair)
    """

    def __init__(self):
        self.model = ChatGoogleGenerativeAI(
            model="gemini-3.6-flash",
            temperature=0.3,
            google_api_key=GEMINI_API_KEY
        ) if GEMINI_API_KEY else None

    @staticmethod
    def _build_content(prompt: str, images_data: list[dict]) -> list[dict]:
        """Build the multimodal message content: the prompt plus each image."""
        content = [{"type": "text", "text": prompt}]
        for img in images_data[:MAX_ANALYSIS_IMAGES]:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img['mime_type']};base64,{img['base64_image']}"}
            })
        return content

    @staticmethod
    def _extract_text(content) -> str:
        """Flatten a LangChain response body, which may be a list of parts."""
        if not isinstance(content, list):
            return content

        text_parts = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and 'text' in part:
                text_parts.append(part['text'])
        return ''.join(text_parts)

    async def _ask(self, prompt: str, images_data: list[dict]) -> str:
        """Run one vision call off the event loop and return its text body.

        The LangChain client is synchronous; `to_thread` keeps it from pinning
        the event loop so several of these can genuinely run at once.
        """
        msg = HumanMessage(content=self._build_content(prompt, images_data))
        response = await asyncio.to_thread(self.model.invoke, [msg])
        return self._extract_text(response.content)

    async def analyze(self, images_data: list[dict]) -> dict:
        """
        Analyze multiple images and return product details.

        Args:
            images_data: list of dicts with 'base64_image' and 'mime_type'

        Returns:
            dict with 'name', 'description', 'condition'
        """
        if not self.model:
            return self._get_fallback_response()

        content = None
        try:
            content = await self._ask(ANALYZE_PROMPT, images_data)

            # Clean up the response
            clean_content = content.replace('```json', '').replace('```', '').strip()
            result = json.loads(clean_content)

            # Ensure required fields exist
            result.setdefault("name", "Unknown Item")
            result.setdefault("description", "No description available.")
            result.setdefault("condition", "Good")
            result.setdefault("category", "Other")
            result.setdefault("suggested_keywords", [])

            return result

        except json.JSONDecodeError as e:
            logger.info(f"Failed to parse Gemini response as JSON: {e}")
            logger.info(f"Raw response: {content}")
            return self._get_fallback_response()
        except Exception as e:
            logger.info(f"Image analysis error: {e}")
            return self._get_fallback_response()

    async def identify(self, images_data: list[dict]) -> dict:
        """Fast pass: what is this item? Returns name/condition/category/keywords.

        Never raises — a failure here degrades to the fallback shape so the
        rest of the pipeline can still run.
        """
        if not self.model:
            fallback = self._get_fallback_response()
            fallback.pop("description", None)
            return fallback

        content = None
        try:
            content = await self._ask(IDENTIFY_PROMPT, images_data)
            clean_content = content.replace('```json', '').replace('```', '').strip()
            result = json.loads(clean_content)

            result.setdefault("name", "Unknown Item")
            result.setdefault("condition", "Good")
            result.setdefault("category", "Other")
            result.setdefault("suggested_keywords", [])
            return result

        except json.JSONDecodeError as e:
            logger.info(f"Failed to parse identify response as JSON: {e}")
            logger.info(f"Raw response: {content}")
        except Exception as e:
            logger.info(f"Item identification error: {e}")

        fallback = self._get_fallback_response()
        fallback.pop("description", None)
        return fallback

    async def describe(self, images_data: list[dict]) -> str | None:
        """Slow pass: the Markdown listing copy. Returns None if unavailable."""
        if not self.model:
            return None

        try:
            content = await self._ask(DESCRIBE_PROMPT, images_data)
            return content.strip() or None
        except Exception as e:
            logger.info(f"Item description error: {e}")
            return None

    def _get_fallback_response(self) -> dict:
        """Return a fallback response when analysis fails."""
        return {
            "name": "Item",
            "description": "Please add a description for this item.",
            "condition": "Good",
            "category": "Other",
            "suggested_keywords": [],
            "error": "Image analysis unavailable. Please set GEMINI_API_KEY."
        }


# Singleton instance
image_analyzer = ImageAnalyzerService()
