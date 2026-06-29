"""
Custom Image Analyzer Service
Analyzes images using Gemini Vision API directly (no Apify dependency).
"""

import json
from langchain_google_genai import ChatGoogleGenerativeAI
from logger import logger
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
        
        prompt = """
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
        
        try:
            content = [{"type": "text", "text": prompt}]
            for img in images_data:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{img['mime_type']};base64,{img['base64_image']}"}
                })
                
            msg = HumanMessage(content=content)
            
            response = self.model.invoke([msg])
            content = response.content
            
            # Handle case where content is a list (LangChain multimodal response)
            if isinstance(content, list):
                # Extract text from the list - usually first item or text part
                text_parts = []
                for part in content:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict) and 'text' in part:
                        text_parts.append(part['text'])
                content = ''.join(text_parts)
            
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
