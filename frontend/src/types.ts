// Reflejo a mano de los esquemas Pydantic del backend (app/schemas/*.py).

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export interface DocumentOut {
  id: string;
  filename: string;
  sha256: string;
  size_bytes: number;
  status: DocumentStatus;
  error_code: string | null;
  error_message: string | null;
  page_count: number | null;
  chunk_count: number | null;
  created_at: string;
  updated_at: string;
}

export interface UploadOut extends DocumentOut {
  duplicate: boolean;
}

export interface DocumentListOut {
  items: DocumentOut[];
}

export interface ChunkOut {
  id: string;
  document_id: string;
  filename: string;
  chunk_index: number;
  page_number: number;
  content: string;
}

export type Confidence = "high" | "medium" | "low";

export interface AskIn {
  question: string;
  document_ids?: string[];
}

export interface CitationOut {
  chunk_id: string;
  document_id: string;
  document_name: string;
  page: number;
  snippet: string;
}

export interface AskOut {
  status: "answered" | "insufficient_evidence" | "rejected";
  answer: string | null;
  citations: CitationOut[];
  confidence: Confidence | null;
  has_conflict: boolean;
}

export interface ErrorOut {
  error: {
    code: string;
    message: string;
    trace_id: string;
  };
}
