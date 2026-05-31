import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { createGhlAddNoteTool } from "./src/ghl-add-note-tool.js";
import { createGhlFindContactTool } from "./src/ghl-find-contact-tool.js";
import { createGhlGetContactTool } from "./src/ghl-get-contact-tool.js";

export default definePluginEntry({
  id: "ghl",
  name: "GoHighLevel Plugin",
  description: "Bundled GoHighLevel (LeadConnector) CRM contact and note tools",
  register(api) {
    api.registerTool((ctx) => createGhlFindContactTool(api, ctx), { name: "ghl_find_contact" });
    api.registerTool((ctx) => createGhlGetContactTool(api, ctx), { name: "ghl_get_contact" });
    api.registerTool((ctx) => createGhlAddNoteTool(api, ctx), { name: "ghl_add_contact_note" });
  },
});
