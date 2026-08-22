import { afterEach, describe, expect, it, vi } from "vitest";

import { getHealth, getSignals } from "@/src/features/api/client";
import { assertProductionBackendConfiguration } from "@/src/features/api/config";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  delete process.env.BIA_API_BASE_URL;
  delete process.env.BIA_API_KEY;
});

describe("server-only BIA API client", () => {
  it("fails closed at production startup when server credentials are missing", () => {
    const originalNodeEnv = process.env.NODE_ENV;
    const originalBaseUrl = process.env.BIA_API_BASE_URL;
    const originalApiKey = process.env.BIA_API_KEY;
    const environment = process.env as Record<string, string | undefined>;
    environment.NODE_ENV = "production";
    delete process.env.BIA_API_BASE_URL;
    delete process.env.BIA_API_KEY;

    expect(assertProductionBackendConfiguration).toThrow("BIA_API_BASE_URL and BIA_API_KEY");

    environment.NODE_ENV = originalNodeEnv;
    if (originalBaseUrl) process.env.BIA_API_BASE_URL = originalBaseUrl;
    if (originalApiKey) process.env.BIA_API_KEY = originalApiKey;
  });

  it("uses a server credential and an intentional no-store policy for health", async () => {
    process.env.BIA_API_BASE_URL = "http://bia.internal:8000/";
    process.env.BIA_API_KEY = "server-secret";
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok", version: "1", db: {} }), { status: 200 }));
    global.fetch = fetchMock;

    await getHealth();

    expect(fetchMock).toHaveBeenCalledWith("http://bia.internal:8000/api/v1/health", expect.objectContaining({
      cache: "no-store",
      headers: expect.objectContaining({ Authorization: "Bearer server-secret" })
    }));
  });

  it("uses a 60-second revalidation policy for the signal feed", async () => {
    process.env.BIA_API_BASE_URL = "http://bia.internal:8000";
    process.env.BIA_API_KEY = "server-secret";
    global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ signals: [], total: 0, limit: 50, offset: 0 }), { status: 200 }));

    await getSignals({ limit: 50, offset: 0 });

    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/signals?limit=50&offset=0"), expect.objectContaining({ next: { revalidate: 60 } }));
  });

  it("fails clearly for an unauthorized backend response", async () => {
    process.env.BIA_API_BASE_URL = "http://bia.internal:8000";
    process.env.BIA_API_KEY = "server-secret";
    global.fetch = vi.fn().mockResolvedValue(new Response("unauthorized", { status: 401 }));

    await expect(getHealth()).rejects.toMatchObject({ status: 401, message: "BIA_API_UNAUTHORIZED" });
  });

  it("does not permit missing backend server configuration", async () => {
    await expect(getHealth()).rejects.toThrow("BIA_API_CONFIGURATION_MISSING");
  });
});
