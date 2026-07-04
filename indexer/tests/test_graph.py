"""M2.1 AC: graph JSON matches Obsidian semantics on a test vault."""

from pathlib import Path

import pytest

from vault_indexer.graph import build_graph


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian/graph.json").write_text("{}")
    (tmp_path / "Projects").mkdir()

    (tmp_path / "Home.md").write_text(
        "---\ntitle: Home Base\ntags: [index, hub]\n---\n"
        "Start at [[Projects/VAULT]] or [[Ideas|the idea pile]].\n"
        "Ghost link: [[Nonexistent Note]] and heading link [[VAULT#Goals]].\n"
        "`[[not-a-link-in-code]]`\n"
    )
    (tmp_path / "Projects/VAULT.md").write_text(
        "# VAULT\nBack to [[Home]]. Self link [[VAULT]] ignored. #ai-os #build/step-one\n"
        "```\n[[also-not-a-link]]\n```\n"
    )
    (tmp_path / "Ideas.md").write_text("Loose thoughts. Tag #someday\n")
    return tmp_path


def test_nodes_and_titles(vault: Path):
    g = build_graph(vault)
    by_id = {n["id"]: n for n in g["nodes"]}
    assert by_id["Home.md"]["title"] == "Home Base"
    assert by_id["Home.md"]["tags"] == ["hub", "index"]
    assert by_id["Projects/VAULT.md"]["tags"] == ["ai-os", "build/step-one"]
    assert by_id["Ideas.md"]["title"] == "Ideas"


def test_link_resolution(vault: Path):
    g = build_graph(vault)
    links = {(l["source"], l["target"]) for l in g["links"]}
    # exact path, alias, stem-resolution, backlink
    assert ("Home.md", "Projects/VAULT.md") in links
    assert ("Home.md", "Ideas.md") in links
    assert ("Projects/VAULT.md", "Home.md") in links
    # heading link [[VAULT#Goals]] resolves to the note, deduped with path link
    assert len([l for l in links if l == ("Home.md", "Projects/VAULT.md")]) == 1


def test_unresolved_ghost_node(vault: Path):
    g = build_graph(vault)
    ghosts = [n for n in g["nodes"] if n.get("unresolved")]
    assert len(ghosts) == 1
    assert ghosts[0]["id"] == "Nonexistent Note"
    assert ("Home.md", "Nonexistent Note") in {
        (l["source"], l["target"]) for l in g["links"]
    }


def test_code_and_selflinks_excluded(vault: Path):
    g = build_graph(vault)
    ids = {n["id"] for n in g["nodes"]}
    assert "not-a-link-in-code" not in ids
    assert "also-not-a-link" not in ids
    assert ("Projects/VAULT.md", "Projects/VAULT.md") not in {
        (l["source"], l["target"]) for l in g["links"]
    }


def test_obsidian_dir_skipped(vault: Path):
    g = build_graph(vault)
    assert all(".obsidian" not in n["id"] for n in g["nodes"])
