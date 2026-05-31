#!/usr/bin/env node
// Live smoke test for the GoHighLevel plugin against the real LeadConnector API.
//
// This exercises the SAME request shaping the plugin uses (headers, Version,
// endpoints, graceful not-found handling) but with plain fetch so it can run
// standalone without building the whole project.
//
// Usage:
//   GHL_API_KEY=pit-... GHL_LOCATION_ID=your-loc \
//     node extensions/ghl/scripts/live-smoke.mjs [--email someone@example.com] [--contact-id ID] [--note "text"]
//
// Nothing is written unless you pass --note together with --contact-id.

const BASE = (process.env.GHL_BASE_URL || "https://services.leadconnectorhq.com").replace(
  /\/$/,
  "",
);
const VERSION = process.env.GHL_API_VERSION || "2021-07-28";
const TOKEN = process.env.GHL_API_KEY;
const LOCATION = process.env.GHL_LOCATION_ID;

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const email = arg("--email");
const contactId = arg("--contact-id");
const note = arg("--note");

function headers(method) {
  const h = {
    Authorization: `Bearer ${TOKEN}`,
    Version: VERSION,
    Accept: "application/json",
  };
  if (method === "POST") h["Content-Type"] = "application/json";
  return h;
}

async function call(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: headers(method),
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  let payload;
  const text = await res.text();
  try {
    payload = text ? JSON.parse(text) : undefined;
  } catch {
    payload = text;
  }
  return { status: res.status, payload };
}

function line(label, value) {
  console.log(`  ${label.padEnd(18)} ${value}`);
}

async function main() {
  if (!TOKEN) {
    console.error("✗ GHL_API_KEY is required (Private Integration Token).");
    process.exit(2);
  }
  if (!LOCATION) {
    console.error("✗ GHL_LOCATION_ID is required (sub-account location id).");
    process.exit(2);
  }

  console.log(`\nGoHighLevel live smoke  base=${BASE}  version=${VERSION}\n`);

  // 1. Search contacts (ghl_find_contact)
  console.log("1) POST /contacts/search");
  const searchBody = { locationId: LOCATION, pageLimit: 5 };
  if (email) searchBody.filters = [{ field: "email", operator: "eq", value: email }];
  const search = await call("POST", "/contacts/search", searchBody);
  line("status", search.status);
  if (search.status >= 200 && search.status < 300) {
    const rec = search.payload && typeof search.payload === "object" ? search.payload : {};
    const contacts = Array.isArray(rec.contacts) ? rec.contacts : [];
    line("response keys", Object.keys(rec).join(", ") || "(none)");
    line("contacts found", contacts.length);
    line("total field", "total" in rec ? rec.total : "(absent — code falls back to count)");
    if (contacts[0]) {
      line("first id", contacts[0].id ?? "(no id key)");
      line("contact keys", Object.keys(contacts[0]).slice(0, 12).join(", "));
    }
  } else {
    line("error", JSON.stringify(search.payload));
  }

  // 2. Get contact by id (ghl_get_contact) — only if we have an id
  const idToGet = contactId || search.payload?.contacts?.[0]?.id;
  if (idToGet) {
    console.log(`\n2) GET /contacts/${idToGet}`);
    const get = await call("GET", `/contacts/${encodeURIComponent(idToGet)}`);
    line("status", get.status);
    if (get.status === 404) {
      line("interpreted", "not found (404) → { found: false }");
    } else if (get.status >= 200 && get.status < 300) {
      const rec = get.payload && typeof get.payload === "object" ? get.payload : {};
      line("response keys", Object.keys(rec).join(", "));
      line(
        "contact key?",
        "contact" in rec ? "yes (code reads payload.contact)" : "NO — adjust normalizeContact",
      );
    } else {
      line("error", JSON.stringify(get.payload));
    }

    // 3. Add a note (ghl_add_contact_note) — ONLY when --note is given
    if (note) {
      console.log(`\n3) POST /contacts/${idToGet}/notes  (WRITE)`);
      const add = await call("POST", `/contacts/${encodeURIComponent(idToGet)}/notes`, {
        body: note,
      });
      line("status", add.status);
      const rec = add.payload && typeof add.payload === "object" ? add.payload : {};
      line("response keys", Object.keys(rec).join(", "));
      line(
        "note.id present?",
        rec.note?.id ? `yes (${rec.note.id})` : "NO — adjust note-id extraction",
      );
    } else {
      console.log('\n3) (skipped note write — pass --note "text" to test ghl_add_contact_note)');
    }
  } else {
    console.log(
      "\n2/3) (skipped — no contact id available; pass --contact-id or an --email that matches)",
    );
  }

  console.log("\nDone. Compare 'response keys' above against the plugin's assumptions:");
  console.log("  search → contacts[], total ;  get → contact ;  note → note.id\n");
}

main().catch((err) => {
  console.error("✗ live smoke failed:", err?.message || err);
  process.exit(1);
});
