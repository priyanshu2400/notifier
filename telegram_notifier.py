"""
Telegram notification sender — sends job alerts via Bot API.
"""

import logging
from urllib.parse import quote

import requests

from config import TELEGRAM_API

logger = logging.getLogger(__name__)


def format_job_compact(job: dict, index: int) -> str:
    """Format a single job into a compact Telegram-friendly block."""
    tech = ", ".join(job.get("tech", [])[:4]) if job.get("tech") else "N/A"
    
    salary_min = job.get("salary_min")
    salary_max = job.get("salary_max")
    if salary_min and salary_max:
        salary = f"₹{salary_min/100000:.1f}-{salary_max/100000:.1f}L"
    elif salary_min:
        salary = f"₹{salary_min/100000:.1f}L+"
    else:
        salary = "Not disclosed"
    
    gemini_score = job.get("gemini_score", 0)
    gemini_reason = job.get("gemini_reason", "")
    
    score_emoji = "🟢" if gemini_score >= 80 else "🟡" if gemini_score >= 60 else "⚪"
    
    lines = [
        f"{score_emoji} <b>{index}. {job.get('title', 'New Job')}</b>",
        f"🏢 {job.get('company', 'Unknown')} | 📍 {job.get('location', 'N/A')}",
        f"🏠 {job.get('workplace_type', 'N/A')} | 💰 {salary} | 📊 {job.get('seniority', 'N/A')}",
        f"🛠 <i>{tech}</i>",
        f"🤖 {gemini_score}/100 — {gemini_reason[:80]}",
        f'🔗 <a href="{job.get("apply_url", "#")}">Apply</a>',
    ]
    
    return "\n".join(lines)


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
) -> bool:
    """Send a message via Telegram Bot API with retry on rate limit."""
    import time
    url = f"{TELEGRAM_API}/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=30)
            result = response.json()
            
            if result.get("ok"):
                logger.info(f"Message sent to chat {chat_id}")
                return True
            
            desc = result.get('description', '')
            if 'Too Many Requests' in desc:
                retry_after = int(''.join(filter(str.isdigit, desc.split('retry after')[-1])) or '5')
                logger.warning(f"Rate limited, waiting {retry_after}s...")
                time.sleep(retry_after + 1)
                continue
            
            logger.error(f"Telegram API error: {desc}")
            return False
        except requests.RequestException as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    logger.error("Failed to send after 3 retries")
    return False


def format_all_jobs(jobs: list[dict]) -> list[str]:
    """Format all jobs into compact message(s). Splits at Telegram's4096 char limit."""
    TELEGRAM_MAX =4096
    
    # Sort by score descending
    sorted_jobs = sorted(jobs, key=lambda j: j.get("gemini_score", 0), reverse=True)
    
    header = f"🔔 <b>{len(sorted_jobs)} New Job{'s' if len(sorted_jobs) != 1 else ''} Found!</b>\n"
    header += f"📋 From HiringCafe — Bengaluru & Asia\n"
    header += f"🤖 Sorted by match score (highest first)\n\n"
    
    messages = []
    current = header
    
    for i, job in enumerate(sorted_jobs, 1):
        job_text = format_job_compact(job, i)
        candidate = current + job_text + "\n\n"
        
        if len(candidate) > TELEGRAM_MAX and current != header:
            messages.append(current)
            current = f"🔔 <b>Continued ({i}-{len(sorted_jobs)})...</b>\n\n"
            current += job_text + "\n\n"
        else:
            current = candidate
    
    if current.strip():
        messages.append(current)
    
    return messages


def notify_new_jobs(bot_token: str, chat_ids: str | list[str], jobs: list[dict]) -> int:
    """Send notifications for new jobs to one or more chat IDs. Returns count of messages sent."""
    import time
    
    if not jobs:
        logger.info("No new jobs to notify")
        return 0
    
    # Normalize to list
    if isinstance(chat_ids, str):
        chat_ids = [chat_ids]
    
    messages = format_all_jobs(jobs)
    logger.info(f"Formatted {len(jobs)} jobs into {len(messages)} message(s) for {len(chat_ids)} destination(s)")
    
    sent = 0
    for chat_id in chat_ids:
        for i, msg in enumerate(messages, 1):
            if send_telegram_message(bot_token, chat_id, msg):
                sent += 1
            time.sleep(1)  # Rate limit: max ~1 msg/sec per chat
    
    logger.info(f"Sent {sent} messages across {len(chat_ids)} destination(s)")
    return sent


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
