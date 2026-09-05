import socket
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


def redis_is_up(host="127.0.0.1", port=6379):
    """Check whether something is already listening on the Redis port"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def start_redis():
    """Start Redis server, unless one is already running"""
    if redis_is_up():
        print("Redis already running on 127.0.0.1:6379, reusing it")
        return None

    print("Starting Redis server...")
    try:
        proc = subprocess.Popen(["redis-server"])
    except FileNotFoundError:
        print("Redis not found. Please install Redis or start it manually.")
        return None

    time.sleep(1)  # Give Redis time to start
    if proc.poll() is not None:
        print(f"Redis failed to start (exit code {proc.returncode}), see output above")
        return None

    processes.append(("Redis", proc))
    print("Redis server started")
    return proc


def start_backend(): 
    """Start the FastAPI backend server using backend's venv"""
    print("Starting Backend server...")
    
    # Use the venv Python from the backend directory
    venv_python = BACKEND_DIR / ".venv" / "bin" / "python"
    if not venv_python.exists():
        print(f"Backend venv not found at {venv_python}")
        print("Please run: cd backend && uv sync")
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
        ["bun", "dev"],
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
    print("   Frontend: http://localhost:3000 (or check output above)")
    print("   Press Ctrl+C to stop all services")
    print("=" * 50)
    print()

    # Wait for all processes
    try:
        while True:
            # If any process has died, stop the rest instead of limping along
            for name, proc in processes:
                if proc.poll() is not None:
                    print(f"{name} has stopped unexpectedly (exit code {proc.returncode})!")
                    cleanup()
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()