"""Config loader (M0.4) — reads the project .env (vault path, ports, tokens)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# project root = projects/vault-os (api/src/vault_api/config.py -> 3 parents up)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    vault_path: Path = Path.home() / "Obsidian_Vaults/Sabrina"
    hermes_api_host: str = "127.0.0.1"
    hermes_api_port: int = 8100
    hermes_api_token: str = ""

    obsidian_rest_url: str = "http://127.0.0.1:27123"
    obsidian_rest_api_key: str = ""

    # M2.2 RAG — local embeddings only (PRD §3.4)
    rag_data_dir: Path = PROJECT_ROOT / ".tmp/rag"
    ollama_url: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"

    worker_r9700_url: str = "http://127.0.0.1:8081/v1"
    worker_7900xtx_url: str = "http://127.0.0.1:8082/v1"

    anthropic_api_key: str = ""

    plane_api_url: str = ""
    # browser-facing origin for issue links — the one Brice is signed into
    # (session cookies don't cross localhost vs LAN-IP origins)
    plane_web_url: str = ""
    plane_api_token: str = ""
    plane_workspace_slug: str = ""
    plane_project_id: str = ""

    grafana_embed_url: str = ""


settings = Settings()
