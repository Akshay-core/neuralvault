# Akshay-core
__author__ = "Akshay-core"

# FILE: scripts/lan_server.py
"""
Hosts the Streamlit app on LAN so other devices can connect via browser.
Usage:  python scripts/lan_server.py
"""
import subprocess
import socket
import sys
import os
import secrets


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    port = int(os.environ.get("PORT", 8501))
    token = os.environ.get("LAN_TOKEN", secrets.token_hex(8))
    ip = get_local_ip()

    print("=" * 55)
    print("  AI Second Brain — LAN Server")
    print("=" * 55)
    print(f"  Local IP  : http://{ip}:{port}")
    print(f"  Access token (share with trusted users): {token}")
    print("  Other devices: open browser → http://{ip}:{port}")
    print("=" * 55)

    env = os.environ.copy()
    env["LAN_MODE"] = "1"
    env["LAN_TOKEN"] = token

    cmd = [
        sys.executable, "-m", "streamlit", "run",
        "app/ui/streamlit_app.py",
        "--server.address", "0.0.0.0",
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    subprocess.run(cmd, env=env)


if __name__ == "__main__":
    main()
