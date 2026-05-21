# Akshay-core
__author__ = "Akshay-core"

# FILE: run.py
"""
One-command launcher for AI Second Brain.
Usage:
    python run.py              # default (local, port 8501)
    python run.py --lan        # LAN mode (accessible from other devices)
    python run.py --port 8888  # custom port
    python run.py --setup      # run setup only
"""
import subprocess
import sys
import os
import argparse
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))


def pre_check():
    """Quick env check before launch."""
    try:
        from app.database.sqlite_db import init_db
        init_db()
    except Exception as e:
        print(f"DB init warning: {e}")

    try:
        from app.models.ollama_client import is_ollama_running
        if not is_ollama_running():
            print("⚠️  Ollama is not running.")
            print("   Start it: ollama serve")
            print("   Continuing anyway (chat will show error until Ollama is up)\n")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="AI Second Brain Launcher")
    parser.add_argument("--lan", action="store_true", help="Host on LAN (0.0.0.0)")
    parser.add_argument("--port", type=int, default=8501, help="Port to run on")
    parser.add_argument("--setup", action="store_true", help="Run setup only")
    args = parser.parse_args()

    if args.setup:
        subprocess.run([sys.executable, "scripts/setup_env.py"])
        return

    print("=" * 55)
    print("  🧠 AI Second Brain")
    print("  Offline RAG Intelligence System")
    print("=" * 55)

    pre_check()

    if args.lan:
        subprocess.run([sys.executable, "scripts/lan_server.py"])
        return

    host = "localhost"
    url = f"http://{host}:{args.port}"
    print(f"\n  App running at: {url}")
    print("  Press Ctrl+C to stop\n")

    cmd = [
        sys.executable, "-m", "streamlit", "run",
        "app/ui/streamlit_app.py",
        "--server.address", host,
        "--server.port", str(args.port),
        "--server.headless", "false",
        "--browser.gatherUsageStats", "false",
        "--theme.base", "dark",
    ]
    subprocess.run(cmd)


if __name__ == "__main__":
    main()
