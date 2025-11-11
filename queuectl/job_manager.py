"""Job management and execution logic"""

import subprocess
import uuid
from datetime import datetime, timedelta
from typing import Optional
from .models import Job, JobState, QueueConfig
from .storage import Storage


class JobManager:
    def __init__(self, storage: Storage):
        self.storage = storage

    def enqueue_job(self, command: str, job_id: Optional[str] = None, max_retries: Optional[int] = None) -> Job:
        """Add a new job to the queue"""
        config = self.storage.get_config()
        
        job = Job(
            id=job_id or str(uuid.uuid4()),
            command=command,
            state=JobState.PENDING,
            attempts=0,
            max_retries=max_retries or config.max_retries,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        self.storage.save_job(job)
        return job

    def execute_job(self, job: Job) -> bool:
        """Execute a job and return success status"""
        # Update job state to processing
        job.state = JobState.PROCESSING
        job.updated_at = datetime.now()
        self.storage.save_job(job)

        try:
            # Execute the command
            result = subprocess.run(
                job.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            job.output = result.stdout
            job.updated_at = datetime.now()
            
            if result.returncode == 0:
                # Success
                job.state = JobState.COMPLETED
                self.storage.save_job(job)
                return True
            else:
                # Command failed
                job.error_message = result.stderr or f"Command exited with code {result.returncode}"
                return self._handle_job_failure(job)
                
        except subprocess.TimeoutExpired:
            job.error_message = "Job execution timed out"
            return self._handle_job_failure(job)
        except Exception as e:
            job.error_message = f"Execution error: {str(e)}"
            return self._handle_job_failure(job)

    def _handle_job_failure(self, job: Job) -> bool:
        """Handle job failure with retry logic"""
        job.attempts += 1
        job.updated_at = datetime.now()
        
        if job.attempts >= job.max_retries:
            # Move to dead letter queue
            job.state = JobState.DEAD
            job.next_retry_at = None
        else:
            # Schedule retry with exponential backoff
            config = self.storage.get_config()
            delay_seconds = config.backoff_base ** job.attempts
            job.next_retry_at = datetime.now() + timedelta(seconds=delay_seconds)
            job.state = JobState.FAILED
        
        self.storage.save_job(job)
        return False

    def retry_job(self, job_id: str) -> bool:
        """Retry a job from DLQ"""
        job = self.storage.get_job(job_id)
        if not job:
            return False
        
        if job.state == JobState.DEAD:
            job.state = JobState.PENDING
            job.attempts = 0
            job.error_message = None
            job.next_retry_at = None
            job.updated_at = datetime.now()
            self.storage.save_job(job)
            return True
        
        return False

    def get_next_job(self) -> Optional[Job]:
        """Get the next job to process"""
        return self.storage.get_next_pending_job()