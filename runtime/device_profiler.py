# Akshay-core
__author__ = "Akshay-core"

# FILE: runtime/device_profiler.py
import psutil
import platform
import time
from app.utils.logger import get_logger

logger = get_logger("device_profiler")


def profile() -> dict:
    mem = psutil.virtual_memory()
    cpu_pct = psutil.cpu_percent(interval=0.3)
    freq = psutil.cpu_freq()
    battery = psutil.sensors_battery()

    return {
        "ram_total_gb": round(mem.total / 1024**3, 1),
        "ram_used_pct": mem.percent,
        "ram_available_gb": round(mem.available / 1024**3, 1),
        "cpu_cores_physical": psutil.cpu_count(logical=False) or 2,
        "cpu_cores_logical": psutil.cpu_count(logical=True) or 4,
        "cpu_usage_pct": cpu_pct,
        "cpu_freq_mhz": round(freq.current) if freq else 0,
        "on_battery": battery.power_plugged is False if battery else False,
        "battery_pct": battery.percent if battery else 100,
        "platform": platform.system(),
        "arch": platform.machine(),
    }


def get_performance_mode(p: dict = None) -> str:
    if p is None:
        p = profile()
    ram = p["ram_total_gb"]
    on_bat = p.get("on_battery", False)
    cpu_load = p.get("cpu_usage_pct", 0)

    if ram < 6 or (on_bat and cpu_load > 70):
        return "safe"        # phi3 only, low ctx
    elif ram < 14:
        return "light"       # phi3, normal ctx
    elif ram < 22:
        return "balanced"    # llama 8b
    else:
        return "performance" # llama 8b, allow 70b opt-in


def throttle_if_needed(p: dict = None):
    """Adds a small delay when system is under heavy load."""
    if p is None:
        p = profile()
    if p.get("cpu_usage_pct", 0) > 85:
        logger.debug("CPU hot — throttling 1s")
        time.sleep(1.0)
    elif p.get("ram_used_pct", 0) > 90:
        logger.debug("RAM pressure — throttling 0.5s")
        time.sleep(0.5)
