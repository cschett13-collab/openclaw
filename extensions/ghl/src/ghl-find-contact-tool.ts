import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import type { OpenClawPluginToolContext } from "openclaw/plugin-sdk/plugin-entry";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-runtime";
import { jsonResult, readNumberParam, readStringParam } from "openclaw/plugin-sdk/provider-web-search";
import { Type } from "typebox";
import { findGhlContacts } from "./ghl-client.js";

type GhlToolConfigContext = Pick<
  OpenClawPluginToolContext,
  "config" | "runtimeConfig" | "getRuntimeConfig"
>;

function resolveGhlToolConfig(
  api: OpenClawPluginApi,
  ctx?: GhlToolConfigContext,
): OpenClawConfig {
  return ctx?.getRuntimeConfig?.() ?? ctx?.runtimeConfig ?? ctx?.config ?? api.config;
}

const GhlFindContactSchema = Type.Object(
  {
    email: Type.Optional(Type.String({ description: "Exact email to match." })),
    phone: Type.Optional(Type.String({ description: "Exact phone to match (E.164 preferred)." })),
    query: Type.Optional(
      Type.String({ description: "Free-text search across name/email/phone." }),
    ),
    limit: Type.Optional(
      Type.Number({ description: "Max results to return (1-100).", minimum: 1, maximum: 100 }),
    ),
  },
  { additionalProperties: false },
);

export function createGhlFindContactTool(api: OpenClawPluginApi, ctx?: GhlToolConfigContext) {
  return {
    name: "ghl_find_contact",
    label: "GHL Find Contact",
    description:
      "Search GoHighLevel (LeadConnector) contacts by email, phone, or free-text query. Returns { found, matches }; an empty result is reported cleanly, not as an error.",
    parameters: GhlFindContactSchema,
    execute: async (_toolCallId: string, rawParams: Record<string, unknown>) => {
      const email = readStringParam(rawParams, "email") || undefined;
      const phone = readStringParam(rawParams, "phone") || undefined;
      const query = readStringParam(rawParams, "query") || undefined;
      const limit = readNumberParam(rawParams, "limit", { integer: true });
      if (!email && !phone && !query) {
        throw new Error("ghl_find_contact requires at least one of: email, phone, query.");
      }
      return jsonResult(
        await findGhlContacts({
          cfg: resolveGhlToolConfig(api, ctx),
          email,
          phone,
          query,
          limit,
        }),
      );
    },
  };
}
