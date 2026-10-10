import type { DeliveryState } from "../data/deliverySnapshot";

export const DELIVERY_LABELS: Record<DeliveryState, string> = {
  DRAFT: "Preparando arquivos", READY_FOR_REVIEW: "Pronta para conferência",
  APPROVED: "Entrega aprovada", FINALIZED: "Arquivos finalizados",
  DELIVERED: "Registrada como entregue", SUPERSEDED: "Substituída por nova revisão", STALE: "Desatualizada",
};
