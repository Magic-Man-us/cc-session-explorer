import { createContext, useContext, type ReactNode } from "react";

export type ProviderScope = "all" | "claude" | "codex";

const STORAGE_KEY = "cc-session-explorer-provider";
const ProviderScopeContext = createContext<ProviderScope>("all");

export const PROVIDER_OPTIONS = [
  { value: "all", label: "Both" },
  { value: "claude", label: "Claude Code" },
  { value: "codex", label: "Codex" },
] satisfies { value: ProviderScope; label: string }[];

export const providerLabel = (provider: ProviderScope): string =>
  PROVIDER_OPTIONS.find((option) => option.value === provider)?.label ?? "Both";

export function initialProviderScope(): ProviderScope {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored === "claude" || stored === "codex" ? stored : "all";
  } catch {
    return "all";
  }
}

export function rememberProviderScope(provider: ProviderScope): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, provider);
  } catch {
    // A private/locked-down browser can reject storage; the in-memory selection still works.
  }
}

export function ProviderScopeProvider({
  provider,
  children,
}: {
  provider: ProviderScope;
  children: ReactNode;
}) {
  return (
    <ProviderScopeContext.Provider value={provider}>
      {children}
    </ProviderScopeContext.Provider>
  );
}

export const useProviderScope = (): ProviderScope => useContext(ProviderScopeContext);
