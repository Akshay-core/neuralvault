# Akshay-core
__author__ = "Akshay-core"

# FILE: plugins/plugin_manager.py
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional
from plugins.base_plugin import BasePlugin
from app.utils.logger import get_logger

logger = get_logger("plugin_manager")

PLUGINS_DIR = Path(__file__).parent
DEFAULT_TIMEOUT_SECONDS = 12
REQUIRED_MANIFEST_FIELDS = {"name", "version", "permissions"}


class PluginManager:
    def __init__(self):
        self._registry: Dict[str, BasePlugin] = {}
        self._sources: Dict[str, dict] = {}
        self._auto_discover()

    def _auto_discover(self):
        examples_dir = PLUGINS_DIR / "examples"
        search_dirs = [examples_dir]
        if os.getenv("AI_SECOND_BRAIN_ALLOW_UNTRUSTED_PLUGINS", "0") == "1":
            search_dirs.insert(0, PLUGINS_DIR)
        for d in search_dirs:
            if not d.exists():
                continue
            for f in d.glob("*_plugin.py"):
                self._load_from_file(f)

    def _load_from_file(self, path: Path):
        try:
            manifest = self._read_manifest(path)
            if manifest is None:
                logger.warning(f"Plugin skipped without manifest: {path.name}")
                return
            module_name = f"plugin_{path.stem}_{id(path)}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for attr in dir(mod):
                cls = getattr(mod, attr)
                if (
                    isinstance(cls, type)
                    and issubclass(cls, BasePlugin)
                    and cls is not BasePlugin
                ):
                    instance = cls()
                    trusted_dir = (PLUGINS_DIR / "examples").resolve()
                    self._registry[instance.name] = instance
                    self._sources[instance.name] = {
                        "path": str(path.resolve()),
                        "class_name": cls.__name__,
                        "trusted": trusted_dir in path.resolve().parents,
                        "manifest": manifest,
                    }
                    logger.info(f"Plugin loaded: {instance.name} v{instance.version}")
        except Exception as e:
            logger.warning(f"Failed to load plugin {path.name}: {e}")

    def _read_manifest(self, path: Path) -> dict | None:
        manifest_path = path.with_suffix(".manifest.json")
        if not manifest_path.exists():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Invalid plugin manifest {manifest_path.name}: {exc}")
            return None
        if not REQUIRED_MANIFEST_FIELDS.issubset(manifest):
            logger.warning(f"Plugin manifest missing required fields: {manifest_path.name}")
            return None
        permissions = set(manifest.get("permissions") or [])
        if permissions - {"compute", "read_input"}:
            logger.warning(f"Plugin manifest requests unsupported permissions: {manifest_path.name}")
            return None
        return manifest

    def register(self, plugin: BasePlugin):
        self._registry[plugin.name] = plugin
        self._sources.pop(plugin.name, None)
        logger.info(f"Plugin registered manually: {plugin.name}")

    def get(self, name: str) -> Optional[BasePlugin]:
        return self._registry.get(name)

    def list_plugins(self) -> list:
        items = []
        for plugin in self._registry.values():
            info = plugin.info()
            source = self._sources.get(plugin.name) or {}
            manifest = source.get("manifest") or {}
            info["permissions"] = manifest.get("permissions", [])
            info["sandbox"] = "subprocess" if source else "in-process"
            items.append(info)
        return items

    def run(self, name: str, input_data: dict) -> dict:
        plugin = self.get(name)
        if not plugin:
            return {"success": False, "error": f"Plugin '{name}' not found"}
        source = self._sources.get(name)
        if source:
            return self._run_subprocess(name, source, input_data)
        try:
            if not plugin.validate(input_data):
                return {"success": False, "error": "Input validation failed"}
            return plugin.execute(input_data)
        except Exception as e:
            logger.error(f"Plugin {name} execution error: {e}")
            return {"success": False, "error": str(e)}

    def _run_subprocess(self, name: str, source: dict, input_data: dict) -> dict:
        runner = r"""
import importlib.util, json, pathlib, sys
payload = json.loads(sys.stdin.read())
path = pathlib.Path(payload["path"]).resolve()
class_name = payload["class_name"]
spec = importlib.util.spec_from_file_location("sandboxed_plugin", str(path))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
cls = getattr(mod, class_name)
plugin = cls()
data = payload["input"]
if not plugin.validate(data):
    print(json.dumps({"success": False, "error": "Input validation failed"}))
else:
    print(json.dumps(plugin.execute(data), ensure_ascii=False))
"""
        payload = {
            "path": source["path"],
            "class_name": source["class_name"],
            "input": input_data,
        }
        try:
            plugin_path = Path(source["path"]).resolve()
            trusted_root = PLUGINS_DIR.resolve()
            if trusted_root not in plugin_path.parents:
                return {"success": False, "error": "Plugin path is outside the plugin boundary"}
            completed = subprocess.run(
                [sys.executable, "-c", runner],
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                cwd=str(PLUGINS_DIR.parent),
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Plugin '{name}' timed out"}
        except Exception as e:
            return {"success": False, "error": f"Plugin sandbox failed: {e}"}
        if completed.returncode != 0:
            logger.error(f"Plugin {name} sandbox stderr: {completed.stderr[:600]}")
            return {"success": False, "error": completed.stderr.strip() or "Plugin sandbox failed"}
        try:
            return json.loads(completed.stdout.strip().splitlines()[-1])
        except Exception:
            return {"success": False, "error": "Plugin returned invalid JSON"}


# singleton
_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _manager
    if _manager is None:
        _manager = PluginManager()
    return _manager
