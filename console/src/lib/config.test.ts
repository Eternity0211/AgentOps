import { describe, expect, it } from "vitest";

import { resolveApiBaseUrl } from "./config";

describe("resolveApiBaseUrl", () => {
  it("uses a same-origin default and removes one trailing slash", () => {
    expect(resolveApiBaseUrl(undefined)).toBe("/api/v1");
    expect(resolveApiBaseUrl("   ")).toBe("/api/v1");
    expect(resolveApiBaseUrl("/")).toBe("/");
    expect(resolveApiBaseUrl(" /control/ ")).toBe("/control");
    expect(resolveApiBaseUrl("https://control.example.test/api/v1")).toBe(
      "https://control.example.test/api/v1",
    );
    expect(resolveApiBaseUrl("https://control.example.test/api/v1/")).toBe(
      "https://control.example.test/api/v1",
    );
  });

  it.each([
    "//attacker.example.test",
    "/api/v1?tenant=other",
    "/api/v1#override",
    "ftp://control.example.test/api/v1",
    "https://operator:secret@control.example.test/api/v1",
    "https://:secret@control.example.test/api/v1",
    "https://control.example.test/api/v1#override",
    "https://control.example.test/api/v1?tenant=other",
    "not a url",
  ])("rejects unsafe API bases: %s", (value) => {
    expect(() => resolveApiBaseUrl(value)).toThrow(/API_BASE_URL/);
  });
});
