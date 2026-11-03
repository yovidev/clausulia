import { failureReason, STATUS_LABELS } from "../logic";
import type { DocumentOut } from "../types";

/** Estado del documento con color y, si falló, el motivo legible. */
export function StatusBadge({ document }: { document: DocumentOut }) {
  return (
    <div className="status">
      <span className={`badge status-${document.status}`}>{STATUS_LABELS[document.status]}</span>
      {document.status === "failed" && (
        <span className="status-reason">
          {failureReason(document.error_code, document.error_message)}
        </span>
      )}
    </div>
  );
}
