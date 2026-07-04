"""M2.1 — vault parser: markdown + [[wikilinks]] → {nodes, links} graph JSON.

Mirrors Obsidian's own graph semantics:
- every .md file is a node (id = vault-relative path without extension? NO —
  id = vault-relative path incl. .md, matching shared/events.ts GraphNode)
- every [[wikilink]] (incl. [[target|alias]], [[target#heading]], ![[embeds]])
  is a directed link source → target
- links to non-existent notes create `unresolved` nodes (Obsidian's ghost nodes)
- target resolution follows Obsidian: exact vault path first, then unique
  filename-stem match anywhere in the vault (shortest path wins on ties)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {".obsidian", ".trash", ".git"}

# [[target]] / [[target|alias]] / [[target#heading]] / ![[embed]]
WIKILINK_RE = re.compile(r"(!?)\[\[([^\]\[]+?)\]\]")
# ```code fences``` and `inline code` must not contribute links
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
FM_TITLE_RE = re.compile(r"^title:\s*[\"']?(.+?)[\"']?\s*$", re.MULTILINE)
FM_TAGS_BLOCK_RE = re.compile(
    r"^tags:\s*(?:\[(?P<inline>[^\]]*)\]\s*$|(?P<list>(?:\n\s*-\s*.+)+))",
    re.MULTILINE,
)
INLINE_TAG_RE = re.compile(r"(?:^|\s)#([\w/-]+)")


@dataclass
class Note:
    rel_path: str  # vault-relative, with .md
    abs_path: str
    title: str
    tags: list[str] = field(default_factory=list)
    raw_targets: list[str] = field(default_factory=list)


def _strip_code(text: str) -> str:
    return INLINE_CODE_RE.sub("", CODE_FENCE_RE.sub("", text))


def _parse_note(vault: Path, md: Path) -> Note:
    text = md.read_text(encoding="utf-8", errors="replace")
    rel = md.relative_to(vault).as_posix()

    title = md.stem
    tags: list[str] = []
    fm = FRONTMATTER_RE.match(text)
    body = text
    if fm:
        body = text[fm.end() :]
        if m := FM_TITLE_RE.search(fm.group(1)):
            title = m.group(1)
        if m := FM_TAGS_BLOCK_RE.search(fm.group(1)):
            if m.group("inline") is not None:
                tags += [t.strip().strip("\"'") for t in m.group("inline").split(",")]
            else:
                tags += [
                    line.split("-", 1)[1].strip()
                    for line in m.group("list").strip().splitlines()
                ]
    tags += INLINE_TAG_RE.findall(_strip_code(body))
    tags = sorted({t.lstrip("#") for t in tags if t and t.strip()})

    targets = []
    for _embed, inner in WIKILINK_RE.findall(_strip_code(body)):
        target = inner.split("|")[0].split("#")[0].strip()
        if target:
            targets.append(target)

    return Note(rel, str(md), title, tags, targets)


def _resolve(target: str, by_path: dict[str, Note], by_stem: dict[str, list[Note]]) -> str | None:
    """Resolve a wikilink target to a note's rel_path, Obsidian-style."""
    t = target.strip("/")
    # exact path (with or without .md)
    for cand in (t, f"{t}.md"):
        if cand in by_path:
            return cand
    # filename-stem match anywhere in vault; shortest path wins
    stem = t.rsplit("/", 1)[-1].lower()
    matches = by_stem.get(stem, [])
    if matches:
        return min(matches, key=lambda n: len(n.rel_path)).rel_path
    return None


def build_graph(vault_path: str | Path) -> dict:
    """Return {nodes, links} matching shared/events.ts VaultGraph."""
    vault = Path(vault_path).expanduser().resolve()
    notes: list[Note] = []
    for md in sorted(vault.rglob("*.md")):
        if any(part in SKIP_DIRS for part in md.relative_to(vault).parts):
            continue
        notes.append(_parse_note(vault, md))

    by_path = {n.rel_path: n for n in notes}
    by_stem: dict[str, list[Note]] = {}
    for n in notes:
        by_stem.setdefault(Path(n.rel_path).stem.lower(), []).append(n)

    nodes = [
        {"id": n.rel_path, "path": n.abs_path, "title": n.title, "tags": n.tags}
        for n in notes
    ]
    links: list[dict] = []
    seen_links: set[tuple[str, str]] = set()
    unresolved_ids: set[str] = set()

    for n in notes:
        for target in n.raw_targets:
            resolved = _resolve(target, by_path, by_stem)
            if resolved is None:
                # ghost node, keyed by the raw link text (Obsidian behavior)
                node_id = target
                if node_id not in unresolved_ids and node_id not in by_path:
                    unresolved_ids.add(node_id)
                    nodes.append(
                        {
                            "id": node_id,
                            "path": "",
                            "title": target.rsplit("/", 1)[-1],
                            "tags": [],
                            "unresolved": True,
                        }
                    )
                resolved = node_id
            if resolved == n.rel_path:
                continue  # self-link
            key = (n.rel_path, resolved)
            if key not in seen_links:
                seen_links.add(key)
                links.append({"source": n.rel_path, "target": resolved})

    return {"nodes": nodes, "links": links}
