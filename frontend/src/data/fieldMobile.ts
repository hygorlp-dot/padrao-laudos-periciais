import type { InspectionSnapshot } from "./inspectionSession";

export type OfflinePackageEnvelope = {
  device_id: string;
  package: { package_id: string; package_revision: number; device_sequence: number; inspection_snapshot: InspectionSnapshot };
};
export type FieldSyncConflict = { code: string; message: string; record_ids: string[]; requires_explicit_review: boolean };
export type FieldSyncResult = { accepted: boolean; conflicts: FieldSyncConflict[]; revision: number | null };

async function jsonPost<T>(path: string, body: object, method: "POST" | "PUT" = "POST"): Promise<T> {
  let response: Response;
  try { response = await fetch(path, { method, credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json; charset=utf-8" }, body: JSON.stringify(body) }); }
  catch { throw new Error("FIELD_MOBILE_UNAVAILABLE"); }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new Error("FIELD_MOBILE_INVALID_RESPONSE");
  const value = await response.json() as T;
  if (!response.ok && response.status !== 409) throw new Error("FIELD_MOBILE_UNAVAILABLE");
  return value;
}

export function prepareOfflineInspection(workspaceId: string, deviceSessionId: string) {
  return jsonPost<OfflinePackageEnvelope>(`/app-api/v1/workspaces/${workspaceId}/offline-inspection`, { device_session_id: deviceSessionId });
}

export function syncOfflineInspection(workspaceId: string, packageId: string) {
  return jsonPost<FieldSyncResult>(`/app-api/v1/workspaces/${workspaceId}/offline-sync`, { package_id: packageId });
}

export function updateOfflineInspection(workspaceId: string, packageId: string, expectedPackageRevision: number, snapshot: InspectionSnapshot) {
  return jsonPost<OfflinePackageEnvelope>(`/app-api/v1/workspaces/${workspaceId}/offline-inspection`, {
    package_id: packageId, expected_package_revision: expectedPackageRevision, snapshot,
  }, "PUT");
}

export async function getOfflineInspection(workspaceId: string, packageId: string): Promise<OfflinePackageEnvelope> {
  const response = await fetch(`/app-api/v1/workspaces/${workspaceId}/offline-inspection/${encodeURIComponent(packageId)}`, { credentials: "same-origin", cache: "no-store" });
  if (!response.ok || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new Error("FIELD_MOBILE_UNAVAILABLE");
  return await response.json() as OfflinePackageEnvelope;
}

export async function listPendingOfflineInspections(workspaceId: string): Promise<{
  items: OfflinePackageEnvelope["package"][];
  conflicts?: Array<{ code: string; message: string }>;
}> {
  const response = await fetch(`/app-api/v1/workspaces/${workspaceId}/offline-inspection`, { credentials: "same-origin", cache: "no-store" });
  if (!response.ok || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new Error("FIELD_MOBILE_UNAVAILABLE");
  return await response.json() as {
    items: OfflinePackageEnvelope["package"][];
    conflicts?: Array<{ code: string; message: string }>;
  };
}

export function revokeOfflineDevice(workspaceId: string) {
  return jsonPost<{ revoked: true }>(`/app-api/v1/workspaces/${workspaceId}/offline-device/revoke`, { confirm: true });
}
