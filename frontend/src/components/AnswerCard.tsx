import { CONFIDENCE_LABELS } from "../logic";
import type { AskOut } from "../types";
import { CitationChip } from "./CitationChip";

interface Props {
  response: AskOut;
  onOpenSource: (chunkId: string) => void;
}

export function AnswerCard({ response, onOpenSource }: Props) {
  if (response.status === "rejected") {
    return (
      <div className="answer">
        <div className="notice notice-error">
          No se pudo generar una respuesta fiable: el modelo devolvió un formato inválido.
          Intenta reformular la pregunta.
        </div>
      </div>
    );
  }

  if (response.status === "insufficient_evidence") {
    return (
      <div className="answer">
        <div className="notice notice-warning">
          <strong>Sin evidencia suficiente.</strong> {response.answer}
        </div>
      </div>
    );
  }

  return (
    <div className="answer">
      <div className="answer-header">
        {response.confidence && (
          <span className={`badge confidence-${response.confidence}`}>
            {CONFIDENCE_LABELS[response.confidence]}
          </span>
        )}
      </div>
      {response.has_conflict && (
        <div className="notice notice-warning">
          <strong>Los documentos se contradicen.</strong> Revisa ambas versiones en las citas.
        </div>
      )}
      <p className="answer-text">{response.answer}</p>
      <div className="chips">
        {response.citations.map((citation) => (
          <CitationChip key={citation.chunk_id} citation={citation} onOpen={onOpenSource} />
        ))}
      </div>
    </div>
  );
}
