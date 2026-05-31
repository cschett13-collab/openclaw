---
name: ghl
description: GoHighLevel (LeadConnector) CRM contact lookup and note tools.
metadata:
  { "openclaw": { "emoji": "📇", "requires": { "config": ["plugins.entries.ghl.enabled"] } } }
---

# GoHighLevel Tools

Read-leaning contact tooling for the GoHighLevel / LeadConnector v2 API. Auth is
a Private Integration Token sent as a Bearer credential; every request carries
the `Version` header so the API does not silently drop fields.

## Setup

| Setting | Config key | Env fallback |
| ------- | ---------- | ------------ |
| Token (secret) | `plugins.entries.ghl.config.crm.apiKey` | `GHL_API_KEY` |
| Location id | `plugins.entries.ghl.config.crm.locationId` | `GHL_LOCATION_ID` |
| API version | `plugins.entries.ghl.config.crm.apiVersion` | `GHL_API_VERSION` (default `2021-07-28`) |
| Base URL | `plugins.entries.ghl.config.crm.baseUrl` | `GHL_BASE_URL` |

## When to use which tool

| Need | Tool |
| ---- | ---- |
| Find a contact by email/phone/text | `ghl_find_contact` |
| Fetch one contact by id | `ghl_get_contact` |
| Attach a note to a contact | `ghl_add_contact_note` |

## ghl_find_contact

`POST /contacts/search`. Requires a location id and at least one of `email`,
`phone`, or `query`.

| Parameter | Description |
| --------- | ----------- |
| `email` | Exact email to match |
| `phone` | Exact phone to match (E.164 preferred) |
| `query` | Free-text search across name/email/phone |
| `limit` | Max results, 1-100 (default 10) |

Returns `{ found, count, total, matches }`. No match is a normal `found: false`
result, not an error.

## ghl_get_contact

`GET /contacts/{contactId}`. Returns `{ found: true, contact }` or, when the id
does not exist, `{ found: false, reason: "no_match" }` — never an exception.

## ghl_add_contact_note

`POST /contacts/{contactId}/notes`.

| Parameter | Description |
| --------- | ----------- |
| `contactId` | Contact to attach the note to |
| `body` | Note text |
| `userId` | Optional GHL user id to attribute the note to |

Returns `{ ok: true, status: "created", noteId }`. If the contact is missing,
returns `{ ok: false, reason: "contact_not_found" }`.

## Error model

- Missing contact / empty search → clean status payload (no throw).
- Auth (401/403), rate limit (429), and server (5xx) errors throw with an
  actionable message, since those are operator-fixable rather than agent-loop
  noise.
- Contact field values are wrapped as untrusted external content before they
  reach the agent.
