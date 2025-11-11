"""CLI interface for QueueCTL"""

import click
import json
import sys
import signal
import time
from datetime import datetime
from .models import JobState, QueueConfig
from .storage import Storage
from .job_manager import JobManager
from .worker import WorkerManager


# Global instances
storage = Storage()
job_manager = JobManager(storage)
worker_manager = WorkerManager(storage, job_manager)


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """QueueCTL - CLI-based background job queue system"""
    pass


@cli.command()
@click.argument('job_data')
def enqueue(job_data):
    """Add a new job to the queue
    
    Example: queuectl enqueue '{"id":"job1","command":"sleep 2"}'
    """
    try:
        data = json.loads(job_data)
        command = data.get('command')
        job_id = data.get('id')
        max_retries = data.get('max_retries')
        
        if not command:
            click.echo("Error: 'command' field is required", err=True)
            sys.exit(1)
        
        job = job_manager.enqueue_job(command, job_id, max_retries)
        click.echo(f"Enqueued job {job.id}: {job.command}")
        
    except json.JSONDecodeError:
        click.echo("Error: Invalid JSON format", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.group()
def worker():
    """Worker management commands"""
    pass


@worker.command()
@click.option('--count', '-c', default=1, help='Number of workers to start')
def start(count):
    """Start one or more workers"""
    try:
        def signal_handler(signum, frame):
            click.echo("\nShutting down workers...")
            worker_manager.stop_workers()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        started_workers = worker_manager.start_workers(count)
        click.echo(f"Started {len(started_workers)} workers")
        
        # Keep main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            click.echo("\nShutting down workers...")
            worker_manager.stop_workers()
            
    except Exception as e:
        click.echo(f"Error starting workers: {e}", err=True)
        sys.exit(1)


@worker.command()
def stop():
    """Stop running workers gracefully"""
    stopped_count = worker_manager.stop_workers()
    click.echo(f"Stopped {stopped_count} workers")


@cli.command()
def status():
    """Show summary of all job states & active workers"""
    try:
        queue_status = storage.get_queue_status()
        active_workers = worker_manager.get_active_workers()
        
        click.echo("=== Queue Status ===")
        click.echo(f"Pending:    {queue_status.pending}")
        click.echo(f"Processing: {queue_status.processing}")
        click.echo(f"Completed:  {queue_status.completed}")
        click.echo(f"Failed:     {queue_status.failed}")
        click.echo(f"Dead:       {queue_status.dead}")
        click.echo(f"Active Workers: {worker_manager.get_worker_count()}")
        
        if active_workers:
            click.echo("\n=== Active Workers ===")
            for worker in active_workers:
                current_job = f" (processing {worker.current_job_id})" if worker.current_job_id else ""
                click.echo(f"{worker.id}: {worker.status}{current_job}")
                
    except Exception as e:
        click.echo(f"Error getting status: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--state', help='Filter jobs by state (pending, processing, completed, failed, dead)')
@click.option('--limit', default=10, help='Maximum number of jobs to show')
def list(state, limit):
    """List jobs by state"""
    try:
        if state:
            try:
                job_state = JobState(state)
                jobs = storage.get_jobs_by_state(job_state)
            except ValueError:
                click.echo(f"Error: Invalid state '{state}'. Valid states: pending, processing, completed, failed, dead", err=True)
                sys.exit(1)
        else:
            # Get all jobs (we'll need to implement this)
            jobs = []
            for state_enum in JobState:
                jobs.extend(storage.get_jobs_by_state(state_enum))
        
        # Limit results
        jobs = jobs[:limit]
        
        if not jobs:
            click.echo("No jobs found")
            return
        
        click.echo(f"=== Jobs ({len(jobs)} found) ===")
        for job in jobs:
            status_info = f"attempts: {job.attempts}/{job.max_retries}"
            if job.error_message:
                status_info += f", error: {job.error_message[:50]}..."
            
            click.echo(f"{job.id}: {job.command} [{job.state.value}] ({status_info})")
            
    except Exception as e:
        click.echo(f"Error listing jobs: {e}", err=True)
        sys.exit(1)


@cli.group()
def dlq():
    """Dead Letter Queue management"""
    pass


@dlq.command()
@click.option('--limit', default=10, help='Maximum number of jobs to show')
def list(limit):
    """View jobs in Dead Letter Queue"""
    try:
        dead_jobs = storage.get_jobs_by_state(JobState.DEAD)[:limit]
        
        if not dead_jobs:
            click.echo("No jobs in Dead Letter Queue")
            return
        
        click.echo(f"=== Dead Letter Queue ({len(dead_jobs)} jobs) ===")
        for job in dead_jobs:
            click.echo(f"{job.id}: {job.command}")
            click.echo(f"  Failed after {job.attempts} attempts")
            if job.error_message:
                click.echo(f"  Last error: {job.error_message}")
            click.echo()
            
    except Exception as e:
        click.echo(f"Error listing DLQ: {e}", err=True)
        sys.exit(1)


@dlq.command()
@click.argument('job_id')
def retry(job_id):
    """Retry a job from Dead Letter Queue"""
    try:
        if job_manager.retry_job(job_id):
            click.echo(f"Job {job_id} moved back to pending queue")
        else:
            click.echo(f"Job {job_id} not found in Dead Letter Queue", err=True)
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"Error retrying job: {e}", err=True)
        sys.exit(1)


@cli.group()
def config():
    """Configuration management"""
    pass


@config.command()
@click.argument('key')
@click.argument('value', type=int)
def set(key, value):
    """Set configuration value"""
    try:
        current_config = storage.get_config()
        
        if key == 'max-retries':
            current_config.max_retries = value
        elif key == 'backoff-base':
            current_config.backoff_base = value
        elif key == 'worker-poll-interval':
            current_config.worker_poll_interval = value
        else:
            click.echo(f"Error: Unknown config key '{key}'. Valid keys: max-retries, backoff-base, worker-poll-interval", err=True)
            sys.exit(1)
        
        storage.save_config(current_config)
        click.echo(f"Set {key} = {value}")
        
    except Exception as e:
        click.echo(f"Error setting config: {e}", err=True)
        sys.exit(1)


@config.command()
def show():
    """Show current configuration"""
    try:
        config = storage.get_config()
        click.echo("=== Configuration ===")
        click.echo(f"max-retries: {config.max_retries}")
        click.echo(f"backoff-base: {config.backoff_base}")
        click.echo(f"worker-poll-interval: {config.worker_poll_interval}")
        
    except Exception as e:
        click.echo(f"Error showing config: {e}", err=True)
        sys.exit(1)


def main():
    """Main entry point"""
    cli()


if __name__ == '__main__':
    main()