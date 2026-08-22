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
          ? "The console is not configured to access the required service."
          : unauthorized
            ? "The console could not access the requested service."
            : "The requested service is unavailable or returned an unexpected response. Try again."}
      </p>
      <p><button type="button" onClick={reset}>Try again</button></p>
    </main>
  );
}
