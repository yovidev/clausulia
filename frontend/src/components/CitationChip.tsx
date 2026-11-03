import type { CitationOut } from "../types";

interface Props {
  citation: CitationOut;
  onOpen: (chunkId: string) => void;
}

/** Chip "documento · p. N"; al pulsarlo abre el fragmento fuente completo. */
export function CitationChip({ citation, onOpen }: Props) {
  return (
    <button
      type="button"
      className="chip"
      title={citation.snippet}
      onClick={() => onOpen(citation.chunk_id)}
    >
      {citation.document_name} · p. {citation.page}
    </button>
  );
}
