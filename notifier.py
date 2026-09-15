#!/usr/bin/env python3
"""
HiringCafe Job Notifier — Main entry point.

Scrapes HiringCafe for new jobs and sends Telegram notifications.
Runs on a configurable schedule (default: every 7 minutes).

Supports both config.json (local) and environment variables (GitHub Actions).
"""

import json
import logging
import signal
import sys
import time
from datetime import datetime

import schedule

from config import (
    CONFIG_FILE, SENIORITY_KEYWORDS, INTERNSHIP_KEYWORDS,
    MAX_COMPENSATION_LAKHS, load_config, load_api_key, load_preferences,
)
from scraper import fetch_jobs
from telegram_notifier import notify_new_jobs, test_connection, get_chat_id
from database import insert_job, log_scrape, get_stats, mark_notified
from gemini_filter import filter_jobs as gemini_filter_jobs

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("notifier.log"),
    ],
)
logger = logging.getLogger(__name__)


def scrape_and_notify():
    """Main job: scrape HiringCafe and notify about new jobs."""
    config = load_config()
    bot_token = config["telegram_bot_token"]
    chat_ids = config.get("telegram_chat_ids", [])
    custom_url = config.get("hiringcafe_url")
    max_comp = config.get("max_compensation_lakhs", MAX_COMPENSATION_LAKHS)
    gemini_key = load_api_key()

    if not chat_ids:
        logger.warning("No telegram_chat_ids configured — run setup first")
        return

    logger.info("Starting scrape...")

    # Fetch jobs
    jobs = fetch_jobs(custom_url if custom_url else None)

    if not jobs:
        logger.info("No jobs found in this scrape")
        log_scrape(0, 0, 0)
        return

    # Filter for entry-level, no internships, and compensation cap
    filtered = []
    for job in jobs:
        # Seniority check
        seniority = (job.get("seniority") or "").lower()
        if not any(kw in seniority for kw in SENIORITY_KEYWORDS):
            continue

        # Exclude internships
        commitment = " ".join(job.get("commitment", [])).lower()
        title_lower = (job.get("title") or "").lower()
        if any(kw in commitment or kw in title_lower for kw in INTERNSHIP_KEYWORDS):
            logger.info(f"Skipping internship: {job['title']}")
            continue

        # Compensation cap
        salary_max = job.get("salary_max")
        if salary_max and salary_max > max_comp * 100000:
            logger.info(f"Skipping {job['title']} — salary ₹{salary_max/100000:.1f}L > {max_comp}L")
            continue

        filtered.append(job)

    # Gemini AI filtering
    if gemini_key and filtered:
        logger.info("Applying Gemini AI filter...")
        filtered = gemini_filter_jobs(gemini_key, filtered)
        if not filtered:
            logger.info("No jobs matched preferences after Gemini filtering")
            log_scrape(len(jobs), 0, 0)
            return

    # Check for new jobs
    new_jobs = [job for job in filtered if insert_job(job)]

    total_found = len(filtered)
    new_count = len(new_jobs)

    logger.info(f"Scrape complete: {total_found} total, {new_count} new")

    # Send notifications
    notified = 0
    if new_jobs:
        notified = notify_new_jobs(bot_token, chat_ids, new_jobs)
        notified_ids = [j["id"] for j in new_jobs[:notified]]
        mark_notified(notified_ids)

    log_scrape(total_found, new_count, notified)

    stats = get_stats()
    logger.info(f"Stats: {stats['total_tracked_jobs']} tracked, {stats['pending_notification']} pending")


def setup_chat_id():
    """Interactive setup to get chat_id from Telegram."""
    config = load_config()
    bot_token = config["telegram_bot_token"]
    existing_ids = config.get("telegram_chat_ids", [])

    print("\n" + "=" * 60)
    print("  HiringCafe Notifier — Telegram Setup")
    print("=" * 60)
    print(f"\nCurrent destinations: {existing_ids or '(none)'}")
    print("\nTo add a PERSONAL chat: send /start to your bot in Telegram")
    print("To add a GROUP: add bot as admin, send any message")
    print("To add a CHANNEL: add bot as admin, send any message")
    input("\n>>> Press Enter after sending a message... ")

    chat_id = get_chat_id(bot_token)
    if chat_id:
        if chat_id not in existing_ids:
            existing_ids.append(chat_id)
            config["telegram_chat_ids"] = existing_ids
            with open(CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)
            print(f"\n✅ Chat ID added: {chat_id}")
        else:
            print(f"\nℹ️  Chat ID {chat_id} already configured.")

        print(f"\nSending test message to {len(existing_ids)} destination(s)...")
        if test_connection(bot_token, existing_ids):
            print("✅ Test messages sent successfully!")
        else:
            print("❌ Failed to send some test messages")
    else:
        print("\n❌ Could not find chat_id. Make sure you sent a message to the bot.")


def run_scheduler():
    """Run the scheduler loop."""
    config = load_config()
    interval = config.get("scrape_interval_minutes", 7)

    print("\n" + "=" * 60)
    print("  HiringCafe Job Notifier — Running")
    print("=" * 60)
    print(f"  ⏱  Checking every {interval} minutes")
    print("  🎯 Filters: Bengaluru, Entry Level, Software Dev")
    print("  📱 Telegram notifications enabled")
    print("  Press Ctrl+C to stop\n")

    scrape_and_notify()
    schedule.every(interval).minutes.do(scrape_and_notify)

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        print("\n\n🛑 Stopping notifier...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while running:
        schedule.run_pending()
        time.sleep(1)

    print("✅ Notifier stopped.")


def show_stats():
    """Display current statistics."""
    stats = get_stats()
    print("\n" + "=" * 40)
    print("  HiringCafe Notifier — Stats")
    print("=" * 40)
    print(f"  📊 Total tracked jobs: {stats['total_tracked_jobs']}")
    print(f"  ✅ Notified: {stats['notified']}")
    print(f"  ⏳ Pending: {stats['pending_notification']}")
    if stats["last_scrape"]:
        ls = stats["last_scrape"]
        print(f"  🕐 Last scrape: {ls['scraped_at']}")
        print(f"     Found: {ls['total_found']} jobs, {ls['new_jobs']} new")
    print()


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("""
HiringCafe Job Notifier

Usage:
    python notifier.py <command>

Commands:
    setup   Configure Telegram destinations
    run     Start the notification service
    once    Run a single scrape cycle
    stats   Show notification statistics
    test    Test Telegram connection
        """)
        return

    command = sys.argv[1].lower()

    if command == "setup":
        setup_chat_id()
    elif command == "run":
        run_scheduler()
    elif command == "once":
        scrape_and_notify()
    elif command == "stats":
        show_stats()
    elif command == "test":
        config = load_config()
        chat_ids = config.get("telegram_chat_ids", [])
        if chat_ids:
            test_connection(config["telegram_bot_token"], chat_ids)
        else:
            print("❌ No chat_ids configured. Run 'setup' first.")
    else:
        print(f"Unknown command: {command}")
        print("Run 'python notifier.py' for help.")


if __name__ == "__main__":
    main()
