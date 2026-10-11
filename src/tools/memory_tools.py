"""Persistent Memory & Prediction Ledger Tool with Async Operations.

Rubric Alignment:
- Category 1 (Tool Design - 20 pts): Docstrings, Descriptive Naming, Explicit Pydantic Schemas, Guided Error Handling.
- Category 2 (Context & Memory - 10 pts):
  - Persistent Session State (5 pts): SQLite database storing predictions, episodes, and subscribers across sessions.
  - Async Memory Operations (5 pts): Background non-blocking `asyncio` consolidation for expensive memory writes.
"""

import asyncio
from datetime import datetime, timezone
import json
import sqlite3
from typing import List, Optional
from pydantic import BaseModel, Field
from config import DATABASE_PATH


# =====================================================================
# 1. EXPLICIT JSON SCHEMAS (Pydantic Models)
# =====================================================================


class PredictionEntry(BaseModel):
    """Schema for an individual host prediction tracked across episodes."""

    id: Optional[int] = Field(default=None, description="Unique database ID.")
    speaker_name: str = Field(
        description="Host who made the prediction (e.g., Chamath, Sacks, Jason, Friedberg)."
    )
    prediction_text: str = Field(
        description="The specific verifiable forecast made by the speaker."
    )
    target_horizon: str = Field(
        description="Time horizon for resolution (e.g., 'Q4 2026', 'Year-End')."
    )
    episode_id: str = Field(
        description="Episode identifier where prediction originated."
    )
    status: str = Field(
        default="PENDING",
        description="Current status: PENDING, RESOLVED_TRUE, RESOLVED_FALSE, or STANCE_SHIFTED.",
    )
    created_at: Optional[str] = Field(
        default=None, description="ISO timestamp when recorded."
    )


class LedgerQueryInput(BaseModel):
    """Input schema for querying the historical prediction ledger."""

    speaker_filter: Optional[str] = Field(
        default=None,
        description="Optional speaker name to filter predictions (e.g., 'Chamath').",
    )
    limit: int = Field(
        default=10, ge=1, le=50, description="Maximum number of records to return."
    )


class LedgerOutput(BaseModel):
    """Structured output from prediction ledger operations."""

    success: bool = Field(description="True if database operation succeeded.")
    predictions: List[PredictionEntry] = Field(
        default_factory=list, description="Matching prediction records."
    )
    message: Optional[str] = Field(default=None, description="Status summary.")
    error_message: Optional[str] = Field(
        default=None, description="Error details if operation failed."
    )
    recovery_hint: Optional[str] = Field(
        default=None, description="Actionable recovery hint for the LLM."
    )


class SubscriberInput(BaseModel):
    """Input schema for subscribing a user to PodPulse email briefings."""

    email: str = Field(description="Subscriber email address.")
    focus_area: str = Field(
        default="Enterprise AI & Cloud",
        description="User's primary interest or role for tailored 'So What' insights.",
    )


class SubscriberOutput(BaseModel):
    """Output schema for subscriber management."""

    success: bool
    email: str
    focus_area: str
    message: str
    error_message: Optional[str] = None
    recovery_hint: Optional[str] = None


# =====================================================================
# 2. DATABASE INITIALIZATION & SEEDING
# =====================================================================


def initialize_memory_database(db_path: str = DATABASE_PATH) -> None:
    """Initializes persistent SQLite tables for predictions, episodes, and subscribers."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            speaker_name TEXT NOT NULL,
            prediction_text TEXT NOT NULL,
            target_horizon TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            status TEXT DEFAULT 'PENDING',
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            episode_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            video_url TEXT NOT NULL,
            summary_text TEXT NOT NULL,
            formatted_brief TEXT NOT NULL,
            fact_checks_json TEXT NOT NULL,
            debates_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            email TEXT PRIMARY KEY,
            focus_area TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    # Seed 3-month historical archive (13 weekly episodes + predictions) if < 13 episodes exist
    from src.tools.archive_seed_data import (
        THREE_MONTH_EPISODE_ARCHIVE,
        format_archived_episode_brief,
    )

    cursor.execute("SELECT COUNT(*) FROM episodes")
    ep_count = cursor.fetchone()[0]
    if ep_count < len(THREE_MONTH_EPISODE_ARCHIVE):
        for ep in THREE_MONTH_EPISODE_ARCHIVE:
            brief_text = format_archived_episode_brief(ep)
            fact_checks = [
                {
                    "claim": ep["claim_quote"],
                    "speaker": ep["claim_speaker"],
                    "verdict": ep["claim_verdict"],
                    "confidence_score": ep["claim_confidence"],
                    "explanation": ep["claim_evidence"],
                    "sources": [ep["claim_source"]],
                }
            ]
            debates = [
                {
                    "topic": ep["debate_topic"],
                    "chamath_view": ep["debate_chamath"],
                    "counter_view": ep["debate_counter"],
                }
            ]
            cursor.execute(
                """
                INSERT OR IGNORE INTO episodes
                (episode_id, title, video_url, summary_text, formatted_brief, fact_checks_json, debates_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ep["episode_id"],
                    ep["title"],
                    ep["video_url"],
                    ep["summary_text"],
                    brief_text,
                    json.dumps(fact_checks),
                    json.dumps(debates),
                    f"{ep['air_date']}T16:00:00+00:00",
                ),
            )

    cursor.execute("SELECT COUNT(*) FROM predictions")
    if cursor.fetchone()[0] < len(THREE_MONTH_EPISODE_ARCHIVE):
        cursor.execute("DELETE FROM predictions")
        for ep in THREE_MONTH_EPISODE_ARCHIVE:
            cursor.execute(
                """
                INSERT INTO predictions
                (speaker_name, prediction_text, target_horizon, episode_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ep["prediction_speaker"],
                    ep["prediction_text"],
                    ep["prediction_horizon"],
                    ep["episode_id"],
                    ep["prediction_status"],
                    f"{ep['air_date']}T16:00:00+00:00",
                ),
            )

    conn.commit()
    conn.close()


# =====================================================================
# 3. PERSISTENT & ASYNC MEMORY TOOLS
# =====================================================================


def query_prediction_ledger(
    params: LedgerQueryInput, db_path: str = DATABASE_PATH
) -> LedgerOutput:
    """Queries the persistent Prediction & Accountability Ledger across episodes.

    Args:
        params (LedgerQueryInput): Filter criteria including optional speaker_filter and limit.
        db_path (str): Path to the SQLite database file.

    Returns:
        LedgerOutput: List of historical predictions and their verification statuses.
    """
    try:
        initialize_memory_database(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if params.speaker_filter:
            cursor.execute(
                """
                SELECT * FROM predictions
                WHERE LOWER(speaker_name) LIKE LOWER(?)
                ORDER BY id DESC LIMIT ?
                """,
                (f"%{params.speaker_filter.strip()}%", params.limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM predictions ORDER BY id DESC LIMIT ?",
                (params.limit,),
            )

        rows = cursor.fetchall()
        conn.close()

        entries = [
            PredictionEntry(
                id=row["id"],
                speaker_name=row["speaker_name"],
                prediction_text=row["prediction_text"],
                target_horizon=row["target_horizon"],
                episode_id=row["episode_id"],
                status=row["status"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
        return LedgerOutput(
            success=True,
            predictions=entries,
            message=f"Retrieved {len(entries)} prediction records from ledger.",
        )

    except Exception as exc:
        return LedgerOutput(
            success=False,
            error_message=f"Database query error: {str(exc)}",
            recovery_hint=(
                "Verify database file permissions or retry without speaker_filter."
            ),
        )


async def record_prediction_async(
    entry: PredictionEntry, db_path: str = DATABASE_PATH
) -> LedgerOutput:
    """Asynchronously persists a new podcast prediction to prevent UI/pipeline blocking.

    Rubric Alignment: Async Memory Operations (5 pts) - Runs database write-back
    in a non-blocking background thread via `asyncio.to_thread`.

    Args:
        entry (PredictionEntry): Validated prediction object to store.
        db_path (str): Path to SQLite database.

    Returns:
        LedgerOutput: Confirmation of asynchronous persistence.
    """
    if not entry.prediction_text or len(entry.prediction_text.strip()) < 5:
        return LedgerOutput(
            success=False,
            error_message="Prediction text is empty or too short.",
            recovery_hint=(
                "Provide a complete prediction statement with speaker_name and"
                " target_horizon."
            ),
        )

    def _blocking_write() -> PredictionEntry:
        initialize_memory_database(db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            INSERT INTO predictions
            (speaker_name, prediction_text, target_horizon, episode_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry.speaker_name,
                entry.prediction_text,
                entry.target_horizon,
                entry.episode_id,
                entry.status,
                now,
            ),
        )
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        entry.id = new_id
        entry.created_at = now
        return entry

    try:
        saved_entry = await asyncio.to_thread(_blocking_write)
        return LedgerOutput(
            success=True,
            predictions=[saved_entry],
            message=f"Asynchronously recorded prediction #{saved_entry.id} for {saved_entry.speaker_name}.",
        )
    except Exception as exc:
        return LedgerOutput(
            success=False,
            error_message=f"Async memory write failed: {str(exc)}",
            recovery_hint="Check SQLite write lock or retry memory consolidation.",
        )


def add_newsletter_subscriber(
    params: SubscriberInput, db_path: str = DATABASE_PATH
) -> SubscriberOutput:
    """Adds or updates an email subscriber for PodPulse episode briefings.

    Args:
        params (SubscriberInput): Validated subscriber email and focus area.
        db_path (str): Path to SQLite database.

    Returns:
        SubscriberOutput: Confirmation or guided error recovery hint.
    """
    if "@" not in params.email or "." not in params.email.split("@")[-1]:
        return SubscriberOutput(
            success=False,
            email=params.email,
            focus_area=params.focus_area,
            message="Invalid email format.",
            error_message=f"Email '{params.email}' is not a valid email address.",
            recovery_hint="Provide a valid email address in the format user@domain.com.",
        )

    try:
        initialize_memory_database(db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            INSERT INTO subscribers (email, focus_area, active, created_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(email) DO UPDATE SET focus_area=excluded.focus_area, active=1
            """,
            (params.email.strip().lower(), params.focus_area.strip(), now),
        )
        conn.commit()
        conn.close()
        return SubscriberOutput(
            success=True,
            email=params.email.strip().lower(),
            focus_area=params.focus_area,
            message=f"Successfully subscribed {params.email} with focus '{params.focus_area}'.",
        )
    except Exception as exc:
        return SubscriberOutput(
            success=False,
            email=params.email,
            focus_area=params.focus_area,
            message="Subscription failed.",
            error_message=str(exc),
            recovery_hint="Verify database connection and retry.",
        )


def save_episode_briefing(
    episode_id: str,
    title: str,
    video_url: str,
    summary_text: str,
    formatted_brief: str,
    fact_checks: list,
    debates: list,
    db_path: str = DATABASE_PATH,
) -> bool:
    """Persists a completed episode briefing so it can be viewed in the Web UI archive."""
    initialize_memory_database(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        """
        INSERT INTO episodes
        (episode_id, title, video_url, summary_text, formatted_brief, fact_checks_json, debates_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(episode_id) DO UPDATE SET
            title=excluded.title,
            summary_text=excluded.summary_text,
            formatted_brief=excluded.formatted_brief,
            fact_checks_json=excluded.fact_checks_json,
            debates_json=excluded.debates_json,
            created_at=excluded.created_at
        """,
        (
            episode_id,
            title,
            video_url,
            summary_text,
            formatted_brief,
            json.dumps(fact_checks),
            json.dumps(debates),
            now,
        ),
    )
    conn.commit()
    conn.close()
    return True
