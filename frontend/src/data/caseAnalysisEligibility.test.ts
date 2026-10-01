import { describe, expect, test } from "vitest";
import { derivedFromUnavailable, isEffectiveItem, unavailableDocumentIds, type AnalysisItem, type CaseAnalysisSnapshot } from "./caseAnalysis";

// Espelho do backend: o que o seletor oferece precisa ser exatamente o que o save aceita.
const source = (documentId: string) => ({ workspace_id: "W", source_document_id: documentId, source_document_sha256: "a".repeat(64), page_or_span: "p. 1", source_revision: 1, occurrence_id: `OCC-${documentId}` });
const item = (itemId: string, documentId: string): AnalysisItem => ({ item_id: itemId, text: itemId, participant_refs: [], technical_subjects: [], provenance: [source(documentId)] } as unknown as AnalysisItem);
const snapshot = (documents: Record<string, boolean>, reviews: { target_item_id: string; decision: string; revision: number }[] = []) => ({
  documents: Object.entries(documents).map(([document_id, content_available]) => ({ document_id, content_available })),
  human_reviews: reviews,
} as unknown as CaseAnalysisSnapshot);

describe("source eligibility mirrors the backend", () => {
  test("an excluded document leaves the offer; re-enabling brings it back; others stay", () => {
    const kept = item("CLAIM-1", "DOC-001");
    const derived = item("CLAIM-2", "DOC-002");

    const available = unavailableDocumentIds(snapshot({ "DOC-001": true, "DOC-002": true }));
    expect(derivedFromUnavailable(derived, available)).toBe(false);

    const excluded = unavailableDocumentIds(snapshot({ "DOC-001": true, "DOC-002": false }));
    expect([...excluded]).toEqual(["DOC-002"]);
    expect(derivedFromUnavailable(derived, excluded)).toBe(true);
    expect(derivedFromUnavailable(kept, excluded)).toBe(false);

    const reenabled = unavailableDocumentIds(snapshot({ "DOC-001": true, "DOC-002": true }));
    expect(derivedFromUnavailable(derived, reenabled)).toBe(false);
  });

  test("effectiveness follows the LATEST review by revision, not array order", () => {
    expect(isEffectiveItem(snapshot({}), "CLAIM-1")).toBe(true);
    expect(isEffectiveItem(snapshot({}, [{ target_item_id: "CLAIM-1", decision: "CONFIRM", revision: 1 }]), "CLAIM-1")).toBe(true);
    expect(isEffectiveItem(snapshot({}, [{ target_item_id: "CLAIM-1", decision: "REJECT", revision: 2 }]), "CLAIM-1")).toBe(false);
    // Restaurado: uma revisão posterior à rejeição volta a torná-lo efetivo.
    const restored = [
      { target_item_id: "CLAIM-1", decision: "CONFIRM", revision: 3 },
      { target_item_id: "CLAIM-1", decision: "REJECT", revision: 2 },
    ];
    expect(isEffectiveItem(snapshot({}, restored), "CLAIM-1")).toBe(true);
    // A rejeição de OUTRO item não afeta este.
    expect(isEffectiveItem(snapshot({}, [{ target_item_id: "CLAIM-9", decision: "REJECT", revision: 4 }]), "CLAIM-1")).toBe(true);
  });
});
