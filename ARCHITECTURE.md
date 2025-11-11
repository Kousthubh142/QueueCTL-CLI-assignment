# QueueCTL Architecture & Design

## System Overview

QueueCTL is a CLI-based background job queue system built with Python that provides reliable job processing with retry mechanisms and persistent storage.

## Architecture Diagram

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   CLI Interface │    │  Job Manager    │    │   Worker Pool   │
│                 │    │                 │    │                 │
│ • Commands      │◄──►│ • Job Creation  │◄──►│ • Job Execution │
│ • User Input    │    │ • Retry Logic   │    │ • Multi-threading│
│ • Status Output │    │ • State Mgmt    │    │ • Process Mgmt  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Storage Layer (SQLite)                      │
│                                                                 │
│ • Job Persistence    • Configuration    • State Management     │
│ • Queue Status       • Retry Tracking   • Error Logging        │
└─────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. CLI Interface (`cli.py`)
- **Purpose**: User interaction and command routing
- **Responsibilities**:
  - Parse user commands and arguments
  - Route commands to appropriate managers
  - Format and display output
  - Handle errors and user feedback

### 2. Job Manager (`job_manager.py`)
- **Purpose**: Job lifecycle management
- **Responsibilities**:
  - Create and enqueue new jobs
  - Execute job commands via subprocess
  - Handle job failures and retry logic
  - Implement exponential backoff
  - Move jobs to Dead Letter Queue

### 3. Worker System (`worker.py`)
- **Purpose**: Concurrent job processing
- **Components**:
  - **Worker**: Individual job processor (thread-based)
  - **WorkerManager**: Manages multiple workers
- **Responsibilities**:
  - Poll for available jobs
  - Execute jobs concurrently
  - Handle graceful shutdown
  - Track worker status

### 4. Storage Layer (`storage.py`)
- **Purpose**: Data persistence and retrieval
- **Responsibilities**:
  - SQLite database management
  - Job CRUD operations
  - Configuration persistence
  - Queue status aggregation
  - Retry timing queries

### 5. Data Models (`models.py`)
- **Purpose**: Type definitions and data structures
- **Components**:
  - `Job`: Core job entity with state management
  - `JobState`: Enum for job lifecycle states
  - `QueueConfig`: Configuration settings
  - `WorkerInfo`: Worker metadata
  - `QueueStatus`: Queue statistics

## Job Lifecycle

```
┌─────────┐    ┌────────────┐    ┌───────────┐    ┌───────────┐
│ PENDING │───►│ PROCESSING │───►│ COMPLETED │    │   FAILED  │
└─────────┘    └────────────┘    └───────────┘    └─────┬─────┘
     ▲                                                   │
     │                                                   ▼
     │         ┌─────────┐                        ┌─────────────┐
     └─────────│  DEAD   │◄───────────────────────│ RETRY LOGIC │
               └─────────┘                        └─────────────┘
```

### State Transitions:
1. **PENDING** → **PROCESSING**: Worker picks up job
2. **PROCESSING** → **COMPLETED**: Job executes successfully (exit code 0)
3. **PROCESSING** → **FAILED**: Job fails but retries remain
4. **FAILED** → **PROCESSING**: Retry after exponential backoff delay
5. **FAILED** → **DEAD**: Max retries exceeded, moved to DLQ
6. **DEAD** → **PENDING**: Manual retry from DLQ

## Retry Mechanism

### Exponential Backoff Formula:
```
delay_seconds = backoff_base ^ attempt_number
```

### Example with backoff_base=2:
- Attempt 1 fails → Wait 2¹ = 2 seconds
- Attempt 2 fails → Wait 2² = 4 seconds  
- Attempt 3 fails → Wait 2³ = 8 seconds
- Max retries reached → Move to DLQ

### Implementation:
```python
def _handle_job_failure(self, job: Job) -> bool:
    job.attempts += 1
    if job.attempts >= job.max_retries:
        job.state = JobState.DEAD  # Move to DLQ
    else:
        delay_seconds = config.backoff_base ** job.attempts
        job.next_retry_at = datetime.now() + timedelta(seconds=delay_seconds)
        job.state = JobState.FAILED
```

## Concurrency & Thread Safety

### Worker Threading Model:
- **Main Thread**: CLI interface and user interaction
- **Worker Threads**: Job execution (one per worker)
- **Shared State**: SQLite database with transaction isolation

### Thread Safety Mechanisms:
1. **Database Locking**: SQLite handles concurrent access
2. **Job State Management**: Atomic state transitions
3. **Worker Coordination**: Database-based job claiming
4. **Graceful Shutdown**: Signal handling and thread joining

## Data Persistence

### SQLite Schema:

```sql
-- Jobs table
CREATE TABLE jobs (
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
);

-- Configuration table
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

### Data Flow:
1. **Job Creation**: Insert into jobs table with PENDING state
2. **Job Processing**: Update state to PROCESSING, then COMPLETED/FAILED
3. **Retry Scheduling**: Set next_retry_at timestamp for failed jobs
4. **DLQ Management**: Update state to DEAD when retries exhausted

## Configuration Management

### Configurable Parameters:
- `max_retries`: Maximum retry attempts per job (default: 3)
- `backoff_base`: Exponential backoff base (default: 2)
- `worker_poll_interval`: Worker polling frequency in seconds (default: 1)

### Configuration Storage:
- Stored in SQLite config table as JSON
- Loaded at startup and cached in memory
- Updated via CLI commands

## Error Handling

### Job Execution Errors:
- **Command Not Found**: Captured as stderr, triggers retry
- **Non-zero Exit Code**: Triggers retry with error message
- **Timeout**: 5-minute timeout, triggers retry
- **System Errors**: Exception handling, triggers retry

### System Errors:
- **Database Errors**: Graceful degradation with error messages
- **Worker Errors**: Individual worker failure doesn't affect others
- **CLI Errors**: User-friendly error messages with exit codes

## Performance Considerations

### Scalability:
- **Worker Count**: Configurable based on system resources
- **Database Performance**: SQLite suitable for moderate loads
- **Memory Usage**: Minimal memory footprint per worker

### Optimization Opportunities:
- **Connection Pooling**: Reuse database connections
- **Batch Operations**: Process multiple jobs per transaction
- **Index Optimization**: Add indexes for common queries
- **Distributed Architecture**: Scale beyond single node

## Security Considerations

### Command Execution:
- **Shell Injection**: Commands executed via shell (security risk)
- **Privilege Escalation**: Runs with user permissions
- **Resource Limits**: No built-in resource constraints

### Mitigation Strategies:
- **Input Validation**: Validate job commands before execution
- **Sandboxing**: Run jobs in isolated environments
- **Resource Limits**: Implement CPU/memory limits
- **Audit Logging**: Log all job executions

## Deployment Architecture

### Single Node Deployment:
```
┌─────────────────────────────────────┐
│           Application Host          │
│                                     │
│  ┌─────────────┐  ┌─────────────┐   │
│  │ QueueCTL    │  │   SQLite    │   │
│  │ CLI + Workers│  │  Database   │   │
│  └─────────────┘  └─────────────┘   │
└─────────────────────────────────────┘
```

### Production Considerations:
- **Process Management**: Use systemd or supervisor
- **Log Management**: Centralized logging with rotation
- **Monitoring**: Health checks and metrics collection
- **Backup Strategy**: Regular database backups
- **High Availability**: Database replication for critical systems

## Future Enhancements

### Planned Features:
- **Job Prioritization**: Priority queues for urgent jobs
- **Scheduled Jobs**: Cron-like scheduling capabilities
- **Job Dependencies**: Chain jobs with dependencies
- **Web Dashboard**: Real-time monitoring interface
- **Metrics & Analytics**: Job performance statistics
- **Distributed Mode**: Multi-node job processing
- **Plugin System**: Custom job types and handlers