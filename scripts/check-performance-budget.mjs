import { readFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";

const budgetBytes = 150 * 1024;
const manifestPath = new URL("../.next/build-manifest.json", import.meta.url);
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const chunks = manifest.rootMainFiles;

if (!Array.isArray(chunks) || chunks.length === 0) {
  throw new Error("Unable to locate the Next.js root client chunk manifest.");
}

const sizes = await Promise.all(chunks.map(async (chunk) => {
  const asset = new URL(`../.next/${chunk}`, import.meta.url);
  const bytes = gzipSync(await readFile(asset)).byteLength;
  return { chunk, bytes };
}));
const total = sizes.reduce((sum, item) => sum + item.bytes, 0);

console.log(`Root client runtime: ${(total / 1024).toFixed(1)} KiB gzip (budget: ${budgetBytes / 1024} KiB)`);
if (total > budgetBytes) {
  throw new Error(`Root client runtime exceeds the ${budgetBytes / 1024} KiB gzip budget.`);
}
