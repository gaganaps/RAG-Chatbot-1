"""Web scraper for retrieving official Groww mutual fund scheme pages."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import random
import time
from typing import Any, Dict, Optional

from bs4 import BeautifulSoup
import httpx

from src.config import ACTIVE_SCHEMES, DATA_RAW_DIR, SchemeConfig

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


class GrowwScraper:
    """Scraper to extract HTML and server-side JSON data from Groww mutual fund URLs."""

    def __init__(self, raw_dir: Path = DATA_RAW_DIR, timeout: float = 15.0):
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout

    def fetch_page(self, url: str, max_retries: int = 3) -> str:
        """Fetch raw HTML from a target Groww URL with exponential backoff retry.
        
        Args:
            url: The Groww scheme page URL.
            max_retries: Maximum retry attempts for transient errors.
            
        Returns:
            The raw HTML content string.
            
        Raises:
            httpx.HTTPError: If the request fails after all retries.
        """
        delay = 1.5
        last_exception = None

        with httpx.Client(headers=DEFAULT_HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"Fetching URL (Attempt {attempt}/{max_retries}): {url}")
                    response = client.get(url)
                    response.raise_for_status()
                    return response.text
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    last_exception = exc
                    logger.warning(f"Fetch attempt {attempt} failed for {url}: {exc}")
                    if attempt < max_retries:
                        sleep_time = delay + random.uniform(0.5, 1.5)
                        logger.info(f"Backing off for {sleep_time:.2f}s before retry...")
                        time.sleep(sleep_time)
                        delay *= 2

        raise last_exception or httpx.RequestError(f"Failed to fetch {url}")

    def extract_next_data(self, html_content: str) -> Optional[Dict[str, Any]]:
        """Extract Next.js __NEXT_DATA__ JSON payload from raw HTML.
        
        Args:
            html_content: The HTML string of the scheme page.
            
        Returns:
            The extracted mfServerSideData dictionary, or None if not found.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if not script_tag or not script_tag.string:
            logger.warning("Could not find script#__NEXT_DATA__ in page HTML.")
            return None

        try:
            payload = json.loads(script_tag.string)
            mf_data = payload.get("props", {}).get("pageProps", {}).get("mfServerSideData")
            return mf_data
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error parsing __NEXT_DATA__ JSON: {e}")
            return None

    def scrape_scheme(
        self,
        scheme_config: SchemeConfig,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Scrape a single scheme, utilizing local raw cache when available.
        
        Args:
            scheme_config: SchemeConfig instance containing scheme_id and groww_url.
            force_refresh: If True, fetches live data regardless of cached content.
            
        Returns:
            Dictionary containing scheme metadata, raw_html, mf_data, and scrape timestamp.
        """
        scheme_id = scheme_config.scheme_id
        html_file = self.raw_dir / f"{scheme_id}.html"
        json_file = self.raw_dir / f"{scheme_id}.json"

        # Check local cache first if refresh not forced
        if not force_refresh and html_file.exists() and json_file.exists():
            logger.info(f"Loading cached raw data for '{scheme_id}' from {json_file}")
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                return cached_data
            except Exception as e:
                logger.warning(f"Error reading local cache for '{scheme_id}', re-scraping: {e}")

        # Fetch live HTML
        html_content = self.fetch_page(scheme_config.groww_url)
        mf_data = self.extract_next_data(html_content)
        scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        result_payload = {
            "scheme_id": scheme_id,
            "scheme_name": scheme_config.scheme_name,
            "source_url": scheme_config.groww_url,
            "last_scraped_date": scraped_at,
            "mf_server_side_data": mf_data,
            "raw_html": html_content,
        }

        # Cache HTML and JSON locally
        try:
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(html_content)
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(result_payload, f, indent=2, ensure_ascii=False)
            logger.info(f"Successfully cached raw data for '{scheme_id}' in {self.raw_dir}")
        except Exception as e:
            logger.error(f"Failed to write cache files for '{scheme_id}': {e}")

        return result_payload

    def scrape_all_active_schemes(
        self,
        force_refresh: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """Scrape all 5 active HDFC schemes defined in src.config.
        
        Args:
            force_refresh: If True, re-fetches all pages from Groww.
            
        Returns:
            Dictionary mapping scheme_id to raw scraped payload.
        """
        results: Dict[str, Dict[str, Any]] = {}
        schemes = list(ACTIVE_SCHEMES.values())

        for idx, scheme in enumerate(schemes):
            logger.info(f"Scraping scheme [{idx + 1}/{len(schemes)}]: {scheme.scheme_name}")
            try:
                res = self.scrape_scheme(scheme, force_refresh=force_refresh)
                results[scheme.scheme_id] = res
            except Exception as e:
                logger.error(f"Failed to scrape scheme '{scheme.scheme_id}': {e}")
                # Fallback to existing cache if available
                json_file = self.raw_dir / f"{scheme.scheme_id}.json"
                if json_file.exists():
                    logger.info(f"Falling back to existing cache for '{scheme.scheme_id}'")
                    with open(json_file, "r", encoding="utf-8") as f:
                        results[scheme.scheme_id] = json.load(f)

            # Jitter delay between requests if fetching live
            if force_refresh and idx < len(schemes) - 1:
                sleep_time = random.uniform(1.0, 2.0)
                time.sleep(sleep_time)

        return results


if __name__ == "__main__":
    scraper = GrowwScraper()
    logger.info("Starting scrape of all 5 active HDFC Groww scheme URLs...")
    scraped = scraper.scrape_all_active_schemes(force_refresh=True)
    logger.info(f"Completed scrape. Total schemes retrieved: {len(scraped)}")
