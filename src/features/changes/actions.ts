"use server";

import { revalidatePath } from "next/cache";

import { acknowledgeChanges } from "@/src/features/api/client";

/**
 * Marks all changes through a given snapshot as reviewed.
 *
 * The `snapshotAt` field MUST be the `snapshot_at` value a prior
 * GET /changes/unseen response returned -- never the click time, never
 * the browser's own clock. This is what makes acknowledgement race-safe
 * against a change event arriving between when the operator's view was
 * fetched and when they click "Mark reviewed": the checkpoint reflects
 * what the operator's page actually showed, not the moment of the
 * click. See backend/api/operator_state.py's module docstring for the
 * full reasoning.
 *
 * This is an explicit, operator-triggered mutation only -- invoked by
 * an actual form submit, never by a page render or a GET. It advances
 * the single global operator_state checkpoint; it does not, and
 * cannot, acknowledge a filtered subset of changes (operator_state has
 * exactly one watermark -- see backend/api/changes.py's module
 * docstring for why /unseen itself has no domain/significance filters).
 */
export async function acknowledgeCurrentChanges(formData: FormData) {
  const snapshotAt = formData.get("snapshotAt");
  if (typeof snapshotAt !== "string" || snapshotAt.length === 0 || snapshotAt.length > 100) {
    throw new Error("Invalid acknowledgement snapshot.");
  }

  await acknowledgeChanges(snapshotAt);
  revalidatePath("/overview");
}
