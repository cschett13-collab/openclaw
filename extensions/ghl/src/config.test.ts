import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_GHL_API_VERSION,
  DEFAULT_GHL_BASE_URL,
  resolveGhlApiKey,
  resolveGhlApiVersion,
  resolveGhlBaseUrl,
  resolveGhlLocationId,
  resolveGhlTimeoutSeconds,
} from "./config.js";

function cfgWithCrm(crm: Record<string, unknown>): OpenClawConfig {
  return { plugins: { entries: { ghl: { config: { crm } } } } } as unknown as OpenClawConfig;
}

const ENV_KEYS = ["GHL_API_KEY", "GHL_LOCATION_ID", "GHL_API_VERSION", "GHL_BASE_URL"] as const;

describe("ghl config resolution", () => {
  const saved: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const key of ENV_KEYS) {
      saved[key] = process.env[key];
      delete process.env[key];
    }
  });

  afterEach(() => {
    for (const key of ENV_KEYS) {
      if (saved[key] === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = saved[key];
      }
    }
  });

  it("prefers configured api key over env", () => {
    process.env.GHL_API_KEY = "env-token";
    expect(resolveGhlApiKey(cfgWithCrm({ apiKey: "cfg-token" }))).toBe("cfg-token");
  });

  it("falls back to env api key when config absent", () => {
    process.env.GHL_API_KEY = "env-token";
    expect(resolveGhlApiKey(undefined)).toBe("env-token");
  });

  it("returns undefined when no api key anywhere", () => {
    expect(resolveGhlApiKey(undefined)).toBeUndefined();
  });

  it("resolves location id from config then env", () => {
    expect(resolveGhlLocationId(cfgWithCrm({ locationId: "loc-1" }))).toBe("loc-1");
    process.env.GHL_LOCATION_ID = "loc-env";
    expect(resolveGhlLocationId(undefined)).toBe("loc-env");
  });

  it("defaults the api version and allows override", () => {
    expect(resolveGhlApiVersion(undefined)).toBe(DEFAULT_GHL_API_VERSION);
    expect(resolveGhlApiVersion(cfgWithCrm({ apiVersion: "2023-02-21" }))).toBe("2023-02-21");
    process.env.GHL_API_VERSION = "2099-01-01";
    expect(resolveGhlApiVersion(undefined)).toBe("2099-01-01");
  });

  it("defaults the base url and allows override", () => {
    expect(resolveGhlBaseUrl(undefined)).toBe(DEFAULT_GHL_BASE_URL);
    expect(resolveGhlBaseUrl(cfgWithCrm({ baseUrl: "https://proxy.example/ghl" }))).toBe(
      "https://proxy.example/ghl",
    );
  });

  it("clamps timeout to a positive integer with a default", () => {
    expect(resolveGhlTimeoutSeconds(undefined)).toBe(30);
    expect(resolveGhlTimeoutSeconds(0)).toBe(30);
    expect(resolveGhlTimeoutSeconds(12.7)).toBe(12);
  });
});
