export type SiteLocation = {
  schema_version: "1.0.0"; workspace_id: string; latitude: number; longitude: number; datum: "WGS84";
  input_format: "GOOGLE_MAPS_PLACE" | "GOOGLE_MAPS_QUERY" | "GOOGLE_MAPS_VIEWPORT" | "OPENSTREETMAP" | "GEO_URI" | "DECIMAL" | "DEGREES_MINUTES_SECONDS";
  address_label: string | null; note: string | null; state: "PROPOSED" | "CONFIRMED"; confirmed_by: string | null; confirmed_at: string | null;
};
export type SiteLocationEnvelope = { revision: number; updated_at: string; location: SiteLocation };
export type SiteLocationRefusal = "SHORT_LINK_REQUIRES_NETWORK" | "NO_COORDINATES" | "UNSUPPORTED_LINK" | "OUT_OF_RANGE";
export class SiteLocationApiError extends Error {
  constructor(readonly kind: "not-found" | "refused" | "conflict" | "unavailable", readonly reason?: SiteLocationRefusal) { super(kind); }
}

const base = (workspaceId: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}/site-location`;
const REFUSALS: SiteLocationRefusal[] = ["SHORT_LINK_REQUIRES_NETWORK", "NO_COORDINATES", "UNSUPPORTED_LINK", "OUT_OF_RANGE"];

async function decode(response: Response, workspaceId: string): Promise<SiteLocationEnvelope> {
  if (response.status === 404) throw new SiteLocationApiError("not-found");
  if (response.status === 409) throw new SiteLocationApiError("conflict");
  if (response.status === 422) {
    const code = String((await response.json().catch(() => null))?.error?.code ?? "").replace(/^LOCATION_/, "") as SiteLocationRefusal;
    throw new SiteLocationApiError("refused", REFUSALS.includes(code) ? code : "NO_COORDINATES");
  }
  if (!response.ok) throw new SiteLocationApiError("unavailable");
  const value = await response.json() as SiteLocationEnvelope;
  const location = value?.location;
  if (!Number.isInteger(value?.revision) || value.revision < 1 || location?.workspace_id !== workspaceId || typeof location.latitude !== "number" || typeof location.longitude !== "number" || !["PROPOSED", "CONFIRMED"].includes(location.state)) throw new SiteLocationApiError("unavailable");
  return value;
}

export async function getSiteLocation(workspaceId: string, signal?: AbortSignal) {
  return decode(await fetch(base(workspaceId), { method: "GET", credentials: "same-origin", cache: "no-store", signal }), workspaceId);
}
export async function proposeSiteLocation(workspaceId: string, expectedRevision: number | null, input: string, addressLabel: string, note: string) {
  return decode(await fetch(base(workspaceId), { method: "PUT", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: expectedRevision, input, address_label: addressLabel.trim() || null, note: note.trim() || null }) }), workspaceId);
}
export async function confirmSiteLocation(workspaceId: string, expectedRevision: number) {
  return decode(await fetch(`${base(workspaceId)}/confirmation`, { method: "POST", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: expectedRevision }) }), workspaceId);
}

// A Brazilian report writes coordinates with a decimal comma and hemisphere letters.
export function coordinatesText(location: Pick<SiteLocation, "latitude" | "longitude">) {
  const part = (value: number, positive: string, negative: string) => `${Math.abs(value).toFixed(6).replace(".", ",")}° ${value < 0 ? negative : positive}`;
  return `${part(location.latitude, "N", "S")}, ${part(location.longitude, "L", "O")}`;
}
