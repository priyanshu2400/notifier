"""
Telegram notification sender — sends job alerts via Bot API.
"""

import logging
from urllib.parse import quote

import requests

from config import TELEGRAM_API

logger = logging.getLogger(__name__)


def format_job_message(job: dict) -> str:
    """Format a single job into a Telegram-friendly message."""
    # Tech stack
    tech = ", ".join(job.get("tech", [])[:5]) if job.get("tech") else "N/A"
    
    # Salary
    salary_min = job.get("salary_min")
    salary_max = job.get("salary_max")
    if salary_min and salary_max:
        salary = f"💰 ₹{salary_min/100000:.1f}L - ₹{salary_max/100000:.1f}L/yr"
    elif salary_min:
        salary = f"💰 ₹{salary_min/100000:.1f}L+/yr"
    elif salary_max:
        salary = f"💰 Up to ₹{salary_max/100000:.1f}L/yr"
    else:
        salary = "💰 Not disclosed"
    
    # Commitment
    commitment = ", ".join(job.get("commitment", [])) if job.get("commitment") else "Not specified"
    
    # Build HiringCafe search URL for this job
    search_query = f"{job.get('title', '')} {job.get('company', '')}"
    hiringcafe_search = f"https://hiringcafe.com/?searchState=%7B%22keyword%22%3A%22{quote(search_query)}%22%7D"
    
    # Gemini match score
    gemini_score = job.get("gemini_score")
    gemini_reason = job.get("gemini_reason", "")
    
    lines = [
        f"🎯 <b>{job.get('title', 'New Job')}</b>",
        f"🏢 {job.get('company', 'Unknown')}",
        f"📍 {job.get('location', 'Not specified')}",
        f"🏠 {job.get('workplace_type', 'N/A')} • {commitment}",
        salary,
        f"🛠 <i>{tech}</i>",
        f"📊 Seniority: {job.get('seniority', 'N/A')}",
    ]
    
    if gemini_score is not None:
        # Add match score bar
        bar_len = int(gemini_score / 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        lines.append(f"\n🤖 Match: [{bar}] {gemini_score}/100")
        if gemini_reason:
            lines.append(f"💬 {gemini_reason}")
    
    lines.extend([
        "",
        f'🔗 <a href="{job.get("apply_url", "#")}">Apply Now</a>',
        f'📋 <a href="{hiringcafe_search}">Search on HiringCafe</a>',
    ])
    
    return "\n".join(lines)


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
) -> bool:
    """Send a message via Telegram Bot API."""
    url = f"{TELEGRAM_API}/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        result = response.json()
        
        if not result.get("ok"):
            logger.error(f"Telegram API error: {result.get('description', 'Unknown error')}")
            return False
        
        logger.info(f"Message sent to chat {chat_id}")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def notify_new_jobs(bot_token: str, chat_ids: str | list[str], jobs: list[dict]) -> int:
    """Send notifications for new jobs to one or more chat IDs. Returns count of successfully sent."""
    if not jobs:
        logger.info("No new jobs to notify")
        return 0
    
    # Normalize to list
    if isinstance(chat_ids, str):
        chat_ids = [chat_ids]
    
    sent = 0
    for chat_id in chat_ids:
        # Send summary header
        header = f"\U0001f514 <b>{len(jobs)} New Job{'s' if len(jobs) != 1 else ''} Found!</b>\n"
        header += f"\U0001f4cb From HiringCafe \u2014 Bengaluru & Asia"
        send_telegram_message(bot_token, chat_id, header)
        
        for job in jobs:
            message = format_job_message(job)
            if send_telegram_message(bot_token, chat_id, message):
                sent += 1
    
    logger.info(f"Sent {sent}/{len(jobs) * len(chat_ids)} job notifications across {len(chat_ids)} destination(s)")
    return sent // len(chat_ids) if chat_ids else 0


def test_connection(bot_token: str, chat_ids: str | list[str]) -> bool:
    """Test the Telegram bot connection and send test message to all destinations."""
    if isinstance(chat_ids, str):
        chat_ids = [chat_ids]
    
    url = f"{TELEGRAM_API}/bot{bot_token}/getMe"
    try:
        response = requests.get(url, timeout=30)
        data = response.json()
        if data.get("ok"):
            bot_name = data["result"].get("username", "unknown")
            logger.info(f"Bot connected: @{bot_name}")
            
            test_msg = "\u2705 <b>HiringCafe Notifier</b>\n\nBot is connected and ready to send job alerts!"
            all_ok = True
            for cid in chat_ids:
                if not send_telegram_message(bot_token, cid, test_msg):
                    all_ok = False
            return all_ok
        else:
            logger.error(f"Bot API error: {data.get('description')}")
            return False
    except requests.RequestException as e:
        logger.error(f"Connection test failed: {e}")
        return False


def get_chat_id(bot_token: str) -> str | None:
    """Get the chat_id by waiting for a message. Used for initial setup."""
    url = f"{TELEGRAM_API}/bot{bot_token}/getUpdates"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        if data.get("ok") and data.get("result"):
            # Get the latest message
            update = data["result"][-1]
            chat = update.get("message", {}).get("chat", {})
            chat_id = str(chat.get("id", ""))
            if chat_id:
                logger.info(f"Found chat_id: {chat_id} (from @{chat.get('username', 'unknown')})")
                return chat_id
    except requests.RequestException as e:
        logger.error(f"Failed to get updates: {e}")
    return None
