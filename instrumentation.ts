import { assertProductionBackendConfiguration } from "@/src/features/api/config";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    assertProductionBackendConfiguration();
  }
}
