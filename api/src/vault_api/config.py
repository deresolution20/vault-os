"""Config loader (M0.4) — reads the project .env (vault path, ports, tokens)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# project root = projects/vault-os (api/src/vault_api/config.py -> 3 parents up)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    vault_path: Path = Path.home() / "vault"  # set VAULT_PATH in .env
    hermes_api_host: str = "127.0.0.1"
    hermes_api_port: int = 8100
    hermes_api_token: str = ""

    obsidian_rest_url: str = "http://127.0.0.1:27123"
    obsidian_rest_api_key: str = ""

    # M2.2 RAG — local embeddings only (PRD §3.4); served by vault-embed
    # (llama.cpp :8084) since the ollama decommission (2026-07-05)
    rag_data_dir: Path = PROJECT_ROOT / ".tmp/rag"
    embed_url: str = "http://127.0.0.1:8084"
    embed_model: str = "nomic-embed-text"
    ollama_url: str = "http://localhost:11434"  # legacy; deck residents only

    worker_r9700_url: str = "http://127.0.0.1:8081/v1"
    # interim junior lane on the NVIDIA card until the 7900 XTX arrives
    worker_4060ti_url: str = "http://127.0.0.1:8082/v1"
    worker_7900xtx_url: str = "http://127.0.0.1:8083/v1"

    anthropic_api_key: str = ""

    plane_api_url: str = ""
    # browser-facing origin for issue links — the one the operator is signed into
    # (session cookies don't cross localhost vs LAN-IP origins)
    plane_web_url: str = ""
    plane_api_token: str = ""
    plane_workspace_slug: str = ""
    plane_project_id: str = ""

    grafana_embed_url: str = ""


settings = Settings()
