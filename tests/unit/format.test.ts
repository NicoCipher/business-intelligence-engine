import { describe, expect, it } from "vitest";

import { boundedInteger, singleValue } from "@/src/features/shared/search-params";
import { isStale, safeExternalUrl } from "@/src/features/shared/format";

describe("safeExternalUrl", () => {
  it("allows http and https evidence links only", () => {
    expect(safeExternalUrl("https://example.com/evidence")).toBe("https://example.com/evidence");
    expect(safeExternalUrl("http://example.com/evidence")).toBe("http://example.com/evidence");
  });

  it("rejects executable and malformed URLs", () => {
    expect(safeExternalUrl("javascript:alert(1)")).toBeNull();
    expect(safeExternalUrl("not a url")).toBeNull();
  });
});

describe("server-side query parsing", () => {
  it("uses only a single search value and bounds pagination", () => {
    expect(singleValue(["first", "second"])).toBeUndefined();
    expect(boundedInteger("20", 0, 100)).toBe(20);
    expect(boundedInteger("-1", 0, 100)).toBe(0);
    expect(boundedInteger("1000", 0, 100)).toBe(0);
  });
});

describe("evidence freshness", () => {
  it("treats an absent or old signal as stale", () => {
    expect(isStale(null)).toBe(true);
    expect(isStale(new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString())).toBe(true);
    expect(isStale(new Date().toISOString())).toBe(false);
  });
});
