#!/usr/bin/env node
// Read-only GoHighLevel (LeadConnector) CRM helper for the `gohighlevel` skill.
// Node 22+, zero dependencies (uses global fetch).
//
// Every failure path returns structured JSON on stdout and a non-zero exit code instead
// of throwing — a missing token, a 429, or an HTTP error must not crash the agent loop.

const BASE = "https://services.leadconnectorhq.com";

// GHL versions its endpoints by date and sources disagree on the current value for contacts
// (docs: 2021-07-28; live marketplace renderer: 2023-02-21). Overridable; confirm against the
// docs for your app. 2021-04-15 is not attested for the contacts endpoints.
const VERSION = process.env.GHL_API_VERSION || "2021-07-28";

function emit(obj, code = 0) {
  process.stdout.write(JSON.stringify(obj, null, 2) + "\n");
  process.exit(code);
}

function fail(error, message, extra = {}, code = 1) {
  return emit({ ok: false, error, message, ...extra }, code);
}

function getConfig() {
  const token =
    process.env.GHL_PRIVATE_TOKEN ||
    process.env.GHL_ACCESS_TOKEN ||
    process.env.GHL_API_KEY ||
    "";
  return { token, locationId: process.env.GHL_LOCATION_ID || "" };
}

// soft=true returns an { _error } object instead of exiting, for best-effort calls.
async function ghlFetch(path, { soft = false } = {}) {
  const { token } = getConfig();
  if (!token) {
    if (soft) return { _error: "MISSING_TOKEN" };
    return fail(
      "MISSING_TOKEN",
      "Set GHL_PRIVATE_TOKEN (a GHL Private Integration token) before using this skill.",
      {},
      2,
    );
  }

  let res;
  try {
    res = await fetch(BASE + path, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        Version: VERSION,
        Accept: "application/json",
      },
    });
  } catch (e) {
    const message = `Could not reach GHL: ${String(e?.message || e)}`;
    if (soft) return { _error: "NETWORK", message };
    return fail("NETWORK", message);
  }

  if (res.status === 429) {
    const retryAfter = res.headers.get("retry-after");
    if (soft) return { _error: "RATE_LIMITED", retryAfter };
    return fail(
      "RATE_LIMITED",
      `GHL rate limit hit (429). Retry after ${retryAfter ?? "a short delay"}.`,
      { retryAfter },
    );
  }

  const text = await res.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { raw: text };
  }

  if (!res.ok) {
    if (soft) return { _error: "HTTP_ERROR", status: res.status, body };
    return fail("HTTP_ERROR", `GHL returned ${res.status} for ${path}.`, {
      status: res.status,
      body,
    });
  }

  return body;
}

function buildSummary(c, notes) {
  const name =
    [c.firstName, c.lastName].filter(Boolean).join(" ") ||
    c.contactName ||
    c.name ||
    "(no name)";
  const lines = [
    `${name} — ${c.email ?? "no email"}${c.phone ? ` / ${c.phone}` : ""}`,
  ];
  if (Array.isArray(c.tags) && c.tags.length) lines.push(`Tags: ${c.tags.join(", ")}`);
  if (c.dateAdded) lines.push(`Added: ${c.dateAdded}`);
  if (c.lastActivity) lines.push(`Last activity: ${c.lastActivity}`);

  const recent = (notes || []).slice(0, 5).map((n) => {
    const when = n.dateAdded || n.createdAt || "";
    const bodyText = String(n.body || "").replace(/\s+/g, " ").trim();
    return `  • ${when ? `${when}: ` : ""}${bodyText.slice(0, 200)}`;
  });
  if (recent.length) {
    lines.push(`Recent notes (${notes.length} total):`, ...recent);
  } else {
    lines.push("No notes on record.");
  }
  return lines.join("\n");
}

async function resolveContact(arg) {
  if (arg.includes("@")) {
    const { locationId } = getConfig();
    if (!locationId) {
      return fail(
        "MISSING_LOCATION",
        "Set GHL_LOCATION_ID to look up contacts by email.",
        {},
        2,
      );
    }
    const q = new URLSearchParams({ locationId, email: arg });
    const d = await ghlFetch(`/contacts/search/duplicate?${q}`);
    return d.contact ?? null;
  }
  const d = await ghlFetch(`/contacts/${encodeURIComponent(arg)}`);
  return d.contact ?? d;
}

async function main() {
  const [cmd, arg] = process.argv.slice(2);

  switch (cmd) {
    case "get-by-id": {
      if (!arg) return fail("USAGE", "Usage: ghl.mjs get-by-id <contactId>", {}, 64);
      const data = await ghlFetch(`/contacts/${encodeURIComponent(arg)}`);
      return emit({ ok: true, contact: data.contact ?? data });
    }
    case "get-by-email": {
      if (!arg) return fail("USAGE", "Usage: ghl.mjs get-by-email <email>", {}, 64);
      const contact = await resolveContact(arg);
      return emit({ ok: true, found: Boolean(contact), contact: contact ?? null });
    }
    case "summarize": {
      if (!arg) return fail("USAGE", "Usage: ghl.mjs summarize <contactId|email>", {}, 64);
      const contact = await resolveContact(arg);
      if (!contact) return emit({ ok: true, found: false, summary: `No GHL contact found for ${arg}.` });
      let notes = [];
      const n = await ghlFetch(`/contacts/${contact.id}/notes`, { soft: true });
      if (!n._error && Array.isArray(n.notes)) notes = n.notes;
      return emit({ ok: true, found: true, contactId: contact.id, summary: buildSummary(contact, notes) });
    }
    default:
      return fail(
        "USAGE",
        "Commands: get-by-id <id> | get-by-email <email> | summarize <id|email>",
        {},
        64,
      );
  }
}

main().catch((e) => fail("UNEXPECTED", String(e?.message || e)));
