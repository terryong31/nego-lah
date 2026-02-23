"""
Carousell Malaysia Scraper
===========================

Adapted from: https://github.com/albertleng/CarousellWebScraper
Modified for Carousell Malaysia using Playwright (async).

Usage:
    scraper = CarousellScraper()
    results = await scraper.search("bmx bicycle", limit=10)
    
    # Or with filters:
    results = await scraper.search(
        query="iphone 13",
        condition="USED",
        min_price=500,
        max_price=2000,
        limit=15
    )
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional, List
from dataclasses import dataclass, asdict
from bs4 import BeautifulSoup


@dataclass
class CarousellListing:
    """Represents a Carousell listing."""
    title: str
    price: float
    currency: str = "MYR"
    condition: Optional[str] = None
    seller: Optional[str] = None
    seller_url: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    posted_date: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)


class CarousellScraper:
    """
    Scrapes listings from Carousell Malaysia.
    Uses Playwright for browser automation (handles JS rendering).
    """
    
    BASE_URL = "https://www.carousell.com.my"
    
    def __init__(self, headless: bool = True):
        """
        Initialize the scraper.
        
        Args:
            headless: Run browser in headless mode (default: True)
        """
        self.headless = headless
        self.browser = None
        self.context = None
    
    def _build_search_url(
        self,
        query: str,
        condition: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        sort_by: str = "time_created,descending"
    ) -> str:
        """Build the search URL with filters."""
        # URL encode the query
        encoded_query = query.replace(" ", "%20")
        url = f"{self.BASE_URL}/search/{encoded_query}?"
        
        params = []
        
        if condition:
            # Carousell uses condition_v2: NEW, USED
            params.append(f"condition_v2={condition.upper()}")
        
        if min_price is not None:
            params.append(f"price_start={min_price}")
        
        if max_price is not None:
            params.append(f"price_end={max_price}")
        
        params.append(f"sort_by={sort_by}")
        
        return url + "&".join(params)
    
    def _parse_price(self, price_text: str) -> float:
        """Extract numeric price from text like 'RM 150' or 'RM150.00'."""
        if not price_text:
            return 0.0
        
        # Remove currency symbols and whitespace
        cleaned = re.sub(r"[^\d.]", "", price_text)
        
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    
    def _parse_date(self, date_text: str) -> str:
        """
        Convert relative dates to YYYY-MM-DD format.
        Examples: "2 hours ago", "3 days ago", "Spotlight", "New Carouseller"
        """
        if not date_text:
            return datetime.now().strftime("%Y-%m-%d")
        
        date_lower = date_text.lower()
        now = datetime.now()
        
        if "hour" in date_lower:
            hours = int(re.sub(r"[a-zA-Z\s]", "", date_text) or 1)
            result = now - timedelta(hours=hours)
        elif "minute" in date_lower:
            minutes = int(re.sub(r"[a-zA-Z\s]", "", date_text) or 1)
            result = now - timedelta(minutes=minutes)
        elif "day" in date_lower:
            days = int(re.sub(r"[a-zA-Z\s]", "", date_text) or 1)
            result = now - timedelta(days=days)
        elif "week" in date_lower:
            weeks = int(re.sub(r"[a-zA-Z\s]", "", date_text) or 1)
            result = now - timedelta(weeks=weeks)
        elif "month" in date_lower:
            months = int(re.sub(r"[a-zA-Z\s]", "", date_text) or 1)
            result = now - timedelta(days=months * 30)
        elif "spotlight" in date_lower or "new carouseller" in date_lower:
            result = now
        else:
            result = now
        
        return result.strftime("%Y-%m-%d")
    
    def _shorten_url(self, url: str) -> str:
        """Remove query parameters from URL."""
        pos = url.find("?")
        return url[:pos] if pos != -1 else url
    
    async def search(
        self,
        query: str,
        condition: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        limit: int = 10
    ) -> List[CarousellListing]:
        """
        Search Carousell Malaysia for listings.
        
        Args:
            query: Search term (e.g., "bmx bicycle", "iphone 13")
            condition: Filter by condition (NEW, USED)
            min_price: Minimum price in MYR
            max_price: Maximum price in MYR
            limit: Maximum number of results to return
        
        Returns:
            List of CarousellListing objects
        """
        from playwright.async_api import async_playwright
        
        url = self._build_search_url(query, condition, min_price, max_price)
        logger.info(f"[CarousellScraper] Searching: {url}")
        
        listings = []
        
        async with async_playwright() as p:
            # Launch browser with memory-saving args for server environment
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",  # Overcome limited shared memory in Docker
                    "--disable-gpu",
                    "--single-process",  # Reduce memory usage
                    "--disable-extensions",
                    "--disable-software-rasterizer",
                ]
            )
            
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            page = await context.new_page()
            
            try:
                # Navigate to search page
                await page.goto(url, wait_until="networkidle", timeout=30000)
                
                # Wait for content to load
                await page.wait_for_timeout(2000)
                
                # Scroll to load more listings
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(500)
                
                # Get page source and parse with BeautifulSoup
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                
                # Find main content container
                main = soup.find("main")
                if not main:
                    logger.info("[CarousellScraper] Could not find main content")
                    await browser.close()
                    return listings
                
                # Find all listing links
                # Carousell listings are typically <a> tags with href containing /p/
                listing_links = main.find_all("a", href=re.compile(r"/p/"))
                
                seen_urls = set()
                
                for link in listing_links:
                    if len(listings) >= limit:
                        break
                    
                    try:
                        href = link.get("href", "")
                        if not href or "/p/" not in href:
                            continue
                        
                        # Full URL
                        item_url = self._shorten_url(
                            href if href.startswith("http") else f"{self.BASE_URL}{href}"
                        )
                        
                        # Skip duplicates
                        if item_url in seen_urls:
                            continue
                        seen_urls.add(item_url)
                        
                        # Extract text content
                        paragraphs = link.find_all("p")
                        
                        title = ""
                        price_text = ""
                        
                        for p in paragraphs:
                            text = p.get_text(strip=True)
                            if not text:
                                continue
                            
                            # Check if this looks like a price
                            if "RM" in text or re.match(r"^[\d,\.]+$", text):
                                if not price_text:
                                    price_text = text
                            elif len(text) > 3 and not title:
                                # First substantial text is likely the title
                                title = text
                        
                        # Skip if we couldn't extract essential info
                        if not title and not price_text:
                            continue
                        
                        # Extract image
                        img = link.find("img")
                        image_url = img.get("src") if img else None
                        
                        # Create listing
                        listing = CarousellListing(
                            title=title or "Unknown Item",
                            price=self._parse_price(price_text),
                            currency="MYR",
                            url=item_url,
                            image_url=image_url,
                            posted_date=datetime.now().strftime("%Y-%m-%d")
                        )
                        
                        listings.append(listing)
                        logger.info(f"  [{len(listings)}] {listing.title[:40]} - RM {listing.price}")
                    
                    except Exception as e:
                        logger.info(f"[CarousellScraper] Error parsing listing: {e}")
                        continue
                
                # Try alternative parsing if we got no results
                if not listings:
                    logger.info("[CarousellScraper] Trying alternative parsing method...")
                    listings = await self._parse_alternative(page, limit)
                
            except Exception as e:
                logger.info(f"[CarousellScraper] Error: {e}")
                # Save screenshot for debugging
                try:
                    await page.screenshot(path="carousell_error.png")
                    logger.info("[CarousellScraper] Error screenshot saved to carousell_error.png")
                except:
                    pass
            
            finally:
                await browser.close()
        
        logger.info(f"[CarousellScraper] Found {len(listings)} listings")
        return listings
    
    async def _parse_alternative(self, page, limit: int) -> List[CarousellListing]:
        """Alternative parsing method using page selectors directly."""
        listings = []
        
        try:
            # Try to find listing cards by various selectors
            selectors = [
                '[data-testid="listing-card"]',
                '[class*="listing-card"]',
                'a[href*="/p/"]'
            ]
            
            for selector in selectors:
                elements = await page.query_selector_all(selector)
                if elements:
                    logger.info(f"[CarousellScraper] Found {len(elements)} elements with selector: {selector}")
                    
                    for el in elements[:limit]:
                        try:
                            text = await el.inner_text()
                            href = await el.get_attribute("href")
                            
                            lines = [l.strip() for l in text.split("\n") if l.strip()]
                            
                            title = ""
                            price = 0.0
                            
                            for line in lines:
                                if "RM" in line:
                                    price = self._parse_price(line)
                                elif len(line) > 3 and not title:
                                    title = line
                            
                            if title or price:
                                listing = CarousellListing(
                                    title=title or "Unknown",
                                    price=price,
                                    currency="MYR",
                                    url=self._shorten_url(f"{self.BASE_URL}{href}") if href else None
                                )
                                listings.append(listing)
                        except:
                            continue
                    
                    if listings:
                        break
        except Exception as e:
            logger.info(f"[CarousellScraper] Alternative parsing failed: {e}")
        
        return listings
    
    async def get_listing_details(self, listing_url: str) -> Optional[dict]:
        """
        Get detailed information about a specific listing.
        
        Args:
            listing_url: Full URL to the listing
        
        Returns:
            dict with detailed listing info, or None if not found
        """
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            page = await context.new_page()
            
            try:
                await page.goto(listing_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)
                
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                
                # Extract details
                details = {
                    "url": listing_url,
                    "title": None,
                    "price": None,
                    "description": None,
                    "condition": None,
                    "seller": None,
                    "images": []
                }
                
                # Title is usually in h1
                h1 = soup.find("h1")
                if h1:
                    details["title"] = h1.get_text(strip=True)
                
                # Find all paragraphs for price/description
                paragraphs = soup.find_all("p")
                for p in paragraphs:
                    text = p.get_text(strip=True)
                    if "RM" in text and not details["price"]:
                        details["price"] = self._parse_price(text)
                
                # Find images
                images = soup.find_all("img")
                for img in images:
                    src = img.get("src", "")
                    if "carousell" in src and "avatar" not in src.lower():
                        details["images"].append(src)
                
                return details
                
            except Exception as e:
                logger.info(f"[CarousellScraper] Error getting listing details: {e}")
                return None
            
            finally:
                await browser.close()


# ====================
# Helper function for market_price.py integration
# ====================

async def search_market_prices(query: str, limit: int = 10) -> List[dict]:
    """
    Search Carousell and return listings as dicts.
    This is the function to integrate with market_price.py
    """
    scraper = CarousellScraper(headless=True)
    listings = await scraper.search(query, limit=limit)
    return [l.to_dict() for l in listings]


# ====================
# CLI for testing
# ====================

async def main():
    """Test the scraper."""
    logger.info("="*60)
    logger.info("Carousell Malaysia Scraper")
    logger.info("="*60)
    
    query = input("\nEnter search query (e.g., 'bmx bicycle'): ").strip() or "bmx bicycle"
    
    # Ask for headless mode
    headless_input = input("Run headless? (y/n, default: y): ").strip().lower()
    headless = headless_input != "n"
    
    scraper = CarousellScraper(headless=headless)
    
    logger.info(f"\nSearching for '{query}'...")
    logger.info("-"*60)
    
    results = await scraper.search(query, limit=10)
    
    if results:
        logger.info(f"\n{'='*60}")
        logger.info(f"FOUND {len(results)} LISTINGS")
        logger.info("="*60)
        
        for i, listing in enumerate(results, 1):
            logger.info(f"\n[{i}] {listing.title}")
            logger.info(f"    Price: RM {listing.price:.2f}")
            logger.info(f"    URL: {listing.url}")
            if listing.image_url:
                logger.info(f"    Image: {listing.image_url[:60]}...")
        
        # Calculate price stats
        prices = [l.price for l in results if l.price > 0]
        if prices:
            logger.info(f"\n{'='*60}")
            logger.info("PRICE ANALYSIS")
            logger.info("="*60)
            logger.info(f"  Average: RM {sum(prices)/len(prices):.2f}")
            logger.info(f"  Min: RM {min(prices):.2f}")
            logger.info(f"  Max: RM {max(prices):.2f}")
    else:
        logger.info("\nNo results found. Try a different query or run non-headless to debug.")


if __name__ == "__main__":
    asyncio.run(main())