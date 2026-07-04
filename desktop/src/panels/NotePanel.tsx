/** M3.4 — clicked node's markdown, rendered in a HUD side panel. */
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { readNote } from "../api";
import type { FgNode } from "../graph/VaultGraph";

export default function NotePanel({
  node,
  onClose,
}: {
  node: FgNode | null;
  onClose: () => void;
}) {
  const [content, setContent] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    setContent("");
    setError("");
    if (!node || node.unresolved || !node.path) return;
    readNote(node.path).then(setContent).catch((e) => setError(String(e)));
  }, [node]);

  if (!node) return null;

  return (
    <aside className="note-panel">
      <header>
        <span className="note-title">{node.title}</span>
        <button className="note-close" onClick={onClose}>
          ✕
        </button>
      </header>
      <div className="note-meta">{node.id}</div>
      <div className="note-body">
        {node.unresolved ? (
          <em>ghost node — no note exists yet for “{node.title}”</em>
        ) : error ? (
          <em className="bad">{error}</em>
        ) : (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        )}
      </div>
    </aside>
  );
}
