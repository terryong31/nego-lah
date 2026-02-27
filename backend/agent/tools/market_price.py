"""
Custom Market Valuator Service
================================

Provides market price valuations using intelligent estimation
based on item category and condition.
"""

import statistics
from typing import Optional, List
from logger import logger


# Condition multipliers (higher = better condition = higher price)
CONDITION_MULTIPLIERS = {
    "new": 1.0,
    "like new": 0.85,
    "good": 0.70,
    "fair": 0.55,
    "refurbished": 0.75,
}

# Base price ranges by category (in MYR)
CATEGORY_BASE_PRICES = {
    "electronics": {"min": 100, "max": 2000, "avg": 500},
    "fashion": {"min": 20, "max": 500, "avg": 100},
    "home": {"min": 30, "max": 800, "avg": 150},
    "sports": {"min": 50, "max": 1000, "avg": 200},
    "toys": {"min": 20, "max": 300, "avg": 80},
    "books": {"min": 5, "max": 100, "avg": 25},
    "vehicles": {"min": 1000, "max": 50000, "avg": 15000},
    "collectibles": {"min": 50, "max": 5000, "avg": 500},
    "other": {"min": 20, "max": 500, "avg": 100},
}


class MarketPriceService:
    """
    Provides market price valuations for items using intelligent estimation
    based on item category and condition.
    """
    
    def get_market_valuation(
        self, 
        query: str, 
        condition: str = "good",
        category: Optional[str] = None,
    ) -> dict:
        """
        Get market valuation for an item.
        
        Args:
            query: Item name/search query
            condition: Item condition (new, like new, good, fair)
            category: Item category (optional, will be inferred from query)
        
        Returns:
            dict with market_average, min_price, max_price, suggested_listing, currency
        """
        return self._estimate_price(query, condition, category)
    
    def _estimate_price(
        self, 
        query: str, 
        condition: str,
        category: Optional[str] = None
    ) -> dict:
        """
        Estimate price based on item characteristics.
        """
        # Infer category from query if not provided
        if not category:
            category = self._infer_category(query)
        
        category = category.lower() if category else "other"
        condition = condition.lower() if condition else "good"
        
        # Get base prices for category
        base = CATEGORY_BASE_PRICES.get(category, CATEGORY_BASE_PRICES["other"])
        
        # Apply condition multiplier
        multiplier = CONDITION_MULTIPLIERS.get(condition, 0.70)
        
        # Add some variance based on query hash (for consistency)
        query_hash = sum(ord(c) for c in query.lower()) % 100
        variance = 0.8 + (query_hash / 100) * 0.4  # 0.8 to 1.2
        
        avg_price = base["avg"] * multiplier * variance
        min_price = base["min"] * multiplier * variance
        max_price = base["max"] * multiplier * variance
        
        # Suggested listing price (slightly below average for quick sale)
        suggested = avg_price * 0.92
        
        return {
            "market_average": self._round_price(avg_price),
            "min_price": self._round_price(min_price),
            "max_price": self._round_price(max_price),
            "suggested_listing": self._round_price(suggested),
            "currency": "MYR",
            "source": "Estimation",
            "category_detected": category,
            "condition_used": condition,
        }
    
    def _infer_category(self, query: str) -> str:
        """Infer category from query keywords."""
        query_lower = query.lower()
        
        electronics_keywords = [
            "phone", "laptop", "computer", "pc", "iphone", "samsung", "macbook",
            "tablet", "ipad", "camera", "headphone", "speaker", "tv", "monitor",
            "keyboard", "mouse", "gpu", "processor", "earbuds", "airpods", "watch"
        ]
        
        fashion_keywords = [
            "shirt", "pants", "dress", "shoes", "bag", "wallet", "jacket",
            "jeans", "sneakers", "nike", "adidas", "gucci", "louis", "chanel"
        ]
        
        sports_keywords = [
            "bicycle", "bike", "bmx", "gym", "dumbbell", "tennis", "badminton",
            "football", "soccer", "basketball", "golf", "yoga", "running"
        ]
        
        home_keywords = [
            "sofa", "table", "chair", "bed", "lamp", "kitchen", "furniture",
            "shelf", "cabinet", "mattress", "pillow", "curtain"
        ]
        
        vehicles_keywords = [
            "car", "motorcycle", "motor", "bike", "scooter", "vespa", "honda",
            "toyota", "bmw", "mercedes"
        ]
        
        for kw in electronics_keywords:
            if kw in query_lower:
                return "electronics"
        
        for kw in fashion_keywords:
            if kw in query_lower:
                return "fashion"
        
        for kw in sports_keywords:
            if kw in query_lower:
                return "sports"
                
        for kw in home_keywords:
            if kw in query_lower:
                return "home"
        
        for kw in vehicles_keywords:
            if kw in query_lower:
                return "vehicles"
        
        return "other"
    
    def _analyze_scraped_prices(self, items: list, condition: str) -> dict:
        """
        Analyze scraped price data.
        
        Args:
            items: List of scraped items with 'price' field
            condition: Item condition for adjustment
        
        Returns:
            Market valuation dict
        """
        prices = [item.get("price", 0) for item in items if item.get("price")]
        
        if not prices:
            return self._estimate_price("", condition)
        
        avg_price = statistics.mean(prices)
        min_price = min(prices)
        max_price = max(prices)
        
        # Apply condition multiplier
        multiplier = CONDITION_MULTIPLIERS.get(condition.lower(), 0.70)
        
        return {
            "market_average": self._round_price(avg_price * multiplier),
            "min_price": self._round_price(min_price * multiplier),
            "max_price": self._round_price(max_price * multiplier),
            "suggested_listing": self._round_price(avg_price * multiplier * 0.92),
            "currency": "MYR",
            "source": "Scraped Data",
            "sample_size": len(prices),
        }
    
    def _round_price(self, price: float) -> float:
        """Round price Malaysian style (psychological pricing)."""
        if price < 10:
            return round(price, 2)
        elif price < 100:
            base = int(price)
            decimal = price - base
            if decimal < 0.3:
                return float(base)
            elif decimal < 0.7:
                return base + 0.88
            else:
                return base + 0.90
        else:
            # Round to nearest 5, then subtract 0.10
            rounded = round(price / 5) * 5
            if rounded < 500:
                return rounded - 0.10
            return float(rounded)


# Singleton instance
market_service = MarketPriceService()
