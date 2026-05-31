import { describe, expect, it } from "vitest";
import { __testing } from "./ghl-client.js";

const { buildGhlUrl, buildGhlHeaders, interpretNotFound, normalizeContact } = __testing;

describe("buildGhlUrl", () => {
  it("appends the path to a bare host", () => {
    expect(buildGhlUrl("https://services.leadconnectorhq.com", "/contacts/search")).toBe(
      "https://services.leadconnectorhq.com/contacts/search",
    );
  });

  it("preserves a reverse-proxy path prefix", () => {
    expect(buildGhlUrl("https://proxy.example/ghl/", "/contacts/abc")).toBe(
      "https://proxy.example/ghl/contacts/abc",
    );
  });

  it("encodes query params and skips empty values", () => {
    const url = buildGhlUrl("https://services.leadconnectorhq.com", "/contacts/", {
      locationId: "loc 1",
      limit: undefined,
    });
    expect(url).toContain("locationId=loc+1");
    expect(url).not.toContain("limit=");
  });

  it("falls back to the default base on an invalid url", () => {
    expect(buildGhlUrl("not a url", "/contacts/x")).toBe(
      "https://services.leadconnectorhq.com/contacts/x",
    );
  });
});

describe("buildGhlHeaders", () => {
  it("always sets the version and bearer auth, content-type only for POST", () => {
    const get = buildGhlHeaders("tok", "2021-07-28", "GET");
    expect(get.Authorization).toBe("Bearer tok");
    expect(get.Version).toBe("2021-07-28");
    expect(get["Content-Type"]).toBeUndefined();

    const post = buildGhlHeaders("tok", "2021-07-28", "POST");
    expect(post["Content-Type"]).toBe("application/json");
  });
});

describe("interpretNotFound", () => {
  it("treats 404 as not found", () => {
    expect(interpretNotFound({ status: 404, payload: {} })).toBe(true);
  });

  it("treats a 200 body with found:false as not found", () => {
    expect(interpretNotFound({ status: 200, payload: { found: false } })).toBe(true);
  });

  it("does not treat a normal 200 as not found", () => {
    expect(interpretNotFound({ status: 200, payload: { contact: { id: "x" } } })).toBe(false);
  });

  it("does not treat a 500 as not found", () => {
    expect(interpretNotFound({ status: 500, payload: {} })).toBe(false);
  });
});

describe("normalizeContact", () => {
  it("returns undefined for non-objects", () => {
    expect(normalizeContact(null)).toBeUndefined();
    expect(normalizeContact("nope")).toBeUndefined();
  });

  it("projects and wraps known fields", () => {
    const out = normalizeContact({
      id: "c1",
      firstName: "Ada",
      email: "ada@example.com",
      tags: ["vip", ""],
      ignored: "drop me",
    });
    expect(out?.id).toBe("c1");
    expect(typeof out?.firstName).toBe("string");
    // Free-text fields are wrapped as untrusted external content.
    expect(String(out?.email)).toContain("ada@example.com");
    expect(Array.isArray(out?.tags)).toBe(true);
    expect((out?.tags as string[]).length).toBe(1);
    expect(out).not.toHaveProperty("ignored");
  });
});
