"""
SQLite database for tracking seen jobs and preventing duplicate notifications.
"""

import json
import sqlite3
from datetime import datetime

from config import DATABASE_FILE


def get_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
            job_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT,
            location TEXT,
            apply_url TEXT,
            workplace_type TEXT,
            commitment TEXT,
            tech_stack TEXT,
            salary_min REAL,
            salary_max REAL,
            seniority TEXT,
            published_at TEXT,
            first_seen_at TEXT NOT NULL,
            notified INTEGER DEFAULT 0
        );
        
        CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scraped_at TEXT NOT NULL,
            total_found INTEGER NOT NULL,
            new_jobs INTEGER NOT NULL,
            notified INTEGER DEFAULT 0
        );
        
        CREATE INDEX IF NOT EXISTS idx_seen_jobs_first_seen 
        ON seen_jobs(first_seen_at);
        
        CREATE INDEX IF NOT EXISTS idx_scrape_log_scraped_at 
        ON scrape_log(scraped_at);
    """)
    conn.commit()
    conn.close()


def job_exists(job_id: str) -> bool:
    """Check if a job has already been seen."""
    conn = get_connection()
    cursor = conn.execute("SELECT 1 FROM seen_jobs WHERE job_id = ?", (job_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def insert_job(job: dict) -> bool:
    """Insert a job if it doesn't exist. Returns True if new."""
    if job_exists(job["id"]):
        return False
    
    conn = get_connection()
    conn.execute("""
        INSERT INTO seen_jobs 
        (job_id, title, company, location, apply_url, workplace_type, 
         commitment, tech_stack, salary_min, salary_max, seniority, 
         published_at, first_seen_at, notified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, (
        job["id"],
        job["title"],
        job.get("company"),
        job.get("location"),
        job.get("apply_url"),
        job.get("workplace_type"),
        json.dumps(job.get("commitment", [])),
        json.dumps(job.get("tech", [])),
        job.get("salary_min"),
        job.get("salary_max"),
        job.get("seniority"),
        job.get("published"),
        datetime.utcnow().isoformat(),
    ))
    conn.commit()
    conn.close()
    return True


def mark_notified(job_ids: list[str]):
    """Mark jobs as notified."""
    if not job_ids:
        return
    conn = get_connection()
    placeholders = ",".join("?" * len(job_ids))
    conn.execute(
        f"UPDATE seen_jobs SET notified = 1 WHERE job_id IN ({placeholders})",
        job_ids,
    )
    conn.commit()
    conn.close()


def get_unnotified_jobs() -> list[dict]:
    """Get jobs that haven't been notified yet."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT * FROM seen_jobs WHERE notified = 0 ORDER BY first_seen_at ASC"
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def log_scrape(total_found: int, new_jobs: int, notified: int = 0):
    """Log a scrape event."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO scrape_log (scraped_at, total_found, new_jobs, notified) VALUES (?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), total_found, new_jobs, notified),
    )
    conn.commit()
    conn.close()


def get_stats() -> dict:
    """Get scrape statistics."""
    conn = get_connection()
    
    total_jobs = conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
    notified_jobs = conn.execute("SELECT COUNT(*) FROM seen_jobs WHERE notified = 1").fetchone()[0]
    unnotified_jobs = total_jobs - notified_jobs
    
    last_scrape = conn.execute(
        "SELECT scraped_at, total_found, new_jobs FROM scrape_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    
    conn.close()
    
    return {
        "total_tracked_jobs": total_jobs,
        "notified": notified_jobs,
        "pending_notification": unnotified_jobs,
        "last_scrape": dict(last_scrape) if last_scrape else None,
    }


# Initialize on import
init_db()
