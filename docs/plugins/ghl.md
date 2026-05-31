---
summary: "GoHighLevel plugin: look up LeadConnector CRM contacts and add notes from an OpenClaw agent"
read_when:
  - You want an OpenClaw agent to find a GoHighLevel (LeadConnector) contact by email, phone, or text
  - You want an OpenClaw agent to fetch a single GoHighLevel contact by id
  - You want an OpenClaw agent to add a note to a GoHighLevel contact
  - You are configuring a GoHighLevel Private Integration Token for OpenClaw
title: "GoHighLevel plugin"
---

GoHighLevel (LeadConnector) CRM support for OpenClaw. The plugin is read-leaning
by design: it looks up contacts and adds notes, and it never deletes or bulk-edits
records.

- Three agent tools: `ghl_find_contact`, `ghl_get_contact`, and
  `ghl_add_contact_note`.
- Auth is a GoHighLevel **Private Integration Token (PIT)** used as a Bearer
  credential. No interactive OAuth.
- Every request sends the mandatory `Version` header (default `2021-07-28`) so
  the LeadConnector v2 API does not silently drop response fields.
- A missing contact or empty search comes back as a clean status payload, not an
  exception. Auth, rate-limit, and server errors still surface as real errors.
- Contact field values are wrapped as untrusted external content before they
  reach the agent.

## Quick start

Create a Private Integration Token in your GoHighLevel sub-account
(Settings → Private Integrations) with contact read and note write scopes, then
provide it plus the sub-account (location) id:

```bash
export GHL_API_KEY=pit-...
export GHL_LOCATION_ID=your-location-id
```

Enable the plugin and the tools become available to the agent.

## Configuration

Credentials resolve **config first, environment second**. The token is treated
as a secret and is never logged or echoed back to the agent.

| Setting                            | Config key                                  | Environment fallback | Default                                |
| ---------------------------------- | ------------------------------------------- | -------------------- | -------------------------------------- |
| Private Integration Token (secret) | `plugins.entries.ghl.config.crm.apiKey`     | `GHL_API_KEY`        | —                                      |
| Sub-account (location) id          | `plugins.entries.ghl.config.crm.locationId` | `GHL_LOCATION_ID`    | —                                      |
| API version header                 | `plugins.entries.ghl.config.crm.apiVersion` | `GHL_API_VERSION`    | `2021-07-28`                           |
| Base URL                           | `plugins.entries.ghl.config.crm.baseUrl`    | `GHL_BASE_URL`       | `https://services.leadconnectorhq.com` |

The location id is required for `ghl_find_contact`. If your marketplace app
requires a newer dated spec, set `apiVersion` (for example `2023-02-21`) without
touching code.

## Tools

### `ghl_find_contact`

Search contacts with `POST /contacts/search`. Requires a location id and at least
one of `email`, `phone`, or `query`.

| Parameter | Description                                    |
| --------- | ---------------------------------------------- |
| `email`   | Exact email to match                           |
| `phone`   | Exact phone to match (E.164 preferred)         |
| `query`   | Free-text search across name, email, and phone |
| `limit`   | Maximum results, 1-100 (default 10)            |

Returns `{ found, count, total, matches }`. No match is a normal
`found: false` result, not an error.

### `ghl_get_contact`

Fetch one contact with `GET /contacts/{contactId}`.

| Parameter   | Description            |
| ----------- | ---------------------- |
| `contactId` | GoHighLevel contact id |

Returns `{ found: true, contact }`, or `{ found: false, reason: "no_match" }`
when the id does not exist.

### `ghl_add_contact_note`

Add a note with `POST /contacts/{contactId}/notes`.

| Parameter   | Description                                           |
| ----------- | ----------------------------------------------------- |
| `contactId` | Contact to attach the note to                         |
| `body`      | Note text                                             |
| `userId`    | Optional GoHighLevel user id to attribute the note to |

Returns `{ ok: true, status: "created", noteId }`. If the contact is missing,
returns `{ ok: false, reason: "contact_not_found" }`.

## Error handling

- A missing contact or empty search result is reported as a clean status payload
  so the agent loop continues normally.
- Authentication (`401`/`403`), rate limiting (`429`), and server (`5xx`) errors
  raise an actionable error, since those are operator-fixable rather than agent
  noise.
- All contact field values are wrapped as untrusted external content before they
  reach the agent.
