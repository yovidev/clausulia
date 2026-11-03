import { ApiError } from "../api";

/** Mensaje de error de la API con su trace_id en pequeño, para buscarlo en Jaeger. */
export function ErrorNotice({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Error inesperado";
  const traceId = error instanceof ApiError ? error.traceId : "";
  return (
    <div className="notice notice-error" role="alert">
      <span>{message}</span>
      {traceId && <small className="trace-id">trace_id: {traceId}</small>}
    </div>
  );
}
