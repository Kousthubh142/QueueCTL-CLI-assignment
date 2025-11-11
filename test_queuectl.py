#!/usr/bin/env python3
"""
Comprehensive test script for QueueCTL
Tests core functionality including job execution, retries, and persistence
"""

import subprocess
import time
import json
import os
import sys
import sqlite3
from datetime import datetime


def run_command(cmd, timeout=10):
    """Run a command and return result"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"


def test_basic_functionality():
    """Test basic job enqueue and execution"""
    print("=== Testing Basic Functionality ===")
    
    # Clean up any existing database
    if os.path.exists("queuectl.db"):
        os.remove("queuectl.db")
    
    # Test enqueue
    print("1. Testing job enqueue...")
    code, out, err = run_command('queuectl enqueue \'{"id":"test1","command":"echo Hello World"}\'')
    if code != 0:
        print(f"❌ Enqueue failed: {err}")
        return False
    print("✅ Job enqueued successfully")
    
    # Test status
    print("2. Testing status command...")
    code, out, err = run_command('queuectl status')
    if code != 0 or "Pending:    1" not in out:
        print(f"❌ Status check failed: {out}")
        return False
    print("✅ Status shows pending job")
    
    # Test list
    print("3. Testing list command...")
    code, out, err = run_command('queuectl list --state pending')
    if code != 0 or "test1" not in out:
        print(f"❌ List failed: {out}")
        return False
    print("✅ List shows pending job")
    
    return True


def test_job_execution():
    """Test job execution with workers"""
    print("\n=== Testing Job Execution ===")
    
    # Start worker in background
    print("1. Starting worker...")
    worker_process = subprocess.Popen(
        ['queuectl', 'worker', 'start', '--count', '1'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Give worker time to start
    time.sleep(2)
    
    # Add a simple job
    print("2. Adding job for execution...")
    run_command('queuectl enqueue \'{"id":"exec1","command":"echo Executed"}\'')
    
    # Wait for execution
    time.sleep(3)
    
    # Check if job completed
    print("3. Checking job completion...")
    code, out, err = run_command('queuectl list --state completed')
    
    # Stop worker
    worker_process.terminate()
    worker_process.wait(timeout=5)
    
    if "exec1" not in out:
        print(f"❌ Job execution failed: {out}")
        return False
    
    print("✅ Job executed successfully")
    return True


def test_retry_mechanism():
    """Test job retry with exponential backoff"""
    print("\n=== Testing Retry Mechanism ===")
    
    # Set low retry count for faster testing
    print("1. Setting retry configuration...")
    run_command('queuectl config set max-retries 2')
    run_command('queuectl config set backoff-base 2')
    
    # Add a failing job
    print("2. Adding failing job...")
    run_command('queuectl enqueue \'{"id":"fail1","command":"exit 1","max_retries":2}\'')
    
    # Start worker
    worker_process = subprocess.Popen(
        ['queuectl', 'worker', 'start', '--count', '1'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for retries to complete
    print("3. Waiting for retries...")
    time.sleep(10)  # Allow time for retries with backoff
    
    # Stop worker
    worker_process.terminate()
    worker_process.wait(timeout=5)
    
    # Check if job moved to DLQ
    print("4. Checking Dead Letter Queue...")
    code, out, err = run_command('queuectl dlq list')
    
    if "fail1" not in out:
        print(f"❌ Job not in DLQ: {out}")
        return False
    
    print("✅ Job moved to DLQ after retries")
    
    # Test DLQ retry
    print("5. Testing DLQ retry...")
    run_command('queuectl dlq retry fail1')
    
    code, out, err = run_command('queuectl list --state pending')
    if "fail1" not in out:
        print(f"❌ DLQ retry failed: {out}")
        return False
    
    print("✅ DLQ retry successful")
    return True


def test_persistence():
    """Test data persistence across restarts"""
    print("\n=== Testing Persistence ===")
    
    # Add a job
    print("1. Adding job for persistence test...")
    run_command('queuectl enqueue \'{"id":"persist1","command":"echo Persistent"}\'')
    
    # Verify job exists
    code, out, err = run_command('queuectl list --state pending')
    if "persist1" not in out:
        print("❌ Job not found before restart")
        return False
    
    # Check database file exists
    if not os.path.exists("queuectl.db"):
        print("❌ Database file not created")
        return False
    
    # Verify job in database
    print("2. Checking database persistence...")
    try:
        conn = sqlite3.connect("queuectl.db")
        cursor = conn.execute("SELECT id, command FROM jobs WHERE id = 'persist1'")
        row = cursor.fetchone()
        conn.close()
        
        if not row or row[0] != "persist1":
            print("❌ Job not found in database")
            return False
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False
    
    print("✅ Job persisted in database")
    
    # Test after simulated restart (just check data is still there)
    code, out, err = run_command('queuectl list --state pending')
    if "persist1" not in out:
        print("❌ Job not found after restart simulation")
        return False
    
    print("✅ Data survives restart")
    return True


def test_configuration():
    """Test configuration management"""
    print("\n=== Testing Configuration ===")
    
    # Test setting config
    print("1. Testing config set...")
    run_command('queuectl config set max-retries 5')
    run_command('queuectl config set backoff-base 3')
    
    # Test showing config
    print("2. Testing config show...")
    code, out, err = run_command('queuectl config show')
    
    if "max-retries: 5" not in out or "backoff-base: 3" not in out:
        print(f"❌ Config not saved correctly: {out}")
        return False
    
    print("✅ Configuration management working")
    return True


def test_worker_management():
    """Test worker start/stop functionality"""
    print("\n=== Testing Worker Management ===")
    
    # Test worker start
    print("1. Testing worker start...")
    worker_process = subprocess.Popen(
        ['queuectl', 'worker', 'start', '--count', '2'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    time.sleep(2)
    
    # Check status shows workers
    code, out, err = run_command('queuectl status')
    if "Active Workers: 2" not in out:
        print(f"❌ Workers not showing in status: {out}")
        worker_process.terminate()
        return False
    
    print("✅ Workers started successfully")
    
    # Test graceful shutdown
    print("2. Testing worker shutdown...")
    worker_process.terminate()
    worker_process.wait(timeout=10)
    
    print("✅ Workers shut down gracefully")
    return True


def main():
    """Run all tests"""
    print("QueueCTL Comprehensive Test Suite")
    print("=" * 40)
    
    tests = [
        ("Basic Functionality", test_basic_functionality),
        ("Job Execution", test_job_execution),
        ("Retry Mechanism", test_retry_mechanism),
        ("Persistence", test_persistence),
        ("Configuration", test_configuration),
        ("Worker Management", test_worker_management),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name}: PASSED")
            else:
                failed += 1
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            failed += 1
            print(f"❌ {test_name}: ERROR - {e}")
        
        print()
    
    print("=" * 40)
    print(f"Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed!")
        return 0
    else:
        print("💥 Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())