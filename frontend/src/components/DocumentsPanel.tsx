import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { listDocuments, uploadDocument } from "../api";
import { pollInterval } from "../logic";
import type { UploadOut } from "../types";
import { ErrorNotice } from "./ErrorNotice";
import { StatusBadge } from "./StatusBadge";
import { UploadZone } from "./UploadZone";

type UploadNotice =
  | { id: number; kind: "duplicate"; document: UploadOut }
  | { id: number; kind: "error"; filename: string; error: unknown };

let nextNoticeId = 0;

export function DocumentsPanel() {
  const queryClient = useQueryClient();
  const [notices, setNotices] = useState<UploadNotice[]>([]);

  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: listDocuments,
    // Se reevalúa tras cada respuesta: el polling se detiene solo cuando todo terminó.
    refetchInterval: (query) => pollInterval(query.state.data?.items),
  });

  const upload = useMutation({
    mutationFn: uploadDocument,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });

  function addNotice(notice: UploadNotice) {
    setNotices((current) => [notice, ...current].slice(0, 5));
  }

  function handleUpload(file: File) {
    upload.mutate(file, {
      onSuccess: (document) => {
        if (document.duplicate) {
          addNotice({ id: nextNoticeId++, kind: "duplicate", document });
        }
      },
      onError: (error) => {
        addNotice({ id: nextNoticeId++, kind: "error", filename: file.name, error });
      },
    });
  }

  const items = documents.data?.items ?? [];

  return (
    <section className="panel">
      <h2>Documentos</h2>
      <UploadZone onUpload={handleUpload} />
      {upload.isPending && <p className="muted">Subiendo…</p>}

      {notices.map((notice) =>
        notice.kind === "duplicate" ? (
          <div key={notice.id} className="notice notice-warning">
            «{notice.document.filename}» ya estaba subido; se usa el documento existente
            {notice.document.status === "pending" && " y se vuelve a procesar"}.
          </div>
        ) : (
          <div key={notice.id}>
            <small className="muted">No se pudo subir «{notice.filename}»:</small>
            <ErrorNotice error={notice.error} />
          </div>
        ),
      )}

      {documents.isError && <ErrorNotice error={documents.error} />}
      {documents.isPending && <p className="muted">Cargando documentos…</p>}
      {documents.isSuccess && items.length === 0 && (
        <p className="muted">Aún no hay documentos. Sube un contrato para empezar.</p>
      )}

      <ul className="document-list">
        {items.map((document) => (
          <li key={document.id} className="document">
            <div className="document-name" title={document.filename}>
              {document.filename}
            </div>
            <StatusBadge document={document} />
            {document.status === "ready" && (
              <small className="muted">
                {document.page_count} páginas · {document.chunk_count} fragmentos
              </small>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
