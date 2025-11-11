"""Worker process implementation"""

import os
import signal
import time
import threading
from datetime import datetime
from typing import Dict, List
from .models import WorkerInfo
from .job_manager import JobManager
from .storage import Storage


class Worker:
    def __init__(self, worker_id: str, storage: Storage, job_manager: JobManager):
        self.worker_id = worker_id
        self.storage = storage
        self.job_manager = job_manager
        self.running = False
        self.current_job_id = None
        self.thread = None

    def start(self):
        """Start the worker in a separate thread"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._work_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the worker gracefully"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)

    def _work_loop(self):
        """Main worker loop"""
        config = self.storage.get_config()
        
        while self.running:
            try:
                # Get next job
                job = self.job_manager.get_next_job()
                
                if job:
                    self.current_job_id = job.id
                    print(f"Worker {self.worker_id} processing job {job.id}: {job.command}")
                    
                    # Execute job
                    success = self.job_manager.execute_job(job)
                    
                    if success:
                        print(f"Worker {self.worker_id} completed job {job.id}")
                    else:
                        print(f"Worker {self.worker_id} failed job {job.id} (attempt {job.attempts})")
                    
                    self.current_job_id = None
                else:
                    # No jobs available, sleep
                    time.sleep(config.worker_poll_interval)
                    
            except Exception as e:
                print(f"Worker {self.worker_id} error: {e}")
                time.sleep(1)


class WorkerManager:
    def __init__(self, storage: Storage, job_manager: JobManager):
        self.storage = storage
        self.job_manager = job_manager
        self.workers: Dict[str, Worker] = {}
        self.worker_processes: Dict[str, WorkerInfo] = {}

    def start_workers(self, count: int) -> List[str]:
        """Start multiple workers"""
        started_workers = []
        
        for i in range(count):
            worker_id = f"worker-{len(self.workers) + 1}"
            worker = Worker(worker_id, self.storage, self.job_manager)
            
            worker.start()
            self.workers[worker_id] = worker
            
            # Track worker info
            worker_info = WorkerInfo(
                id=worker_id,
                pid=os.getpid(),  # In threading model, all workers share same PID
                status="running",
                current_job_id=None,
                started_at=datetime.now()
            )
            self.worker_processes[worker_id] = worker_info
            started_workers.append(worker_id)
            
            print(f"Started worker {worker_id}")
        
        return started_workers

    def stop_workers(self) -> int:
        """Stop all workers gracefully"""
        stopped_count = 0
        
        for worker_id, worker in self.workers.items():
            print(f"Stopping worker {worker_id}...")
            worker.stop()
            
            if worker_id in self.worker_processes:
                self.worker_processes[worker_id].status = "stopped"
            
            stopped_count += 1
        
        self.workers.clear()
        print(f"Stopped {stopped_count} workers")
        return stopped_count

    def get_active_workers(self) -> List[WorkerInfo]:
        """Get list of active workers"""
        active_workers = []
        
        for worker_id, worker_info in self.worker_processes.items():
            if worker_id in self.workers and self.workers[worker_id].running:
                # Update current job info
                worker_info.current_job_id = self.workers[worker_id].current_job_id
                active_workers.append(worker_info)
        
        return active_workers

    def get_worker_count(self) -> int:
        """Get number of active workers"""
        return len([w for w in self.workers.values() if w.running])