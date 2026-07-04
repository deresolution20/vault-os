# TUI framework decision — **Textual (Python)** (2026-07-04)

## Verdict

Build the VAULT daily-driver TUI (`vault`) on **Python Textual 8.x**,
extending the existing `tools/vault_top.py` prototype. The Tauri HUD stays
in-repo as optional eye-candy.

## Rationale (traced to RESEARCH-2026-07-04-vault-tui.md)

1. Every hard requirement has a **verified first-party answer** in Textual:
   damage-limited flicker-free compositor (finding 1), Worker API with
   exclusive-cancellation for esc-interrupt (finding 2), MarkdownStream
   coalescing designed for exactly our 10–30 updates/sec streaming-transcript
   regime (finding 3).
2. The **alternatives fail on the streaming-markdown story**: ratatui's
   options are experimental PoCs with hardcoded themes/odd licenses
   (finding 5); Ink's wrapper is stale (finding 6); and the "Claude Code uses
   Ink so we should too" argument was refuted — they forked and rewrote the
   renderer (finding 7).
3. **Stack fit**: Python 3.12 + uv already ship it; the prototype exists;
   the FastAPI/WS backend is the same language; no new toolchain in the
   critical path.
4. **Cost of being wrong is low**: the TUI talks only to the REST/WS API, so
   a future rewrite (e.g. ratatui once its ecosystem matures) swaps the shell,
   not the system.

## Accepted risks

- **Single maintainer** (Will McGugan) since Textualize wound down — 18
  months of steady releases since; monitored, and the thin-client design
  caps the blast radius.
- **No measured 10–30Hz SSH benchmark exists** — we rely on MarkdownStream
  batching + our own event throttling; if tmux flicker appears, DEC mode 2026
  passthrough (tmux PR #4744) is the knob.
- **Diff rendering** has no off-the-shelf Textual widget — use Rich `Syntax`
  with `lexer="diff"` + custom coloring (gap acknowledged by the research).

## Patterns adopted (from verified precedents)

- **k9s**: live dashboard home + Enter-to-drill-down + `/` filter.
- **ku/lazygit**: multi-pane, Tab cycling, always-visible context keybar.
- **Claude Code / Crush**: streaming transcript pane, esc-interrupt (mapped
  to `@work(exclusive=True)` + task-runner `/cancel`), bottom prompt line
  with slash-commands.
