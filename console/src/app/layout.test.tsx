import { describe, expect, it } from "vitest";

import RootLayout, { metadata } from "./layout";

describe("RootLayout", () => {
  it("declares the console identity and English document language", () => {
    const result = RootLayout({ children: <p>content</p> });

    expect(metadata.title).toBe("AgentOps Incident Commander");
    expect(result.type).toBe("html");
    expect(result.props.lang).toBe("en");
    expect(result.props.children.type).toBe("body");
  });
});
