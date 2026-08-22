"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { updateOpportunityStatus } from "@/src/features/api/client";

const allowedStatuses = new Set(["validated", "dismissed", "archived"]);

export async function reviewOpportunityStatus(formData: FormData) {
  const id = formData.get("id");
  const status = formData.get("status");
  if (typeof id !== "string" || id.length === 0 || id.length > 200) throw new Error("Invalid opportunity identifier.");
  if (typeof status !== "string" || !allowedStatuses.has(status)) throw new Error("Invalid review status.");

  await updateOpportunityStatus(id, status);
  revalidatePath("/overview");
  revalidatePath("/opportunities");
  revalidatePath(`/opportunities/${encodeURIComponent(id)}`);
  redirect(`/opportunities/${encodeURIComponent(id)}?status=updated`);
}
