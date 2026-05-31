import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import type { OpenClawPluginToolContext } from "openclaw/plugin-sdk/plugin-entry";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-runtime";
import { jsonResult, readStringParam } from "openclaw/plugin-sdk/provider-web-search";
import { Type } from "typebox";
import { getGhlContact } from "./ghl-client.js";

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

const GhlGetContactSchema = Type.Object(
  {
    contactId: Type.String({ description: "GoHighLevel contact id." }),
  },
  { additionalProperties: false },
);

export function createGhlGetContactTool(api: OpenClawPluginApi, ctx?: GhlToolConfigContext) {
  return {
    name: "ghl_get_contact",
    label: "GHL Get Contact",
    description:
      "Fetch a single GoHighLevel (LeadConnector) contact by id. A missing contact returns { found: false } instead of raising an error.",
    parameters: GhlGetContactSchema,
    execute: async (_toolCallId: string, rawParams: Record<string, unknown>) => {
      const contactId = readStringParam(rawParams, "contactId", { required: true });
      return jsonResult(
        await getGhlContact({
          cfg: resolveGhlToolConfig(api, ctx),
          contactId,
        }),
      );
    },
  };
}
