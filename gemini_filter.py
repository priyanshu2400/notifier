"""
Gemini-powered job filter — uses Google's Gemini API to decide if a job
is a good match for the user's preferences.
"""

import json
import logging

import requests

from config import GEMINI_API_URL, load_preferences

logger = logging.getLogger(__name__)


def build_prompt(jobs: list[dict], preferences: str) -> str:
    """Build the Gemini prompt for job filtering."""
    jobs_text = ""
    for i, job in enumerate(jobs, 1):
        tech_str = ", ".join(job.get("tech", [])[:5]) if job.get("tech") else "N/A"
        commitment = ", ".join(job.get("commitment", [])) if job.get("commitment") else "Not specified"
        salary_min = job.get("salary_min")
        salary_max = job.get("salary_max")
        salary = "Not disclosed"
        if salary_min and salary_max:
            salary = f"₹{salary_min/100000:.1f}L - ₹{salary_max/100000:.1f}L/yr"
        elif salary_min:
            salary = f"₹{salary_min/100000:.1f}L+/yr"

        jobs_text += f"""
Job {i}:
- ID: {job.get('id', 'N/A')}
- Title: {job.get('title', 'N/A')}
- Company: {job.get('company', 'N/A')}
- Location: {job.get('location', 'N/A')}
- Workplace: {job.get('workplace_type', 'N/A')}
- Commitment: {commitment}
- Tech Stack: {tech_str}
- Salary: {salary}
- Seniority: {job.get('seniority', 'N/A')}
- Description: {job.get('requirements', 'N/A')[:200]}
"""

    return f"""You are a job-matching assistant. Given the user's preferences below, evaluate each job and determine if it's a GOOD FIT.

## User Preferences
{preferences}

## Jobs to Evaluate
{jobs_text}

## Instructions
For EACH job, respond with a JSON object containing:
- "id": the job ID
- "match": true or false
- "score": 0-100 (how well it matches)
- "reason": brief 1-sentence reason

A job should be a GOOD FIT (match: true) if:
1. It's entry to mid-level (1-3 YOE) — REJECT senior/lead/staff/manager roles AND internships/intern roles
2. It's a software engineering role — Backend, Full Stack, SRE, DevOps, Platform, Cloud, Infrastructure, or any SDE role
3. The tech stack includes at least one of: Go, Python, Java, JavaScript, Docker, Kubernetes, Linux, cloud, databases, React, Node.js
4. Location is ACCEPTABLE if: (a) in India (Bangalore preferred), OR (b) Fully Remote from anywhere in the world. REJECT only if it's onsite AND outside India.
5. It's NOT a pure hardware, embedded, firmware, mechanical, civil, electrical, or chip design role
6. It's NOT a pure frontend-only, data analyst, marketing, or sales role
7. It's NOT an internship — the user has 1+ years experience and is overqualified for internships
8. Roles requiring Java, JavaScript, TypeScript, C++, Go, Python are ACCEPTABLE — even if C# or .NET is also mentioned alongside them
9. REJECT only roles where C# or .NET is the PRIMARY/sole required language (no acceptable alternatives listed)

Respond ONLY with a valid JSON array. No markdown, no explanation outside the JSON.

Example format:
[
  {{"id": "job_123", "match": true, "score": 85, "reason": "Go backend role at a cloud company in Bangalore — strong match"}},
  {{"id": "job_456", "match": true, "score": 70, "reason": "Software Engineer requiring Java/C++/C# — Java and C++ are acceptable"}},
  {{"id": "job_789", "match": false, "score": 10, "reason": "Pure C#/.NET role with no acceptable alternatives — not in user's tech stack"}}
]"""


def call_gemini(api_key: str, prompt: str) -> str | None:
    """Call the Gemini API and return the response text."""
    url = f"{GEMINI_API_URL}?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
        },
    }

    for attempt in range(3):
        try:
            logger.info(f"Gemini API call attempt {attempt + 1}/3 (timeout=120s)...")
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()

            # Extract text from Gemini response
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    logger.info("Gemini responded successfully")
                    return parts[0].get("text", "")
            logger.error("Empty Gemini response")
            return None
        except requests.exceptions.ReadTimeout:
            logger.warning(f"Gemini API timed out on attempt {attempt + 1}/3")
            if attempt < 2:
                logger.info("Retrying in 5 seconds...")
                import time
                time.sleep(5)
        except requests.RequestException as e:
            logger.error(f"Gemini API request failed: {e}")
            if attempt < 2:
                logger.info("Retrying in 5 seconds...")
                import time
                time.sleep(5)
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to parse Gemini response: {e}")
            return None
    logger.error("All 3 Gemini API attempts failed")
    return None


def parse_gemini_response(response_text: str) -> list[dict]:
    """Parse the Gemini JSON response."""
    # Clean up the response — remove markdown code fences if present
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]  # Remove first line
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    try:
        results = json.loads(text)
        if isinstance(results, list):
            return results
        logger.error("Gemini returned non-array JSON")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini JSON: {e}\nRaw: {text[:500]}")
        return []


def filter_jobs(api_key: str, jobs: list[dict]) -> list[dict]:
    """
    Filter jobs using Gemini. Returns only jobs that match the user's preferences.
    Each returned job gets an added 'gemini_score' and 'gemini_reason' field.
    """
    if not jobs:
        return []

    preferences = load_preferences()
    if not preferences:
        logger.warning("No preferences loaded — returning all jobs unfiltered")
        return jobs

    logger.info(f"Sending {len(jobs)} jobs to Gemini for filtering...")

    prompt = build_prompt(jobs, preferences)
    response_text = call_gemini(api_key, prompt)

    if not response_text:
        logger.warning("Gemini returned no response — returning all jobs unfiltered")
        return jobs

    results = parse_gemini_response(response_text)
    if not results:
        logger.warning("Could not parse Gemini results — returning all jobs unfiltered")
        return jobs

    # Build lookup by job ID
    result_map = {r["id"]: r for r in results if "id" in r}

    matched_jobs = []
    rejected_jobs = []
    for job in jobs:
        result = result_map.get(job["id"])
        if result and result.get("match", False):
            job["gemini_score"] = result.get("score", 0)
            job["gemini_reason"] = result.get("reason", "")
            matched_jobs.append(job)
        elif result and not result.get("match", False):
            rejected_jobs.append((job, result))
        elif not result:
            # If Gemini didn't return a result for this job, include it with a note
            logger.warning(f"No Gemini result for job {job.get('id')} — including with default score")
            job["gemini_score"] = 50
            job["gemini_reason"] = "Not evaluated by Gemini"
            matched_jobs.append(job)

    logger.info(
        f"Gemini filtered: {len(matched_jobs)}/{len(jobs)} jobs match preferences"
    )

    if rejected_jobs:
        logger.info("   Rejected by Gemini:")
        for job, result in rejected_jobs:
            score = result.get("score", "?")
            reason = result.get("reason", "N/A")
            logger.info(f"   ❌ [{score}/100] {job['title']} @ {job['company']}")
            logger.info(f"      💬 {reason}")

    return matched_jobs


if __name__ == "__main__":
    import sys
    from config import load_api_key

    logging.basicConfig(level=logging.INFO)

    api_key = load_api_key()
    if not api_key:
        print("❌ No API key found. Set GEMINI_API_KEY env var or create api-key.txt")
        sys.exit(1)

    # Test with sample jobs
    from scraper import fetch_jobs
    jobs = fetch_jobs()
    if not jobs:
        print("No jobs fetched")
        sys.exit(1)

    matched = filter_jobs(api_key, jobs)
    print(f"\n✅ {len(matched)}/{len(jobs)} jobs matched your preferences:\n")
    for job in matched:
        score = job.get("gemini_score", "?")
        reason = job.get("gemini_reason", "")
        print(f"  [{score}/100] {job['title']} @ {job['company']}")
        print(f"          📍 {job['location']} | {job['workplace_type']}")
        print(f"          💬 {reason}")
        print()
