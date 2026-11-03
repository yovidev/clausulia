import { describe, expect, it } from "vitest";
import { failureReason, pollInterval, validatePdfFile } from "./logic";
import type { DocumentOut, DocumentStatus } from "./types";

function fileOfSize(name: string, type: string, bytes: number): File {
  const file = new File(["x"], name, { type });
  Object.defineProperty(file, "size", { value: bytes });
  return file;
}

describe("validatePdfFile", () => {
  it("rechaza un archivo que no es PDF", () => {
    const error = validatePdfFile(fileOfSize("foto.png", "image/png", 100));

    expect(error).toContain("no es un PDF");
  });

  it("rechaza un PDF de más de 20 MB", () => {
    const error = validatePdfFile(fileOfSize("grande.pdf", "application/pdf", 20 * 1024 * 1024 + 1));

    expect(error).toContain("20 MB");
  });

  it("acepta un PDF válido, también si el navegador no da el tipo", () => {
    expect(validatePdfFile(fileOfSize("a.pdf", "application/pdf", 1000))).toBeNull();
    expect(validatePdfFile(fileOfSize("B.PDF", "", 1000))).toBeNull();
  });
});

describe("pollInterval", () => {
  const withStatus = (status: DocumentStatus) => ({ status }) as DocumentOut;

  it("hace polling mientras haya documentos pendientes o en proceso", () => {
    expect(pollInterval([withStatus("ready"), withStatus("processing")])).toBe(2000);
    expect(pollInterval([withStatus("pending")])).toBe(2000);
  });

  it("se detiene cuando todos terminaron", () => {
    expect(pollInterval([withStatus("ready"), withStatus("failed")])).toBe(false);
    expect(pollInterval([])).toBe(false);
    expect(pollInterval(undefined)).toBe(false);
  });
});

describe("failureReason", () => {
  it("traduce los códigos conocidos", () => {
    expect(failureReason("ENCRYPTED_PDF", null)).toContain("contraseña");
  });
});
