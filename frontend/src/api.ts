import type {
  AskIn,
  AskOut,
  ChunkOut,
  DocumentListOut,
  ErrorOut,
  UploadOut,
} from "./types";

/** Error de la API con el formato único del backend; traceId sirve para buscarlo en Jaeger. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly traceId: string;

  constructor(status: number, code: string, message: string, traceId = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.traceId = traceId;
  }
}

// Respuestas que no vienen de la API (por ejemplo, nginx cortando un archivo grande).
const STATUS_MESSAGES: Record<number, string> = {
  413: "El archivo supera el tamaño máximo permitido (20 MB)",
  502: "El servidor no está disponible en este momento",
  503: "El servicio no está disponible en este momento",
  504: "El servidor tardó demasiado en responder",
};

function isErrorOut(body: unknown): body is ErrorOut {
  const error = (body as ErrorOut | null)?.error;
  return typeof error?.code === "string" && typeof error.message === "string";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "No se pudo conectar con el servidor");
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (isErrorOut(body)) {
      const { code, message, trace_id } = body.error;
      throw new ApiError(response.status, code, message, trace_id);
    }
    const message = STATUS_MESSAGES[response.status] ?? `Error inesperado (${response.status})`;
    throw new ApiError(response.status, `HTTP_${response.status}`, message);
  }
  return body as T;
}

export function listDocuments(): Promise<DocumentListOut> {
  return request("/documents");
}

export function uploadDocument(file: File): Promise<UploadOut> {
  const form = new FormData();
  form.append("file", file);
  return request("/documents", { method: "POST", body: form });
}

export function getChunk(chunkId: string): Promise<ChunkOut> {
  return request(`/chunks/${encodeURIComponent(chunkId)}`);
}

export function askQuestion(body: AskIn): Promise<AskOut> {
  return request("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
