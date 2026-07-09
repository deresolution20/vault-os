import React from "react";
import ReactDOM from "react-dom/client";
import "./browser-guard.css";

function isTauriRuntime(): boolean {
  const globals = globalThis as typeof globalThis & {
    isTauri?: boolean;
    __TAURI_INTERNALS__?: { invoke?: unknown };
  };
  return Boolean(globals.isTauri || globals.__TAURI_INTERNALS__?.invoke);
}

function BrowserGuard() {
  return (
    <main className="browser-guard">
      <section className="browser-guard-panel">
        <div className="browser-guard-kicker">VAULT</div>
        <h1>Desktop shell required</h1>
        <p>
          This tab is Vite's asset server. Launch the UI through Tauri so VAULT
          can read local config and connect to the API.
        </p>
        <code>pnpm --filter vault-desktop tauri dev</code>
      </section>
    </main>
  );
}

async function boot() {
  const root = ReactDOM.createRoot(document.getElementById("root") as HTMLElement);
  if (!isTauriRuntime()) {
    root.render(
      <React.StrictMode>
        <BrowserGuard />
      </React.StrictMode>,
    );
    return;
  }

  // #deck renders the GPU Deck window; anything else is the main HUD.
  const { default: Root } =
    window.location.hash === "#deck" ? await import("./deck/DeckView") : await import("./App");

  root.render(
    <React.StrictMode>
      <Root />
    </React.StrictMode>,
  );
}

void boot();
