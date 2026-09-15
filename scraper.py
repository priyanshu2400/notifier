"""
HiringCafe job scraper — uses Playwright to render the page and extract __NEXT_DATA__.
"""

import json
import logging
from urllib.parse import quote

from config import HIRINGCAFE_BASE_URL, DEFAULT_SEARCH_STATE

logger = logging.getLogger(__name__)


def build_url(search_state: dict | None = None) -> str:
    """Build the HiringCafe search URL from search state."""
    state = search_state or DEFAULT_SEARCH_STATE
    encoded = quote(json.dumps(state, separators=(",", ":")))
    return f"{HIRINGCAFE_BASE_URL}?searchState={encoded}"


def parse_job(hit: dict) -> dict:
    """Parse a single job hit into a clean dict."""
    info = hit.get("job_information", {})
    proc = hit.get("v5_processed_job_data", {})
    company_data = hit.get("enriched_company_data", {})

    company = (
        company_data.get("company_name")
        or hit.get("attributed_org", {}).get("name")
        or hit.get("attributed_org_card", {}).get("company_name")
        or "Unknown"
    )

    return {
        "id": hit.get("id", ""),
        "title": info.get("title") or info.get("job_title_raw", "Unknown"),
        "company": company,
        "company_description": (company_data.get("short_description", "") or "")[:200],
        "location": proc.get("formatted_workplace_location", "Not specified"),
        "apply_url": hit.get("apply_url", ""),
        "workplace_type": proc.get("workplace_type", "Not specified"),
        "commitment": proc.get("commitment", []),
        "tech": proc.get("technical_tools", []),
        "salary_min": proc.get("yearly_min_compensation"),
        "salary_max": proc.get("yearly_max_compensation"),
        "seniority": proc.get("seniority_level", "Not specified"),
        "published": proc.get("estimated_publish_date", ""),
        "department": proc.get("job_category", ""),
        "requirements": (proc.get("requirements_summary", "") or "")[:300],
    }


def fetch_jobs(custom_url: str | None = None) -> list[dict]:
    """Fetch jobs from HiringCafe using a headless browser."""
    from playwright.sync_api import sync_playwright

    url = custom_url or build_url()
    logger.info(f"Fetching jobs from: {url[:100]}...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            next_data = page.evaluate("""() => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? el.textContent : null;
            }""")

            browser.close()

        if not next_data:
            logger.error("No __NEXT_DATA__ found on page")
            return []

        data = json.loads(next_data)
        hits = data.get("props", {}).get("pageProps", {}).get("ssrHits", [])
        total = data.get("props", {}).get("pageProps", {}).get("ssrTotalCount", 0)

        logger.info(f"Found {len(hits)} jobs (total available: {total})")
        return [parse_job(h) for h in hits if h.get("id")]

    except Exception as e:
        logger.error(f"Scrape failed: {e}")
        return []

            browser.close()

        if not next_data_str:
            logger.error("Could not find __NEXT_DATA__ in rendered page")
            return []

        data = json.loads(next_data_str)
    except Exception as e:
        logger.error(f"Failed to fetch/render page: {e}")
        return []

    page_props = data.get("props", {}).get("pageProps", {})
    hits = page_props.get("ssrHits", [])
    total_count = page_props.get("ssrTotalCount", 0)

    logger.info(f"Found {len(hits)} jobs (total: {total_count})")

    jobs = []
    for hit in hits:
        try:
            job = parse_job(hit)
            if job["id"] and job["title"]:
                jobs.append(job)
        except Exception as e:
            logger.warning(f"Failed to parse job: {e}")
            continue

    return jobs


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    jobs = fetch_jobs()
    print(f"\nFetched {len(jobs)} jobs:\n")
    for job in jobs:
        print(f"• {job['title']} @ {job['company']}")
        print(f"  📍 {job['location']} | {job['workplace_type']}")
        print(f"  🔗 {job['apply_url']}")
        print()
