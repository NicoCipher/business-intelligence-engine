import "server-only";

export function assertProductionBackendConfiguration() {
  if (process.env.NODE_ENV !== "production") return;

  if (!process.env.BIA_API_BASE_URL || !process.env.BIA_API_KEY) {
    throw new Error(
      "BIA Operations Console requires BIA_API_BASE_URL and BIA_API_KEY in production."
    );
  }
}
