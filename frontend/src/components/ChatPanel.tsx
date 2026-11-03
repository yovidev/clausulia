import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { askQuestion } from "../api";
import type { AskOut } from "../types";
import { AnswerCard } from "./AnswerCard";
import { ErrorNotice } from "./ErrorNotice";

interface Turn {
  id: number;
  question: string;
  response?: AskOut;
  error?: unknown;
}

const MIN_LENGTH = 3;
const MAX_LENGTH = 1000;

/** Preguntas independientes: el historial es solo local a la sesión del navegador. */
export function ChatPanel({ onOpenSource }: { onOpenSource: (chunkId: string) => void }) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const nextId = useRef(0);
  const bottom = useRef<HTMLDivElement>(null);

  const ask = useMutation({ mutationFn: askQuestion });

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [turns]);

  const trimmed = question.trim();
  const canSend = trimmed.length >= MIN_LENGTH && !ask.isPending;

  function updateTurn(id: number, change: Partial<Turn>) {
    setTurns((current) => current.map((t) => (t.id === id ? { ...t, ...change } : t)));
  }

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!canSend) return;
    const id = nextId.current++;
    setTurns((current) => [...current, { id, question: trimmed }]);
    setQuestion("");
    ask.mutate(
      { question: trimmed },
      {
        onSuccess: (response) => updateTurn(id, { response }),
        onError: (error) => updateTurn(id, { error }),
      },
    );
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter envía; Mayús+Enter añade una línea.
    if (event.key === "Enter" && !event.shiftKey) submit(event);
  }

  return (
    <section className="panel chat">
      <h2>Preguntas</h2>
      <div className="history">
        {turns.length === 0 && (
          <p className="muted">
            Pregunta sobre tus contratos, por ejemplo: «¿Cuál es la penalización por retraso en
            la entrega?». Cada respuesta cita el documento y la página.
          </p>
        )}
        {turns.map((turn) => (
          <div key={turn.id} className="turn">
            <div className="question">{turn.question}</div>
            {turn.response && <AnswerCard response={turn.response} onOpenSource={onOpenSource} />}
            {turn.error !== undefined && <ErrorNotice error={turn.error} />}
            {!turn.response && turn.error === undefined && (
              <div className="loading" aria-live="polite">
                Buscando en los documentos…
              </div>
            )}
          </div>
        ))}
        <div ref={bottom} />
      </div>
      <form className="ask-form" onSubmit={submit}>
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Escribe tu pregunta…"
          maxLength={MAX_LENGTH}
          rows={2}
          aria-label="Pregunta"
        />
        <button type="submit" disabled={!canSend}>
          {ask.isPending ? "Preguntando…" : "Preguntar"}
        </button>
      </form>
    </section>
  );
}
