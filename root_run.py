import subprocess
import sys
import signal
import time
from pathlib import Path

# Get the root directory
ROOT_DIR = Path(__file__).parent.resolve()
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"

# Store all processes
processes = []


def cleanup(signum=None, frame=None):
    """Clean up all spawned processes"""
    print("\nShutting down all services...")
    for name, proc in processes:
        if proc.poll() is None:  # Process is still running
            print(f"Stopping {name}...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    print("All services stopped.")
    sys.exit(0)


def start_redis():
    """Start Redis server"""
    print("Starting Redis server...")
    try:
        proc = subprocess.Popen(
            ["redis-server"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append(("Redis", proc))
        time.sleep(1)  # Give Redis time to start
        if proc.poll() is not None:
            print(" Redis may already be running or failed to start")
        else:
            print("Redis server started")
        return proc
    except FileNotFoundError:
        print("Redis not found. Please install Redis or start it manually.")
        return None


def start_backend(): 
    """Start the FastAPI backend server using backend's venv"""
    print("Starting Backend server...")
    
    # Use the venv Python from the backend directory
    venv_python = BACKEND_DIR / "venv" / "bin" / "python"
    if not venv_python.exists():
        print(f"Backend venv not found at {venv_python}")
        print("Please create it first: cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt")
        sys.exit(1)
    
    proc = subprocess.Popen(
        [str(venv_python), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
        cwd=str(BACKEND_DIR),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    processes.append(("Backend", proc))
    print("Backend server started on http://127.0.0.1:8000")
    return proc


def start_frontend():
    """Start the frontend dev server"""
    print("Starting Frontend dev server...")
    proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host"],
        cwd=str(FRONTEND_DIR),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    processes.append(("Frontend", proc))
    print("Frontend dev server started")
    return proc


def main():
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("=" * 50)
    print("Nego-lah - Starting All Services")
    print("=" * 50)
    print()

    # Start all services
    start_redis()
    time.sleep(1)
    
    start_backend()
    time.sleep(2)
    
    start_frontend()

    print()
    print("=" * 50)
    print("   All services are running!")
    print("   Backend:  http://127.0.0.1:8000")
    print("   Frontend: http://localhost:5173 (or check output above)")
    print("   Press Ctrl+C to stop all services")
    print("=" * 50)
    print()

    # Wait for all processes
    try:
        while True:
            # Check if any process has died
            for name, proc in processes:
                if proc.poll() is not None:
                    print(f"{name} has stopped unexpectedly!")
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()