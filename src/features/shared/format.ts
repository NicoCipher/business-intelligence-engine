export function formatDate(value: string | null | undefined, options?: Intl.DateTimeFormatOptions) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Unparseable timestamp";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
    ...options
  }).format(date);
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-GB").format(value);
}

export function formatScore(value: number) {
  return value.toFixed(1);
}

export function isStale(value: string | null, hours = 36) {
  if (!value) return true;
  const time = new Date(value).valueOf();
  return Number.isNaN(time) || Date.now() - time > hours * 60 * 60 * 1000;
}

export function safeExternalUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}
