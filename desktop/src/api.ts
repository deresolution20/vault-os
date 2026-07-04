/** Front-end client for the Hermes API (config bootstrapped from Rust). */
import { invoke } from "@tauri-apps/api/core";
import type { VaultGraph, VaultEvent } from "@vault/shared/events";

export interface AppConfig {
  apiUrl: string;
  wsUrl: string;
  token: string;
  vaultPath: string;
}

let config: AppConfig | null = null;

export async function getConfig(): Promise<AppConfig> {
  if (!config) config = await invoke<AppConfig>("get_config");
  return config;
}

async function authed(path: string, init?: RequestInit): Promise<Response> {
  const cfg = await getConfig();
  const res = await fetch(`${cfg.apiUrl}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${cfg.token}`,
    },
  });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res;
}

export async function fetchGraph(): Promise<VaultGraph> {
  return (await authed("/graph")).json();
}

export async function fetchModules(): Promise<
  import("./modules/loader").ModuleManifestEntry[]
> {
  return (await authed("/modules")).json();
}

export async function readNote(absPath: string): Promise<string> {
  return invoke<string>("read_note", { path: absPath });
}

/** Subscribe to the live event bus; returns an unsubscribe fn. */
export function subscribeEvents(
  onEvent: (e: VaultEvent) => void,
  onStatus?: (connected: boolean) => void
): () => void {
  let ws: WebSocket | null = null;
  let closed = false;

  const connect = async () => {
    const cfg = await getConfig();
    ws = new WebSocket(`${cfg.wsUrl}?token=${encodeURIComponent(cfg.token)}`);
    ws.onopen = () => onStatus?.(true);
    ws.onmessage = (m) => {
      try {
        onEvent(JSON.parse(m.data));
      } catch {
        /* non-JSON frame — ignore */
      }
    };
    ws.onclose = () => {
      onStatus?.(false);
      if (!closed) setTimeout(connect, 2000); // sidecar may still be booting
    };
  };
  connect();

  return () => {
    closed = true;
    ws?.close();
  };
}
