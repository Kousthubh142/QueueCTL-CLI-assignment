"""Data models for QueueCTL"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum
import json


class JobState(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"


@dataclass
class Job:
    id: str
    command: str
    state: JobState
    attempts: int
    max_retries: int
    created_at: datetime
    updated_at: datetime
    next_retry_at: Optional[datetime] = None
    error_message: Optional[str] = None
    output: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for JSON serialization"""
        data = asdict(self)
        data['state'] = self.state.value
        data['created_at'] = self.created_at.isoformat()
        data['updated_at'] = self.updated_at.isoformat()
        if self.next_retry_at:
            data['next_retry_at'] = self.next_retry_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Job':
        """Create job from dictionary"""
        data['state'] = JobState(data['state'])
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        if data.get('next_retry_at'):
            data['next_retry_at'] = datetime.fromisoformat(data['next_retry_at'])
        return cls(**data)


@dataclass
class WorkerInfo:
    id: str
    pid: int
    status: str
    current_job_id: Optional[str]
    started_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert worker info to dictionary"""
        data = asdict(self)
        data['started_at'] = self.started_at.isoformat()
        return data


@dataclass
class QueueConfig:
    max_retries: int = 3
    backoff_base: int = 2
    worker_poll_interval: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QueueConfig':
        return cls(**data)


@dataclass
class QueueStatus:
    pending: int
    processing: int
    completed: int
    failed: int
    dead: int
    active_workers: int