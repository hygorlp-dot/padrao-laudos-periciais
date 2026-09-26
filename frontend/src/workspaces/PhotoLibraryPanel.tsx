import { type ChangeEvent, useEffect, useMemo, useState } from "react";

import {
  describeLibraryPhoto,
  fileSha256,
  getPhotoLibrary,
  importLibraryPhoto,
  PhotoLibraryApiError,
  removeLibraryPhoto,
  selectLibraryPhotos,
  thumbnailPath,
  type FigureSection,
  type PhotoEntry,
  type PhotoLibraryEnvelope,
} from "../data/photoLibrary";

const SECTIONS: Array<[FigureSection, string]> = [
  ["INSPECTION", "Vistoria"],
  ["TECHNICAL_ANALYSIS", "Análise técnica"],
  ["TECHNICAL_FINDINGS", "Achados técnicos"],
  ["ATTACHMENTS", "Anexos"],
];

type State = { kind: "loading" } | { kind: "ready"; value: PhotoLibraryEnvelope | null } | { kind: "error" };
type Progress = { done: number; total: number; imported: number; duplicates: number; failed: string[] };

function capturedLabel(value: string | null) {
  if (!value) return "Data da captura não registrada";
  const [date, time] = value.split("T");
  const [year, month, day] = date.split("-");
  return `Capturada em ${day}/${month}/${year} às ${time.slice(0, 5)}`;
}

export function PhotoLibraryPanel({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [tagFilter, setTagFilter] = useState("");
  const [search, setSearch] = useState("");
  const [onlySelected, setOnlySelected] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getPhotoLibrary(workspaceId, controller.signal)
      .then((value) => setState({ kind: "ready", value }))
      .catch((error: unknown) => { if (!controller.signal.aborted) setState(error instanceof PhotoLibraryApiError && error.kind === "not-found" ? { kind: "ready", value: null } : { kind: "error" }); });
    return () => controller.abort();
  }, [workspaceId]);

  const envelope = state.kind === "ready" ? state.value : null;
  const photos = useMemo(() => envelope?.library.photos ?? [], [envelope]);
  const selected = useMemo(() => photos.filter((item) => item.report_order !== null).sort((a, b) => (a.report_order ?? 0) - (b.report_order ?? 0)), [photos]);
  const tags = useMemo(() => [...new Set(photos.flatMap((item) => item.tags))].sort((a, b) => a.localeCompare(b, "pt-BR")), [photos]);
  const visible = photos.filter((item) =>
    (!tagFilter || item.tags.includes(tagFilter))
    && (!onlySelected || item.report_order !== null)
    && (!search.trim() || `${item.caption ?? ""} ${item.original_filename}`.toLocaleLowerCase("pt-BR").includes(search.trim().toLocaleLowerCase("pt-BR"))));

  const act = async (work: (revision: number) => Promise<PhotoLibraryEnvelope>, failure: string) => {
    if (!envelope) return false;
    setBusy(true); setProblem(null);
    try { setState({ kind: "ready", value: await work(envelope.revision) }); return true; }
    catch { setProblem(failure); return false; }
    finally { setBusy(false); }
  };

  const importFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    setBusy(true); setProblem(null);
    const known = new Set(photos.map((item) => item.original_sha256));
    let current = envelope;
    const summary: Progress = { done: 0, total: files.length, imported: 0, duplicates: 0, failed: [] };
    setProgress({ ...summary });
    // One at a time: each registration names the library revision it extends.
    for (const file of files) {
      try {
        if (!["image/jpeg", "image/png"].includes(file.type)) throw new Error("tipo");
        const digest = await fileSha256(file);
        if (known.has(digest)) summary.duplicates += 1;
        else {
          current = await importLibraryPhoto(workspaceId, current?.revision ?? null, file);
          known.add(digest);
          summary.imported += 1;
        }
      } catch (error) {
        if (error instanceof PhotoLibraryApiError && error.kind === "duplicate") summary.duplicates += 1;
        else summary.failed.push(file.name);
      }
      summary.done += 1;
      setProgress({ ...summary, failed: [...summary.failed] });
    }
    setState({ kind: "ready", value: current });
    setBusy(false);
  };

  const saveSelection = (next: PhotoEntry[], sections: Record<string, FigureSection>) =>
    act((revision) => selectLibraryPhotos(workspaceId, revision, next.map((item) => ({ photo_id: item.photo_id, section: sections[item.photo_id] }))), "Não foi possível salvar a seleção. Toda figura precisa de legenda.");
  const sectionsOf = (list: PhotoEntry[]) => Object.fromEntries(list.map((item) => [item.photo_id, item.report_section ?? "INSPECTION"])) as Record<string, FigureSection>;

  const toggle = (photo: PhotoEntry) => {
    const next = photo.report_order === null ? [...selected, photo] : selected.filter((item) => item.photo_id !== photo.photo_id);
    void saveSelection(next, sectionsOf(next));
  };
  const move = (photo: PhotoEntry, delta: number) => {
    const index = selected.findIndex((item) => item.photo_id === photo.photo_id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= selected.length) return;
    const next = [...selected];
    [next[index], next[target]] = [next[target], next[index]];
    void saveSelection(next, sectionsOf(next));
  };
  const place = (photo: PhotoEntry, section: FigureSection) => void saveSelection(selected, { ...sectionsOf(selected), [photo.photo_id]: section });

  if (state.kind === "loading") return <section className="analysis-section photo-library" aria-busy="true"><h3>Biblioteca de fotos</h3><p className="field-hint">Carregando…</p></section>;
  if (state.kind === "error") return <section className="analysis-section photo-library" role="alert"><h3>Biblioteca de fotos</h3><p>Não foi possível carregar a biblioteca. Verifique o serviço local.</p></section>;

  return <section className="analysis-section photo-library" aria-labelledby="photo-library-title">
    <header className="photo-library__header">
      <div><h3 id="photo-library-title">Biblioteca de fotos</h3><p className="field-hint">Os originais ficam guardados só nesta máquina, sem alteração. No laudo entra uma cópia de apresentação, na orientação correta e sem metadados.</p></div>
      <label className="primary-action photo-library__import">{busy && progress ? `Importando ${progress.done} de ${progress.total}…` : "Importar fotos"}<input type="file" accept="image/jpeg,image/png" multiple disabled={busy} onChange={(event) => void importFiles(event)} /></label>
    </header>
    {progress && progress.done === progress.total && <p className="inline-note" role="status">{progress.imported} {progress.imported === 1 ? "foto importada" : "fotos importadas"}{progress.duplicates ? `; ${progress.duplicates} ${progress.duplicates === 1 ? "repetida ignorada" : "repetidas ignoradas"}` : ""}{progress.failed.length ? `; não importadas: ${progress.failed.join(", ")}` : ""}.</p>}
    {problem && <p className="inline-alert" role="alert">{problem}</p>}
    {photos.length === 0
      ? <p className="report-empty">Nenhuma foto ainda. Importe as fotos da vistoria; você pode escolher várias de uma vez.</p>
      : <>
        <div className="photo-library__filters">
          <label>Buscar<input type="search" value={search} placeholder="Legenda ou nome do arquivo" onChange={(event) => setSearch(event.target.value)} /></label>
          <label>Etiqueta<select value={tagFilter} onChange={(event) => setTagFilter(event.target.value)}><option value="">Todas</option>{tags.map((tag) => <option key={tag} value={tag}>{tag}</option>)}</select></label>
          <label className="checkbox-label"><input type="checkbox" checked={onlySelected} onChange={(event) => setOnlySelected(event.target.checked)} /> Só as escolhidas para o laudo</label>
          <p className="field-hint">{photos.length} {photos.length === 1 ? "foto" : "fotos"} · {selected.length} no laudo</p>
        </div>
        <ul className="photo-library__grid">{visible.map((photo) => <PhotoCard key={`${photo.photo_id}:${photo.caption}:${photo.tags.join("|")}`} workspaceId={workspaceId} photo={photo} busy={busy} position={selected.findIndex((item) => item.photo_id === photo.photo_id)} total={selected.length}
          onDescribe={(caption, tagList) => act((revision) => describeLibraryPhoto(workspaceId, revision, photo.photo_id, caption, tagList), "Não foi possível salvar a legenda.")}
          onToggle={() => toggle(photo)} onMove={(delta) => move(photo, delta)} onPlace={(section) => place(photo, section)}
          onRemove={() => void act((revision) => removeLibraryPhoto(workspaceId, revision, photo.photo_id), "Não foi possível retirar a foto.")} />)}</ul>
        {visible.length === 0 && <p className="report-empty">Nenhuma foto com esses filtros.</p>}
      </>}
  </section>;
}

function PhotoCard({ workspaceId, photo, busy, position, total, onDescribe, onToggle, onMove, onPlace, onRemove }: {
  workspaceId: string; photo: PhotoEntry; busy: boolean; position: number; total: number;
  onDescribe: (caption: string, tags: string[]) => Promise<boolean>; onToggle: () => void; onMove: (delta: number) => void; onPlace: (section: FigureSection) => void; onRemove: () => void;
}) {
  // Remounted by key whenever the saved caption or tags change.
  const [caption, setCaption] = useState(photo.caption ?? "");
  const [tagText, setTagText] = useState(photo.tags.join(", "));
  const tagList = tagText.split(",").map((item) => item.trim()).filter(Boolean);
  const changed = caption.trim() !== (photo.caption ?? "") || tagList.join("|") !== photo.tags.join("|");
  const inReport = position >= 0;
  return <li className="photo-card" data-selected={inReport || undefined}>
    <img src={thumbnailPath(workspaceId, photo.photo_id)} alt={photo.caption ?? `Foto ${photo.original_filename}`} loading="lazy" width={photo.width >= photo.height ? 240 : 180} height={photo.width >= photo.height ? 180 : 240} />
    <div className="photo-card__body">
      <p className="photo-card__meta"><span className="data">{photo.original_filename}</span> · {capturedLabel(photo.captured_at)}{photo.has_embedded_location ? " · localização embutida (não copiada)" : ""}</p>
      <label>Legenda<input value={caption} maxLength={300} disabled={busy} onChange={(event) => setCaption(event.target.value)} /></label>
      <label>Etiquetas<input value={tagText} placeholder="fachada, umidade" disabled={busy} onChange={(event) => setTagText(event.target.value)} /></label>
      {changed && <button className="secondary-action" type="button" disabled={busy} onClick={() => void onDescribe(caption, tagList)}>Salvar legenda e etiquetas</button>}
      <div className="photo-card__report">
        <label className="checkbox-label"><input type="checkbox" checked={inReport} disabled={busy || (!inReport && !photo.caption)} onChange={onToggle} /> Usar no laudo{inReport ? ` (figura ${position + 1} de ${total})` : ""}</label>
        {!inReport && !photo.caption && <span className="field-hint">Escreva e salve a legenda para usar no laudo.</span>}
        {inReport && <>
          <label>Seção<select value={photo.report_section ?? "INSPECTION"} disabled={busy} onChange={(event) => onPlace(event.target.value as FigureSection)}>{SECTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <div className="action-row"><button className="text-action" type="button" disabled={busy || position === 0} onClick={() => onMove(-1)}>Antes</button><button className="text-action" type="button" disabled={busy || position === total - 1} onClick={() => onMove(1)}>Depois</button></div>
        </>}
        {!inReport && <button className="text-action" type="button" disabled={busy} onClick={onRemove}>Retirar da biblioteca</button>}
      </div>
    </div>
  </li>;
}
