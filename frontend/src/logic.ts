// Lógica pura de la interfaz (sin React), fácil de probar.
import type { Confidence, DocumentOut, DocumentStatus } from "./types";

export const MAX_UPLOAD_MB = 20;
export const POLL_INTERVAL_MS = 2000;

/** Devuelve el motivo del rechazo, o null si el archivo es aceptable. */
export function validatePdfFile(file: File): string | null {
  const looksLikePdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  if (!looksLikePdf) {
    return `"${file.name}" no es un PDF. Solo se aceptan archivos PDF.`;
  }
  if (file.size === 0) {
    return `"${file.name}" está vacío.`;
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    return `"${file.name}" supera el máximo de ${MAX_UPLOAD_MB} MB.`;
  }
  return null;
}

/** Polling cada 2 s solo mientras algún documento siga en cola o procesándose. */
export function pollInterval(documents: DocumentOut[] | undefined): number | false {
  const active = documents?.some((d) => d.status === "pending" || d.status === "processing");
  return active ? POLL_INTERVAL_MS : false;
}

export const STATUS_LABELS: Record<DocumentStatus, string> = {
  pending: "En cola",
  processing: "Procesando",
  ready: "Listo",
  failed: "Falló",
};

const FAILURE_REASONS: Record<string, string> = {
  INVALID_PDF: "El archivo no es un PDF válido o está dañado.",
  ENCRYPTED_PDF: "El PDF está protegido con contraseña.",
  TOO_MANY_PAGES: "El PDF supera el máximo de páginas permitido.",
  NO_TEXT_LAYER: "El PDF no tiene texto seleccionable (posiblemente es un escaneo).",
  FILE_MISSING: "No se encontró el archivo subido en el servidor.",
  INGESTION_FAILED: "El procesamiento falló tras varios reintentos.",
  STUCK: "El procesamiento no terminó tras varios intentos.",
};

/** Motivo legible de un fallo de ingesta. */
export function failureReason(code: string | null, message: string | null): string {
  if (code && FAILURE_REASONS[code]) return FAILURE_REASONS[code];
  return message || "Error desconocido al procesar el documento.";
}

export const CONFIDENCE_LABELS: Record<Confidence, string> = {
  high: "Confianza alta",
  medium: "Confianza media",
  low: "Confianza baja",
};
