import importlib.util
import io
import subprocess
from pathlib import Path


def load_gpu_deck():
    path = Path(__file__).resolve().parents[2] / "modules/gpu-deck/module.py"
    spec = importlib.util.spec_from_file_location("gpu_deck_test_module", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_gpu_deck_workers_use_7900xtx_as_junior_lane():
    module = load_gpu_deck()

    assert [w["gpu"] for w in module.WORKERS] == ["r9700", "7900xtx"]
    junior = module.WORKERS[1]
    assert junior["url"] == "http://127.0.0.1:8082/v1"
    assert junior["unit"] == "vault-worker-7900xtx"
    assert junior["defaultModel"] == "qwen3.6-35b-a3b"


def test_nvidia_gpus_ignores_failed_smi(monkeypatch):
    module = load_gpu_deck()

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0],
            9,
            stdout="NVIDIA-SMI has failed because it could not communicate\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module._nvidia_gpus() == []


def test_amd_gpus_use_canonical_worker_ids(monkeypatch):
    module = load_gpu_deck()
    vendor = "/sys/class/drm/card0/device/vendor"
    dev = "/sys/class/drm/card0/device"
    files = {
        vendor: "0x1002\n",
        f"{dev}/device": "0x744c\n",
        f"{dev}/mem_info_vram_total": "25769803776\n",
        f"{dev}/mem_info_vram_used": "8589934592\n",
    }

    monkeypatch.setattr(module.glob, "glob", lambda _pattern: [vendor])
    monkeypatch.setattr("builtins.open", lambda path, *_args, **_kwargs: io.StringIO(files[path]))

    assert module._amd_gpus() == [
        {
            "id": "7900xtx",
            "name": "AMD 7900 XTX (gfx1100)",
            "vramUsedGB": 8.6,
            "vramTotalGB": 25.8,
        }
    ]
