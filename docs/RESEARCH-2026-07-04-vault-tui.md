# VAULT TUI research — framework choice + interaction patterns (2026-07-04)

Deep-research run: 5 angles · 21 sources fetched · 103 claims extracted ·
25 verified (3-vote adversarial) → **22 confirmed, 3 refuted, 0 unverified**.
Question: Python Textual vs Rust ratatui vs Node Ink for a Claude-Code-style
operator TUI (dashboard + command deck, 10–30 updates/sec streaming, SSH,
Blade Runner theming), plus which interaction patterns to steal.

## Verdict (see TUI-DECISION-2026-07-04.md)

**Stay with Python Textual.** Every load-bearing requirement has a verified,
first-party answer in Textual; the competing ecosystems fail on the markdown/
streaming story; and the existing prototype (tools/vault_top.py) is already
Textual.

## Confirmed findings (all 3-0 or 2-1 adversarial votes)

1. **Textual is flicker-resistant by architecture** (high confidence, 3-0×2):
   damage-limited compositor redraws only changed regions (to single-line/char
   granularity via the Line API) and composites layers into a single write per
   terminal line. Caveat: sub-widget granularity needs the Line API; plain
   Rich renderables redraw the whole widget.
   — textual.textualize.io/blog/2024/12/12/algorithms-for-high-performance-terminal-apps, /guide/widgets/

2. **Textual's Worker API is purpose-built for our streaming case** (high,
   3-0×3): `@work`/`run_worker` for concurrent network+UI;
   `@work(exclusive=True)` cancels prior workers in the group (built-in
   esc-interrupt/supersede semantics); threaded readers must use
   `App.call_from_thread` or thread-safe `post_message` (async workers on the
   loop are unconstrained). — /guide/workers/, /api/work/

3. **Streaming markdown at 10–30 updates/sec is a solved, built-in problem**
   (high, 3-0×2): `Markdown.append()` + `Markdown.get_stream()` →
   `MarkdownStream` coalesces rapid appends into fewer parse/redraw cycles
   (widget saturates ~20 appends/sec raw; the stream batches to keep up).
   Verified against installed textual 8.2.8 source, not just docs.
   ⚠ Refuted companion claim: "built-in Markdown widget since 0.11.0 covers
   everything" (0-3) — rely on the current 8.x streaming API specifically.

4. **Textual maturity/sustainability** (high, 3-0): actively maintained
   1.0 (Dec 2024) → 8.2.8 (Jun 2026), but by **Will McGugan solo** since
   Textualize-the-company wound down (May 2025). Single-maintainer risk —
   monitor, but 18 months of steady post-windup releases.

5. **ratatui markdown ecosystem is immature** (high, 3-0×5): tui-markdown is
   a self-described "experimental Proof of Concept" (0.3.8, highlight theme
   hardcoded to base16-ocean.dark — Blade Runner theming would need patching);
   ratatui-markdown has ~32 stars, 19 commits, nonstandard "SySL v1.0"
   license. Both far behind Rich/Textual rendering.

6. **Node/Ink path bottoms out in marked-terminal** (medium): marked-terminal
   itself is mature (~5.66M weekly downloads) but the Ink-native wrapper is a
   ~13-line component, stale since Oct 2023, pinning old versions.

7. **Claude Code's actual stack validates the approach, not a framework**
   (medium, 2-1): layout via Meta's Yoga (TS rewrite) inside a heavily
   forked/custom Ink-derived renderer (React-commit → Yoga → paint-buffer →
   diff → flush). The popular "Claude Code = stock React+Ink" framing was
   **refuted 0-3**. Lesson: flexbox-ish layout + custom paint pipeline, not
   "use Ink".

8. **Proven interaction-pattern precedents** (high): k9s = live dashboard +
   filter/Enter drill-down (but 2s default refresh — pattern precedent, not a
   10-30Hz perf proof); `ku` (2026, ex-kli) = lazygit-style multi-pane, Tab
   pane cycling, always-visible context-sensitive keybar. Study Charm's
   **Crush** for agent-TUI patterns (opencode-ai/opencode archived 2025-09-18;
   its "Go/BubbleTea reference" framing refuted 0-3).

9. **Flicker-free streaming recipe (cross-framework)** (high, 3-0):
   coalesce/throttle incoming fragments + damage-limited redraw + DEC mode
   2026 synchronized output (Ink 6.7+, Bubble Tea v2 adopt it). ⚠ mode 2026
   needs terminal support; tmux passthrough only landed recently (PR #4744) —
   relevant for SSH+tmux use.

## Refuted (do not build on these)

- "opencode is a live Go/BubbleTea reference tool" — archived, 0-3.
- "Textual's Markdown widget (since 0.11.0) alone covers all needs" — 0-3.
- "Claude Code is built with stock React + Ink" — 0-3.

## Coverage gaps (from the run's own caveats)

- **Terminal diff rendering per framework**: no claims survived — resolve at
  build time (Rich `Syntax`/manual styling is the Textual-native option).
- **Packaging comparison** (uv tool vs static binary): unanswered; our
  existing `uv run --with textual` wrapper pattern already works; `uv tool
  install` is the upgrade path.
- No measured head-to-head throughput benchmark survived; the 10-30Hz story
  is architectural inference. Mitigation: MarkdownStream batching + our
  event-bus throttling.

## Open questions carried forward

1. Measured Textual cost at sustained 10-30 updates/sec over SSH/tmux.
2. Best diff-rendering approach in Textual (likely Rich Syntax + custom).
3. Crush/Claude Code code-level mechanics for progress trees + esc-interrupt.
4. `uv tool install` as the packaging step once the app stabilizes.

## Sources (21 fetched; key primaries)

textual.textualize.io (blog/guide/widgets/api) · k9scli.io ·
github.com/derailed/k9s · github.com/bjarneo/kli (ku) ·
github.com/opencode-ai/opencode · docs.rs/tui-markdown ·
github.com/celestia-island/ratatui-markdown · github.com/mikaelbr/marked-terminal ·
github.com/cameronhunter/ink-markdown · newsletter.pragmaticengineer.com
(Claude Code interview) · claude-code-from-source.com · dev.to/minnzen ·
wistrand/melker tui-comparison (blog-quality; claims re-anchored to PyPI +
official release notes by verifiers).
