"""Storage layer for QueueCTL using SQLite"""

import sqlite3
import json
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from .models import Job, JobState, QueueConfig, QueueStatus


class Storage:
    def __init__(self, db_path: str = "queuectl.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    command TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_retry_at TEXT,
                    error_message TEXT,
                    output TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            
            # Initialize default config if not exists
            cursor = conn.execute("SELECT COUNT(*) FROM config")
            if cursor.fetchone()[0] == 0:
                default_config = QueueConfig()
                self.save_config(default_config)

    def save_job(self, job: Job):
        """Save or update a job"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO jobs 
                (id, command, state, attempts, max_retries, created_at, updated_at, 
                 next_retry_at, error_message, output)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.id, job.command, job.state.value, job.attempts, job.max_retries,
                job.created_at.isoformat(), job.updated_at.isoformat(),
                job.next_retry_at.isoformat() if job.next_retry_at else None,
                job.error_message, job.output
            ))

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_job(row)
        return None

    def get_jobs_by_state(self, state: JobState) -> List[Job]:
        """Get all jobs with a specific state"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM jobs WHERE state = ?", (state.value,))
            return [self._row_to_job(row) for row in cursor.fetchall()]

    def get_next_pending_job(self) -> Optional[Job]:
        """Get the next pending job for processing"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM jobs 
                WHERE state = 'pending' 
                   OR (state = 'failed' AND next_retry_at <= ?)
                ORDER BY created_at ASC 
                LIMIT 1
            """, (datetime.now().isoformat(),))
            row = cursor.fetchone()
            if row:
                return self._row_to_job(row)
        return None

    def get_queue_status(self) -> QueueStatus:
        """Get current queue status"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT state, COUNT(*) as count 
                FROM jobs 
                GROUP BY state
            """)
            counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            return QueueStatus(
                pending=counts.get('pending', 0),
                processing=counts.get('processing', 0),
                completed=counts.get('completed', 0),
                failed=counts.get('failed', 0),
                dead=counts.get('dead', 0),
                active_workers=0  # Will be updated by worker manager
            )

    def save_config(self, config: QueueConfig):
        """Save configuration"""
        with sqlite3.connect(self.db_path) as conn:
            config_json = json.dumps(config.to_dict())
            conn.execute("""
                INSERT OR REPLACE INTO config (key, value) 
                VALUES ('queue_config', ?)
            """, (config_json,))

    def get_config(self) -> QueueConfig:
        """Get configuration"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT value FROM config WHERE key = 'queue_config'")
            row = cursor.fetchone()
            if row:
                config_data = json.loads(row[0])
                return QueueConfig.from_dict(config_data)
        return QueueConfig()  # Return default config

    def _row_to_job(self, row) -> Job:
        """Convert database row to Job object"""
        return Job(
            id=row['id'],
            command=row['command'],
            state=JobState(row['state']),
            attempts=row['attempts'],
            max_retries=row['max_retries'],
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
            next_retry_at=datetime.fromisoformat(row['next_retry_at']) if row['next_retry_at'] else None,
            error_message=row['error_message'],
            output=row['output']
        )