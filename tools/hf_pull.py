#!/usr/bin/env python3
"""hf_pull — download a GGUF (any quant) from Hugging Face into ~/llm-models.

Usage:
  uv run --with huggingface_hub tools/hf_pull.py <repo_id> [quant]
  uv run --with huggingface_hub tools/hf_pull.py TheDrummer/Cydonia-24B-v4-GGUF Q4_K_M

With no quant: lists the repo's GGUF files and sizes, downloads nothing.
With a quant: downloads all matching *.gguf (handles multi-part shards),
resume-capable, prints progress lines (streamed into the vault transcript
when dispatched via /pull).
"""

import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, list_repo_files
from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError

DEST = Path.home() / "llm-models"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    repo = sys.argv[1]
    quant = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        files = [f for f in list_repo_files(repo) if f.endswith(".gguf")]
    except RepositoryNotFoundError:
        print(f"ERROR: repo not found: {repo}")
        return 1
    except GatedRepoError:
        print(f"ERROR: gated repo (needs HF token/licence acceptance): {repo}")
        return 1
    if not files:
        print(f"ERROR: no .gguf files in {repo}")
        return 1

    if quant is None:
        print(f"GGUF files in {repo}:")
        for f in sorted(files):
            print(f"  {f}")
        print("\nre-run with a quant substring (e.g. Q4_K_M) to download")
        return 0

    matches = [f for f in files if quant.lower() in f.lower()]
    if not matches:
        print(f"ERROR: no files match '{quant}'. Available:")
        for f in sorted(files):
            print(f"  {f}")
        return 1

    DEST.mkdir(parents=True, exist_ok=True)
    print(f"downloading {len(matches)} file(s) from {repo} → {DEST}")
    for f in matches:
        print(f"⇣ {f} …")
        path = hf_hub_download(
            repo_id=repo,
            filename=f,
            local_dir=DEST,
            local_dir_use_symlinks=False,
        )
        gb = Path(path).stat().st_size / 1e9
        print(f"✓ {Path(path).name} · {gb:.1f}GB")
    print("done — run /models to see it in the catalog")
    return 0


if __name__ == "__main__":
    sys.exit(main())
