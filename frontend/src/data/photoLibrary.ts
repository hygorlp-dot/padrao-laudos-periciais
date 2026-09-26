import { uploadInspectionPhoto } from "./inspectionSession";

export type FigureSection = "INSPECTION" | "TECHNICAL_ANALYSIS" | "TECHNICAL_FINDINGS" | "ATTACHMENTS";
export type PhotoEntry = {
  photo_id: string; content_id: string; original_sha256: string; original_filename: string; media_type: string;
  width: number; height: number; captured_at: string | null; camera: string | null; has_embedded_location: boolean;
  imported_at: string; caption: string | null; tags: string[]; report_section: FigureSection | null; report_order: number | null;
};
export type PhotoLibrary = { schema_version: "1.0.0"; workspace_id: string; photos: PhotoEntry[] };
export type PhotoLibraryEnvelope = { revision: number; updated_at: string; library: PhotoLibrary };
export class PhotoLibraryApiError extends Error {
  constructor(readonly kind: "not-found" | "duplicate" | "conflict" | "unavailable", readonly photoId?: string) { super(kind); }
}

const base = (workspaceId: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}/photo-library`;

async function decode(response: Response, workspaceId: string): Promise<PhotoLibraryEnvelope> {
  if (response.status === 404) throw new PhotoLibraryApiError("not-found");
  if (response.status === 409) {
    const error = (await response.json().catch(() => null))?.error;
    throw error?.code === "PHOTO_DUPLICATE" ? new PhotoLibraryApiError("duplicate", String(error.photo_id ?? "")) : new PhotoLibraryApiError("conflict");
  }
  if (!response.ok) throw new PhotoLibraryApiError("unavailable");
  const value = await response.json() as PhotoLibraryEnvelope;
  if (!Number.isInteger(value?.revision) || value.revision < 1 || value.library?.workspace_id !== workspaceId || !Array.isArray(value.library.photos)) throw new PhotoLibraryApiError("unavailable");
  return value;
}

const post = async (workspaceId: string, path: string, body: object) => decode(await fetch(`${base(workspaceId)}/${path}`, { method: "POST", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }), workspaceId);

export async function getPhotoLibrary(workspaceId: string, signal?: AbortSignal) {
  return decode(await fetch(base(workspaceId), { method: "GET", credentials: "same-origin", cache: "no-store", signal }), workspaceId);
}

// SHA-256 of the file as the library records it, computed here so the same
// bytes are recognised before they are uploaded a second time.
export async function fileSha256(file: File) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function importLibraryPhoto(workspaceId: string, expectedRevision: number | null, file: File) {
  const { contentId } = await uploadInspectionPhoto(workspaceId, file);
  return post(workspaceId, "photos", { expected_revision: expectedRevision, content_id: contentId });
}
export function describeLibraryPhoto(workspaceId: string, expectedRevision: number, photoId: string, caption: string, tags: string[]) {
  return post(workspaceId, "descriptions", { expected_revision: expectedRevision, photo_id: photoId, caption: caption.trim() || null, tags });
}
export function selectLibraryPhotos(workspaceId: string, expectedRevision: number, selection: Array<{ photo_id: string; section: FigureSection }>) {
  return post(workspaceId, "selection", { expected_revision: expectedRevision, selection });
}
export function removeLibraryPhoto(workspaceId: string, expectedRevision: number, photoId: string) {
  return post(workspaceId, "removals", { expected_revision: expectedRevision, photo_id: photoId });
}
export const thumbnailPath = (workspaceId: string, photoId: string) => `${base(workspaceId)}/photos/${encodeURIComponent(photoId)}/thumbnail`;
