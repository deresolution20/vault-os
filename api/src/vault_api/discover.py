"""M7.1 — filesystem module discovery: drop a folder in modules/, core mounts it.

A backend module is `modules/<id>/module.py` exporting:

    def register(registry: ModuleRegistry, bus: EventBus) -> None: ...

No core edits are needed to add or remove one (M7.3 proves it). A module that
fails to import is skipped with a logged error — it must never take core down.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from .bus import EventBus
from .config import PROJECT_ROOT
from .modules import ModuleRegistry

MODULES_DIR = PROJECT_ROOT / "modules"


def discover_modules(registry: ModuleRegistry, bus: EventBus) -> list[str]:
    loaded: list[str] = []
    if not MODULES_DIR.is_dir():
        return loaded
    for entry in sorted(MODULES_DIR.iterdir()):
        mod_py = entry / "module.py"
        if not mod_py.is_file():
            continue
        name = f"vault_module_{entry.name.replace('-', '_')}"
        try:
            spec = importlib.util.spec_from_file_location(name, mod_py)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.register(registry, bus)
            loaded.append(entry.name)
        except Exception as e:  # never take core down
            print(f"[modules] SKIPPED {entry.name}: {e}")
    return loaded
