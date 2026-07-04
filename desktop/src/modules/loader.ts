/**
 * M7.1 front-end contract: panels live at src/modules/<id>/Panel.tsx and are
 * discovered at build time; which ones RENDER is driven by the backend
 * manifest (GET /modules) at runtime. Dropping a folder in adds a panel with
 * zero core edits (M7.3).
 */
import { ComponentType, lazy } from "react";

const panelModules = import.meta.glob("./*/Panel.tsx") as Record<
  string,
  () => Promise<{ default: ComponentType<PanelProps> }>
>;

export interface ModuleManifestEntry {
  id: string;
  name: string;
  eventTypes: string[];
  panel: string | null;
  config?: Record<string, unknown>;
}

export interface PanelProps {
  /** events from the shared WS bus, filtered to this module's source id */
  events: import("@vault/shared/events").VaultEvent[];
  /** this module's manifest entry (id, name, config) */
  module?: ModuleManifestEntry;
}

/** panel id → lazy component (id = folder name) */
export const panelRegistry: Record<string, ComponentType<PanelProps>> =
  Object.fromEntries(
    Object.entries(panelModules).map(([path, load]) => [
      path.split("/")[1],
      lazy(load),
    ])
  );
