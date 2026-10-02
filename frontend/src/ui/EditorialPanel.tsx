import { useState, type ReactNode } from "react";

import type { EditorialLayout, EditorialProfile } from "../data/reportSnapshot";
import { decimal, EDITORIAL_PRESET, editorialSummary } from "./editorialProfile";

// Um único painel editorial (#270): o mesmo componente edita o padrão da
// instalação, em Configurações, e o perfil do laudo, na etapa Laudo.

const TYPOGRAPHY_DEFAULT = { heading1_pt: 14, heading2_pt: 12, heading3_pt: 11, headings_bold: true, heading_space_before_pt: 12, heading_space_after_pt: 6, paragraph_space_after_pt: 6 };
// Perfil sem `layout` mantém o comportamento anterior: título 1 em caixa-alta,
// cabeçalho e rodapé a 1,25 cm.
const LEGACY_LAYOUT: EditorialLayout = { header_distance_cm: 1.25, footer_distance_cm: 1.25, paragraph_space_before_pt: 0, keep_with_next: true, widow_orphan_control: true, heading1_case: "UPPER", heading2_case: "PRESERVE", heading3_case: "PRESERVE", heading1_page_break_before: false, long_quote_indent_cm: 4, long_quote_font_pt_delta: 1, long_quote_line_spacing: 1 };
const FONTS = ["Arial", "Calibri", "Cambria", "Georgia", "Times New Roman", "Verdana"];
const CASES: { value: EditorialLayout["heading1_case"]; label: string }[] = [
  { value: "PRESERVE", label: "Como foi escrito" },
  { value: "UPPER", label: "TUDO EM MAIÚSCULAS" },
  { value: "TITLE_CASE", label: "Iniciais Maiúsculas" },
  { value: "SENTENCE_CASE", label: "Só a primeira maiúscula" },
];



export function EditorialPanel({
  profile,
  editable,
  busy,
  onSave,
  preset = EDITORIAL_PRESET,
  hint,
  collapsible = true,
  alternatives = [],
}: {
  profile: EditorialProfile;
  editable: boolean;
  busy: boolean;
  onSave: (profile: EditorialProfile) => Promise<boolean> | Promise<void> | void;
  preset?: EditorialProfile;
  hint?: ReactNode;
  collapsible?: boolean;
  // Perfis completos oferecidos como atalho explícito (ex.: geometria do laudo legado).
  alternatives?: { label: string; profile: EditorialProfile }[];
}) {
  const current = { ...EDITORIAL_PRESET, ...profile };
  const [draft, setDraft] = useState<EditorialProfile>(current);
  const [typography, setTypography] = useState({ ...TYPOGRAPHY_DEFAULT, ...(profile.typography ?? {}) });
  const [layout, setLayout] = useState<EditorialLayout>({ ...LEGACY_LAYOUT, ...(profile.layout ?? {}) });
  const isPreset = profile.profile_id !== "CUSTOM";
  const number = (value: string) => Number(value.replace(",", "."));
  const locked = !editable || busy;
  const field = (label: string, key: keyof EditorialProfile, min: number, max: number, step: number) => (
    <label>{label}<input type="number" min={min} max={max} step={step} value={Number(draft[key] ?? 0)} disabled={locked} onChange={(event) => setDraft({ ...draft, [key]: number(event.target.value) })} /></label>
  );
  const heading = (label: string, key: keyof typeof TYPOGRAPHY_DEFAULT, min: number, max: number) => (
    <label>{label}<input type="number" min={min} max={max} step={1} value={Number(typography[key])} disabled={locked} onChange={(event) => setTypography({ ...typography, [key]: number(event.target.value) })} /></label>
  );
  const geometry = (label: string, key: "header_distance_cm" | "footer_distance_cm" | "long_quote_indent_cm", min: number, max: number, step: number) => (
    <label>{label}<input type="number" min={min} max={max} step={step} value={layout[key]} disabled={locked} onChange={(event) => setLayout({ ...layout, [key]: number(event.target.value) })} /></label>
  );
  const headingCase = (label: string, key: "heading1_case" | "heading2_case" | "heading3_case") => (
    <label>{label}<select value={layout[key]} disabled={locked} onChange={(event) => setLayout({ ...layout, [key]: event.target.value as EditorialLayout["heading1_case"] })}>{CASES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
  );
  const toggle = (label: string, key: "keep_with_next" | "widow_orphan_control" | "heading1_page_break_before") => (
    <label className="checkbox-label"><input type="checkbox" checked={layout[key]} disabled={locked} onChange={(event) => setLayout({ ...layout, [key]: event.target.checked })} /> {label}</label>
  );
  const save = () => {
    void onSave({ ...draft, profile_id: "CUSTOM", typography: { ...typography }, layout: { ...layout } });
  };

  const body = <>
    {hint ?? <p className="field-hint">Vale para o modelo padrão do produto usado na entrega. Um modelo Word próprio mantém a formatação do seu arquivo.</p>}
    <fieldset disabled={locked}><legend>Corpo do texto</legend>
      <label>Fonte<select value={draft.font_family} onChange={(event) => setDraft({ ...draft, font_family: event.target.value })}>{FONTS.map((font) => <option key={font}>{font}</option>)}</select></label>
      {field("Tamanho (pt)", "body_font_pt", 10, 14, 1)}
      <label>Alinhamento<select value={draft.alignment} onChange={(event) => setDraft({ ...draft, alignment: event.target.value })}><option value="JUSTIFIED">Justificado</option><option value="LEFT">À esquerda</option></select></label>
      <label>Entrelinha<select value={String(draft.line_spacing)} onChange={(event) => setDraft({ ...draft, line_spacing: Number(event.target.value) })}>{[1, 1.15, 1.5, 2].map((value) => <option key={value} value={String(value)}>{decimal(value)}</option>)}</select></label>
      {field("Recuo da primeira linha (cm)", "first_line_indent_cm", 0, 3, 0.25)}
      {heading("Espaço após parágrafo (pt)", "paragraph_space_after_pt", 0, 36)}
      {toggle("Evitar linhas isoladas no início ou fim da página", "widow_orphan_control")}
    </fieldset>
    <fieldset disabled={locked}><legend>Títulos</legend>
      {heading("Título 1 (pt)", "heading1_pt", 12, 20)}
      {heading("Título 2 (pt)", "heading2_pt", 11, 16)}
      {heading("Título 3 (pt)", "heading3_pt", 10, 14)}
      <label className="checkbox-label"><input type="checkbox" checked={typography.headings_bold} onChange={(event) => setTypography({ ...typography, headings_bold: event.target.checked })} /> Títulos em negrito</label>
      {headingCase("Caixa do título 1", "heading1_case")}
      {headingCase("Caixa do título 2", "heading2_case")}
      {headingCase("Caixa do título 3", "heading3_case")}
      {heading("Espaço antes do título (pt)", "heading_space_before_pt", 0, 36)}
      {heading("Espaço após o título (pt)", "heading_space_after_pt", 0, 36)}
      {toggle("Cada título 1 começa em nova página", "heading1_page_break_before")}
    </fieldset>
    <fieldset disabled={locked}><legend>Citação longa</legend>
      <p className="field-hint">Parágrafo que começa com “&gt; ” sai recuado, com fonte menor, como pede o Manual Justiça Plural para citação direta com mais de três linhas.</p>
      {geometry("Recuo (cm)", "long_quote_indent_cm", 0, 6, 0.5)}
      <label>Redução da fonte (pt)<input type="number" min={0} max={3} step={1} value={layout.long_quote_font_pt_delta} disabled={locked} onChange={(event) => setLayout({ ...layout, long_quote_font_pt_delta: number(event.target.value) })} /></label>
      <label>Entrelinha<select value={String(layout.long_quote_line_spacing)} disabled={locked} onChange={(event) => setLayout({ ...layout, long_quote_line_spacing: Number(event.target.value) })}>{[1, 1.15, 1.5, 2].map((value) => <option key={value} value={String(value)}>{decimal(value)}</option>)}</select></label>
    </fieldset>
    <fieldset disabled={locked}><legend>Tabelas, legendas e página A4</legend>
      {field("Tabelas (pt)", "table_font_pt", 8, 12, 1)}
      {field("Legendas (pt)", "caption_font_pt", 8, 11, 1)}
      {field("Margem superior (cm)", "margin_top_cm", 1.5, 4, 0.5)}
      {field("Margem inferior (cm)", "margin_bottom_cm", 1.5, 4, 0.5)}
      {field("Margem esquerda (cm)", "margin_left_cm", 1.5, 4, 0.5)}
      {field("Margem direita (cm)", "margin_right_cm", 1.5, 4, 0.5)}
      {geometry("Distância do cabeçalho (cm)", "header_distance_cm", 0.5, 3, 0.05)}
      {geometry("Distância do rodapé (cm)", "footer_distance_cm", 0.5, 3, 0.05)}
    </fieldset>
    {editable && <div className="action-row"><button className="primary-action" type="button" disabled={busy} onClick={save}>Salvar padrão editorial</button><button className="text-action" type="button" disabled={busy || isPreset} onClick={() => void onSave(preset)}>Restaurar padrão do produto</button>{alternatives.map((item) => <button key={item.label} className="text-action" type="button" disabled={busy} onClick={() => void onSave(item.profile)}>{item.label}</button>)}</div>}
  </>;

  if (!collapsible) return <div className="report-editorial">{body}</div>;
  return <details className="analysis-section report-editorial">
    <summary><strong>Padrão editorial</strong> <span className="field-hint">{editorialSummary(current)}</span></summary>
    {body}
  </details>;
}
