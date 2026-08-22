"use client";

export default function RootError({ error, reset }: Readonly<{ error: Error; reset: () => void }>) {
  const unauthorized = error.message === "BIA_API_UNAUTHORIZED";
  const configuration = error.message === "BIA_API_CONFIGURATION_MISSING";

  return (
    <main className="content">
      <p className="eyebrow">Console unavailable</p>
      <h1>{unauthorized ? "Backend access was rejected." : "The console could not load this operational view."}</h1>
      <p className="lede">
        {configuration
          ? "The server is missing its required BIA backend configuration. No credentials are available in the browser."
          : unauthorized
            ? "The server-to-server BIA credential was not accepted. Verify the private deployment configuration."
            : "The backend may be unavailable or returned an unexpected response. Try again, then inspect system diagnostics."}
      </p>
      <p><button type="button" onClick={reset}>Try again</button></p>
    </main>
  );
}
