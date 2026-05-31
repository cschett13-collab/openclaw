---
name: gohighlevel
description: "Look up and summarize existing GoHighLevel (LeadConnector) CRM contacts by email or ID."
homepage: https://marketplace.gohighlevel.com/docs/
metadata:
  {
    "openclaw":
      {
        "emoji": "📇",
        "requires":
          { "bins": ["node"], "env": ["GHL_PRIVATE_TOKEN", "GHL_LOCATION_ID"] },
      },
  }
---

# GoHighLevel Skill

Read-only access to existing GoHighLevel (LeadConnector) CRM contacts: fetch a contact
by email or ID and summarize their status from notes/fields. For managing records you
already own — not bulk lead import or outreach sequencing.

## Setup

1. Create a **Private Integration** token in your GHL location: Settings → Private Integrations.
2. Grant it the `contacts.readonly` scope.
3. Set environment variables:
   ```bash
   export GHL_PRIVATE_TOKEN="pit-..."   # Private Integration token
   export GHL_LOCATION_ID="..."         # required for email lookups
   # export GHL_API_VERSION="2021-07-28"  # override only if your app's docs differ
   ```

If `GHL_PRIVATE_TOKEN` is missing the script returns `{"error":"MISSING_TOKEN"}` and exits
non-zero — it never throws into the agent loop. Same for `429` (`RATE_LIMITED`, with
`retryAfter`) and HTTP errors (`HTTP_ERROR`, with status + body).

## Usage

All commands print JSON to stdout. Auth is `Authorization: Bearer $GHL_PRIVATE_TOKEN` plus
the `Version` header against `https://services.leadconnectorhq.com`.

### Fetch a contact by ID
```bash
node skills/gohighlevel/scripts/ghl.mjs get-by-id <contactId>
```

### Look up a contact by email
```bash
node skills/gohighlevel/scripts/ghl.mjs get-by-email someone@example.com
```
Uses the duplicate-search endpoint (`/contacts/search/duplicate`); requires `GHL_LOCATION_ID`.
Returns `{ "found": false }` when no contact matches.

### Summarize a contact's status
```bash
node skills/gohighlevel/scripts/ghl.mjs summarize <contactId|email>
```
Resolves the contact, pulls recent notes (best-effort), and returns a plain-text summary
of name/contact info, tags, dates, and the latest notes.

## Notes on the API

- Version header: docs list `2021-07-28` for contacts; the live marketplace renderer shows
  `2023-02-21`. The default is overridable via `GHL_API_VERSION` — confirm against your app.
- `GET /contacts/?query=` is deprecated; email lookup uses the duplicate-search endpoint.
- Scope is read-only by design. Status writes would be a separate, explicitly-scoped follow-up.
