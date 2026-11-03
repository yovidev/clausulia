import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import type { AskOut, CitationOut, DocumentOut } from "../types";
import { AnswerCard } from "./AnswerCard";
import { CitationChip } from "./CitationChip";
import { ErrorNotice } from "./ErrorNotice";
import { StatusBadge } from "./StatusBadge";
import { UploadZone } from "./UploadZone";

const citation: CitationOut = {
  chunk_id: "c-1",
  document_id: "d-1",
  document_name: "contrato-acme.pdf",
  page: 7,
  snippet: "La penalización por retraso…",
};

function makeDocument(change: Partial<DocumentOut>): DocumentOut {
  return {
    id: "d-1",
    filename: "contrato.pdf",
    sha256: "a".repeat(64),
    size_bytes: 1000,
    status: "ready",
    error_code: null,
    error_message: null,
    page_count: 3,
    chunk_count: 5,
    created_at: "2026-11-03T10:00:00Z",
    updated_at: "2026-11-03T10:00:00Z",
    ...change,
  };
}

describe("CitationChip", () => {
  it("muestra documento y página, y abre el fragmento al pulsarlo", () => {
    const onOpen = vi.fn();
    render(<CitationChip citation={citation} onOpen={onOpen} />);

    const chip = screen.getByRole("button", { name: "contrato-acme.pdf · p. 7" });
    fireEvent.click(chip);

    expect(onOpen).toHaveBeenCalledWith("c-1");
  });
});

describe("StatusBadge", () => {
  it("muestra el estado failed con su motivo traducido", () => {
    render(
      <StatusBadge
        document={makeDocument({ status: "failed", error_code: "NO_TEXT_LAYER" })}
      />,
    );

    expect(screen.getByText("Falló").className).toContain("status-failed");
    expect(screen.getByText(/no tiene texto seleccionable/)).toBeTruthy();
  });

  it("usa el mensaje del backend si el código no es conocido", () => {
    render(
      <StatusBadge
        document={makeDocument({
          status: "failed",
          error_code: "OTRO",
          error_message: "Algo raro",
        })}
      />,
    );

    expect(screen.getByText("Algo raro")).toBeTruthy();
  });

  it("no muestra motivo si el documento está listo", () => {
    render(<StatusBadge document={makeDocument({ status: "ready" })} />);

    expect(screen.getByText("Listo")).toBeTruthy();
    expect(document.querySelector(".status-reason")).toBeNull();
  });
});

describe("UploadZone", () => {
  it("rechaza un archivo que no es PDF sin subirlo", () => {
    const onUpload = vi.fn();
    render(<UploadZone onUpload={onUpload} />);
    const notPdf = new File(["hola"], "notas.txt", { type: "text/plain" });

    fireEvent.change(screen.getByLabelText("Elegir archivos PDF"), {
      target: { files: [notPdf] },
    });

    expect(onUpload).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("no es un PDF");
  });

  it("sube un PDF válido", () => {
    const onUpload = vi.fn();
    render(<UploadZone onUpload={onUpload} />);
    const pdf = new File(["%PDF-1.7"], "contrato.pdf", { type: "application/pdf" });

    fireEvent.change(screen.getByLabelText("Elegir archivos PDF"), {
      target: { files: [pdf] },
    });

    expect(onUpload).toHaveBeenCalledWith(pdf);
  });
});

describe("AnswerCard", () => {
  const answered: AskOut = {
    status: "answered",
    answer: "Es del 2 % semanal.",
    citations: [citation],
    confidence: "medium",
    has_conflict: false,
  };

  it("muestra la confianza y las citas", () => {
    render(<AnswerCard response={answered} onOpenSource={() => {}} />);

    expect(screen.getByText("Confianza media")).toBeTruthy();
    expect(screen.getByRole("button", { name: "contrato-acme.pdf · p. 7" })).toBeTruthy();
  });

  it("avisa de un conflicto entre documentos", () => {
    render(<AnswerCard response={{ ...answered, has_conflict: true }} onOpenSource={() => {}} />);

    expect(screen.getByText("Los documentos se contradicen.")).toBeTruthy();
  });

  it("avisa cuando no hay evidencia suficiente", () => {
    const response: AskOut = {
      status: "insufficient_evidence",
      answer: "No hay evidencia suficiente en los documentos.",
      citations: [],
      confidence: null,
      has_conflict: false,
    };
    render(<AnswerCard response={response} onOpenSource={() => {}} />);

    expect(screen.getByText("Sin evidencia suficiente.")).toBeTruthy();
  });
});

describe("ErrorNotice", () => {
  it("muestra el mensaje de la API y el trace_id", () => {
    render(<ErrorNotice error={new ApiError(429, "LLM_RATE_LIMITED", "Inténtalo luego", "abc123")} />);

    expect(screen.getByText("Inténtalo luego")).toBeTruthy();
    expect(screen.getByText("trace_id: abc123")).toBeTruthy();
  });
});
