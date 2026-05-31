import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import type { OpenClawPluginToolContext } from "openclaw/plugin-sdk/plugin-entry";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-runtime";
import { jsonResult, readStringParam } from "openclaw/plugin-sdk/provider-web-search";
import { Type } from "typebox";
import { addGhlContactNote } from "./ghl-client.js";

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

const GhlAddNoteSchema = Type.Object(
  {
    contactId: Type.String({ description: "GoHighLevel contact id to attach the note to." }),
    body: Type.String({ description: "Note text content." }),
    userId: Type.Optional(
      Type.String({ description: "Optional GHL user id to attribute the note to." }),
    ),
  },
  { additionalProperties: false },
);

export function createGhlAddNoteTool(api: OpenClawPluginApi, ctx?: GhlToolConfigContext) {
  return {
    name: "ghl_add_contact_note",
    label: "GHL Add Contact Note",
    description:
      "Add a note to a GoHighLevel (LeadConnector) contact. If the contact does not exist, returns { ok: false, reason: 'contact_not_found' } rather than erroring.",
    parameters: GhlAddNoteSchema,
    execute: async (_toolCallId: string, rawParams: Record<string, unknown>) => {
      const contactId = readStringParam(rawParams, "contactId", { required: true });
      const body = readStringParam(rawParams, "body", { required: true });
      const userId = readStringParam(rawParams, "userId") || undefined;
      return jsonResult(
        await addGhlContactNote({
          cfg: resolveGhlToolConfig(api, ctx),
          contactId,
          body,
          userId,
        }),
      );
    },
  };
}
