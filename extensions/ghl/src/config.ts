import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import {
  normalizeResolvedSecretInputString,
  normalizeSecretInput,
} from "openclaw/plugin-sdk/secret-input";

/** Trim a possibly-undefined string, returning undefined when blank. */
function normalizeOptionalString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

export const DEFAULT_GHL_BASE_URL = "https://services.leadconnectorhq.com";
// LeadConnector API v2 versioning header. Override only if the marketplace app
// requires a newer dated spec; mismatched versions can silently drop payload fields.
export const DEFAULT_GHL_API_VERSION = "2021-07-28";
export const DEFAULT_GHL_TIMEOUT_SECONDS = 30;

type GhlCrmConfig =
  | {
      apiKey?: unknown;
      locationId?: unknown;
      apiVersion?: string;
      baseUrl?: string;
    }
  | undefined;

type PluginEntryConfig = {
  crm?: {
    apiKey?: unknown;
    locationId?: unknown;
    apiVersion?: string;
    baseUrl?: string;
  };
};

export function resolveGhlCrmConfig(cfg?: OpenClawConfig): GhlCrmConfig {
  const pluginConfig = cfg?.plugins?.entries?.ghl?.config as PluginEntryConfig;
  const crm = pluginConfig?.crm;
  if (crm && typeof crm === "object" && !Array.isArray(crm)) {
    return crm;
  }
  return undefined;
}

function normalizeConfiguredSecret(value: unknown, path: string): string | undefined {
  return normalizeSecretInput(
    normalizeResolvedSecretInputString({
      value,
      path,
    }),
  );
}

/**
 * Private Integration Token, resolved config-first then env fallback. The token
 * is treated as a secret throughout (never logged or echoed back to the agent).
 */
export function resolveGhlApiKey(cfg?: OpenClawConfig): string | undefined {
  const crm = resolveGhlCrmConfig(cfg);
  return (
    normalizeConfiguredSecret(crm?.apiKey, "plugins.entries.ghl.config.crm.apiKey") ||
    normalizeSecretInput(process.env.GHL_API_KEY) ||
    undefined
  );
}

/**
 * Sub-account (location) id. Required by the search endpoint; optional for
 * id-scoped reads. Not a secret, so plain string coercion is fine.
 */
export function resolveGhlLocationId(cfg?: OpenClawConfig): string | undefined {
  const crm = resolveGhlCrmConfig(cfg);
  return (
    normalizeOptionalString(crm?.locationId as string | undefined) ??
    normalizeOptionalString(process.env.GHL_LOCATION_ID) ??
    undefined
  );
}

export function resolveGhlApiVersion(cfg?: OpenClawConfig): string {
  const crm = resolveGhlCrmConfig(cfg);
  const configured =
    (normalizeOptionalString(crm?.apiVersion) ?? "") ||
    normalizeOptionalString(process.env.GHL_API_VERSION) ||
    "";
  return configured || DEFAULT_GHL_API_VERSION;
}

export function resolveGhlBaseUrl(cfg?: OpenClawConfig): string {
  const crm = resolveGhlCrmConfig(cfg);
  const configured =
    (normalizeOptionalString(crm?.baseUrl) ?? "") ||
    normalizeOptionalString(process.env.GHL_BASE_URL) ||
    "";
  return configured || DEFAULT_GHL_BASE_URL;
}

export function resolveGhlTimeoutSeconds(override?: number): number {
  if (typeof override === "number" && Number.isFinite(override) && override > 0) {
    return Math.floor(override);
  }
  return DEFAULT_GHL_TIMEOUT_SECONDS;
}
