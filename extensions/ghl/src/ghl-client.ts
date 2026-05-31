import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import {
  readResponseText,
  withTrustedWebToolsEndpoint,
} from "openclaw/plugin-sdk/provider-web-search";
import { wrapExternalContent } from "openclaw/plugin-sdk/security-runtime";
import {
  DEFAULT_GHL_BASE_URL,
  resolveGhlApiKey,
  resolveGhlApiVersion,
  resolveGhlBaseUrl,
  resolveGhlLocationId,
  resolveGhlTimeoutSeconds,
} from "./config.js";

const MAX_RESPONSE_BYTES = 256_000;

export type GhlHttpResult = { status: number; payload: unknown };

type GhlRequestParams = {
  cfg?: OpenClawConfig;
  method: "GET" | "POST";
  path: string;
  query?: Record<string, string | undefined>;
  body?: Record<string, unknown>;
  timeoutSeconds?: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Build the v2 endpoint URL. Supports a bare host or a reverse-proxy path
 * prefix on the configured base URL, mirroring the search-plugin convention.
 */
export function buildGhlUrl(
  baseUrl: string,
  path: string,
  query?: Record<string, string | undefined>,
): string {
  const trimmedBase = (baseUrl || "").trim() || DEFAULT_GHL_BASE_URL;
  let url: URL;
  try {
    url = new URL(trimmedBase);
  } catch {
    url = new URL(DEFAULT_GHL_BASE_URL);
  }
  url.pathname = url.pathname.replace(/\/$/, "") + path;
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (typeof value === "string" && value.length > 0) {
        url.searchParams.set(key, value);
      }
    }
  }
  return url.toString();
}

/**
 * Every request carries the mandatory `Version` header. Without it the
 * LeadConnector v2 API silently drops fields, so it is never optional here.
 */
function buildGhlHeaders(apiKey: string, version: string, method: "GET" | "POST"): Record<string, string> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${apiKey}`,
    Version: version,
    Accept: "application/json",
  };
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

function missingApiKeyError(): Error {
  return new Error(
    "GoHighLevel tools need a Private Integration Token. Set GHL_API_KEY in the Gateway environment, or configure plugins.entries.ghl.config.crm.apiKey.",
  );
}

/**
 * Low-level request. Returns the parsed payload plus status so callers can
 * distinguish a real failure from an expected "not found". Does NOT throw on
 * HTTP status by itself — status interpretation is the caller's job.
 */
export async function ghlRequest(params: GhlRequestParams): Promise<GhlHttpResult> {
  const apiKey = resolveGhlApiKey(params.cfg);
  if (!apiKey) {
    throw missingApiKeyError();
  }
  const version = resolveGhlApiVersion(params.cfg);
  const baseUrl = resolveGhlBaseUrl(params.cfg);
  const url = buildGhlUrl(baseUrl, params.path, params.query);
  const timeoutSeconds = resolveGhlTimeoutSeconds(params.timeoutSeconds);

  return withTrustedWebToolsEndpoint(
    {
      url,
      timeoutSeconds,
      init: {
        method: params.method,
        headers: buildGhlHeaders(apiKey, version, params.method),
        ...(params.body ? { body: JSON.stringify(params.body) } : {}),
      },
    },
    async ({ response }) => {
      const detail = await readResponseText(response, { maxBytes: MAX_RESPONSE_BYTES });
      let payload: unknown;
      if (detail.text) {
        try {
          payload = JSON.parse(detail.text);
        } catch {
          payload = undefined;
        }
      }
      return { status: response.status, payload };
    },
  );
}

function throwGhlError(label: string, result: GhlHttpResult): never {
  const rec = isRecord(result.payload) ? result.payload : undefined;
  const message =
    (typeof rec?.message === "string" && rec.message) ||
    (typeof rec?.error === "string" && rec.error) ||
    "";
  throw new Error(`${label} API error (${result.status}): ${message || "unexpected response"}`);
}

function isOk(status: number): boolean {
  return status >= 200 && status < 300;
}

/**
 * GHL signals a missing record in more than one way depending on the endpoint:
 * a 404, or a 200 body carrying `found: false`. Both collapse to "not found"
 * so the agent loop gets a clean status instead of an exception.
 */
export function interpretNotFound(result: GhlHttpResult): boolean {
  if (result.status === 404) {
    return true;
  }
  const rec = isRecord(result.payload) ? result.payload : undefined;
  return rec?.found === false;
}

function wrapContactString(value: unknown): string | undefined {
  if (typeof value !== "string" || value.length === 0) {
    return undefined;
  }
  return wrapExternalContent(value, { source: "contact", includeWarning: false });
}

type NormalizedContact = Record<string, unknown>;

/** Project a GHL contact into a compact, safety-wrapped shape for the agent. */
export function normalizeContact(raw: unknown): NormalizedContact | undefined {
  const rec = isRecord(raw) ? raw : undefined;
  if (!rec) {
    return undefined;
  }
  const out: NormalizedContact = {};
  if (typeof rec.id === "string") {
    out.id = rec.id;
  }
  const name = wrapContactString(rec.contactName ?? rec.name);
  if (name) {
    out.name = name;
  }
  const firstName = wrapContactString(rec.firstName);
  if (firstName) {
    out.firstName = firstName;
  }
  const lastName = wrapContactString(rec.lastName);
  if (lastName) {
    out.lastName = lastName;
  }
  const email = wrapContactString(rec.email);
  if (email) {
    out.email = email;
  }
  const phone = wrapContactString(rec.phone);
  if (phone) {
    out.phone = phone;
  }
  if (Array.isArray(rec.tags)) {
    out.tags = (rec.tags as unknown[])
      .map((tag) => wrapContactString(tag))
      .filter((tag): tag is string => Boolean(tag));
  }
  if (typeof rec.dateAdded === "string") {
    out.dateAdded = rec.dateAdded;
  }
  return out;
}

const NOT_FOUND_SOURCE = {
  untrusted: true,
  source: "ghl",
  provider: "ghl",
  wrapped: true,
} as const;

export type GhlFindContactParams = {
  cfg?: OpenClawConfig;
  email?: string;
  phone?: string;
  query?: string;
  limit?: number;
};

/**
 * POST /contacts/search. An empty `contacts` array is a normal "no match"
 * (HTTP 200), not an error.
 */
export async function findGhlContacts(
  params: GhlFindContactParams,
): Promise<Record<string, unknown>> {
  const locationId = resolveGhlLocationId(params.cfg);
  if (!locationId) {
    throw new Error(
      "ghl_find_contact needs a location id. Set GHL_LOCATION_ID in the Gateway environment, or configure plugins.entries.ghl.config.crm.locationId.",
    );
  }
  const pageLimit =
    typeof params.limit === "number" && Number.isFinite(params.limit)
      ? Math.max(1, Math.min(100, Math.floor(params.limit)))
      : 10;

  const filters: Record<string, unknown>[] = [];
  if (params.email) {
    filters.push({ field: "email", operator: "eq", value: params.email });
  }
  if (params.phone) {
    filters.push({ field: "phone", operator: "eq", value: params.phone });
  }

  const body: Record<string, unknown> = { locationId, pageLimit };
  if (filters.length > 0) {
    body.filters = filters;
  }
  if (params.query) {
    body.query = params.query;
  }

  const result = await ghlRequest({
    cfg: params.cfg,
    method: "POST",
    path: "/contacts/search",
    body,
  });
  if (!isOk(result.status)) {
    throwGhlError("GHL Search Contacts", result);
  }
  const payload = isRecord(result.payload) ? result.payload : {};
  const rawContacts = Array.isArray(payload.contacts) ? payload.contacts : [];
  const matches = rawContacts
    .map((contact) => normalizeContact(contact))
    .filter((contact): contact is NormalizedContact => Boolean(contact));
  const total = typeof payload.total === "number" ? payload.total : matches.length;

  return {
    provider: "ghl",
    found: matches.length > 0,
    count: matches.length,
    total,
    externalContent: NOT_FOUND_SOURCE,
    matches,
  };
}

export type GhlGetContactParams = {
  cfg?: OpenClawConfig;
  contactId: string;
};

/** GET /contacts/{id}. A 404 (or `found:false`) is returned as a clean status. */
export async function getGhlContact(
  params: GhlGetContactParams,
): Promise<Record<string, unknown>> {
  const result = await ghlRequest({
    cfg: params.cfg,
    method: "GET",
    path: `/contacts/${encodeURIComponent(params.contactId)}`,
  });
  if (interpretNotFound(result)) {
    return {
      provider: "ghl",
      found: false,
      reason: "no_match",
      contactId: params.contactId,
    };
  }
  if (!isOk(result.status)) {
    throwGhlError("GHL Get Contact", result);
  }
  const payload = isRecord(result.payload) ? result.payload : {};
  const contact = normalizeContact(payload.contact);
  if (!contact) {
    return {
      provider: "ghl",
      found: false,
      reason: "no_match",
      contactId: params.contactId,
    };
  }
  return {
    provider: "ghl",
    found: true,
    externalContent: NOT_FOUND_SOURCE,
    contact,
  };
}

export type GhlAddNoteParams = {
  cfg?: OpenClawConfig;
  contactId: string;
  body: string;
  userId?: string;
};

/** POST /contacts/{id}/notes. Missing contact returns a clean status, not a throw. */
export async function addGhlContactNote(
  params: GhlAddNoteParams,
): Promise<Record<string, unknown>> {
  const requestBody: Record<string, unknown> = { body: params.body };
  if (params.userId) {
    requestBody.userId = params.userId;
  }
  const result = await ghlRequest({
    cfg: params.cfg,
    method: "POST",
    path: `/contacts/${encodeURIComponent(params.contactId)}/notes`,
    body: requestBody,
  });
  if (interpretNotFound(result)) {
    return {
      provider: "ghl",
      ok: false,
      reason: "contact_not_found",
      contactId: params.contactId,
    };
  }
  if (!isOk(result.status)) {
    throwGhlError("GHL Create Note", result);
  }
  const payload = isRecord(result.payload) ? result.payload : {};
  const note = isRecord(payload.note) ? payload.note : undefined;
  return {
    provider: "ghl",
    ok: true,
    status: "created",
    contactId: params.contactId,
    ...(typeof note?.id === "string" ? { noteId: note.id } : {}),
  };
}

export const __testing = {
  buildGhlUrl,
  buildGhlHeaders,
  interpretNotFound,
  normalizeContact,
};
