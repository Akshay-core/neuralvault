# Akshay-core
__author__ = "Akshay-core"

# FILE: app/utils/device_check.py
import psutil
import platform


def get_system_info() -> dict:
    ram = psutil.virtual_memory()
    cpu = psutil.cpu_freq()
    return {
        "os": platform.system(),
        "ram_total_gb": round(ram.total / (1024**3), 1),
        "ram_available_gb": round(ram.available / (1024**3), 1),
        "ram_used_pct": ram.percent,
        "cpu_physical_cores": psutil.cpu_count(logical=False),
        "cpu_logical_cores": psutil.cpu_count(logical=True),
        "cpu_freq_mhz": round(cpu.current, 0) if cpu else "N/A",
        "cpu_usage_pct": psutil.cpu_percent(interval=0.5),
    }


def recommend_mode(info: dict) -> str:
    ram = info["ram_total_gb"]
    if ram < 6:
        return "ultra_safe"
    elif ram < 12:
        return "light"
    elif ram < 20:
        return "balanced"
    else:
        return "performance"


def get_performance_budget() -> dict:
    info = get_system_info()
    mode = recommend_mode(info)
    model_map = {
        "ultra_safe": "phi3:mini",
        "light": "phi3:mini",
        "balanced": "llama3.1:8b",
        "performance": "llama3.1:8b",  # 70b only if user opts in
    }
    return {
        "mode": mode,
        "recommended_model": model_map[mode],
        "system_info": info
    }


if __name__ == "__main__":
    import json
    print(json.dumps(get_performance_budget(), indent=2))
