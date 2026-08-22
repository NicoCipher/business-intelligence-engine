export type SearchParams = Record<string, string | string[] | undefined>;

export function singleValue(value: string | string[] | undefined) {
  return typeof value === "string" ? value : undefined;
}

export function boundedInteger(value: string | undefined, fallback: number, maximum: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 && parsed <= maximum ? parsed : fallback;
}
