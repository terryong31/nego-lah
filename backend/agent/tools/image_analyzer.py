"""
Custom Image Analyzer Service
Analyzes images using Gemini Vision API directly (no Apify dependency).
"""

import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from env import GEMINI_API_KEY


class ImageAnalyzerService:
    """
    Analyzes product images to extract:
    - Product name/title
    - Description
    - Condition (New, Like New, Good, Fair)
    """
    
    def __init__(self):
        self.model = ChatGoogleGenerativeAI(
            model="gemini-3-flash-preview",
            temperature=0.3,
            google_api_key=GEMINI_API_KEY
        ) if GEMINI_API_KEY else None
    
    async def analyze(self, base64_image: str, mime_type: str = "image/jpeg") -> dict:
        """
        Analyze an image and return product details.
        
        Args:
            base64_image: Base64 encoded image string
            mime_type: MIME type of the image (default: image/jpeg)
        
        Returns:
            dict with 'name', 'description', 'condition'
        """
        if not self.model:
            return self._get_fallback_response()
        
        prompt = """
You are an expert e-commerce listing assistant for a Malaysian marketplace.
Analyze this image and generate a compelling listing.

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
- DO NOT make up features you can't verify from the image
"""
        
        try:
            msg = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
                    }
                ]
            )
            
            response = self.model.invoke([msg])
            content = response.content
            
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
            print(f"Failed to parse Gemini response as JSON: {e}")
            print(f"Raw response: {content}")
            return self._get_fallback_response()
        except Exception as e:
            print(f"Image analysis error: {e}")
            return self._get_fallback_response()
    
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
