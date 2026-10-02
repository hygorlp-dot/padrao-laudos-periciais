import type { EditorialProfile } from "../data/reportSnapshot";

// O preset do produto (Justiça Plural, cap. 4) como o laudo antigo o gravou.
export const EDITORIAL_PRESET: EditorialProfile = { profile_id: "JUSTICA_PLURAL_CHAPTER_4", font_family: "Arial", body_font_pt: 11, table_font_pt: 10, caption_font_pt: 9, alignment: "JUSTIFIED", line_spacing: 1.15, first_line_indent_cm: 1.25, page_size: "A4", margin_top_cm: 2, margin_bottom_cm: 2, margin_left_cm: 3, margin_right_cm: 2, hyphenation: false, overrides: [] };

export const decimal = (value: number | undefined) => String(value ?? 0).replace(".", ",");

export function editorialSummary(profile: EditorialProfile) {
  const current = { ...EDITORIAL_PRESET, ...profile };
  return `${profile.profile_id === "CUSTOM" ? "Personalizado" : "Padrão do produto"} · ${current.font_family} ${current.body_font_pt} pt · entrelinha ${decimal(current.line_spacing)} · recuo ${decimal(current.first_line_indent_cm)} cm`;
}
