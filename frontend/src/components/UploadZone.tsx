import { useRef, useState, type DragEvent } from "react";
import { MAX_UPLOAD_MB, validatePdfFile } from "../logic";

interface Props {
  onUpload: (file: File) => void;
  disabled?: boolean;
}

/** Zona para arrastrar o elegir PDFs. Valida tipo y tamaño antes de subir. */
export function UploadZone({ onUpload, disabled = false }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [rejections, setRejections] = useState<string[]>([]);

  function handleFiles(files: FileList | null) {
    if (!files) return;
    const errors: string[] = [];
    for (const file of Array.from(files)) {
      const error = validatePdfFile(file);
      if (error) errors.push(error);
      else onUpload(file);
    }
    setRejections(errors);
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (!disabled) handleFiles(event.dataTransfer.files);
  }

  return (
    <div>
      <div
        className={`dropzone${dragging ? " dropzone-active" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <p>Arrastra aquí tus contratos en PDF</p>
        <button type="button" disabled={disabled} onClick={() => input.current?.click()}>
          Elegir archivos
        </button>
        <small>Solo PDF, máximo {MAX_UPLOAD_MB} MB</small>
        <input
          ref={input}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          aria-label="Elegir archivos PDF"
          onChange={(event) => {
            handleFiles(event.target.files);
            event.target.value = ""; // permite volver a elegir el mismo archivo
          }}
        />
      </div>
      {rejections.map((message) => (
        <div key={message} className="notice notice-error" role="alert">
          {message}
        </div>
      ))}
    </div>
  );
}
