// Client-side JD parser — PDF + .docx → plain text string for form_data.jd_text.
// Per spec NG5: no backend parser. PDF uses pdfjs-dist; .docx uses mammoth.
//
// Both deps are dynamic-imported to keep them out of the route's initial JS
// bundle (form-stage only loads them when the user actually picks a file).

export const MAX_JD_BYTES = 5 * 1024 * 1024; // 5MB cap per spec §9.

const PDF_MIME = 'application/pdf';
const DOCX_MIME =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

export class UnsupportedJdTypeError extends Error {
  constructor(type: string) {
    super(`Unsupported JD file type: ${type || 'unknown'}. Use PDF or .docx, or paste text.`);
    this.name = 'UnsupportedJdTypeError';
  }
}

export class JdTooLargeError extends Error {
  constructor(bytes: number) {
    super(`JD file is ${(bytes / 1024 / 1024).toFixed(1)}MB; max is ${MAX_JD_BYTES / 1024 / 1024}MB.`);
    this.name = 'JdTooLargeError';
  }
}

export class JdParseError extends Error {
  constructor(detail: string) {
    super(`Couldn't read this file: ${detail}. Try pasting the text instead.`);
    this.name = 'JdParseError';
  }
}

export function isSupportedJdFile(file: File): boolean {
  if (file.size > MAX_JD_BYTES) return false;
  if (file.type === PDF_MIME) return true;
  if (file.type === DOCX_MIME) return true;
  // Some browsers (Safari) set empty MIME for .docx — fall back to extension.
  const name = file.name.toLowerCase();
  if (file.type === '' && (name.endsWith('.pdf') || name.endsWith('.docx'))) return true;
  return false;
}

export async function parseJdFile(file: File): Promise<string> {
  if (file.size > MAX_JD_BYTES) throw new JdTooLargeError(file.size);

  const name = file.name.toLowerCase();
  const isPdf = file.type === PDF_MIME || (file.type === '' && name.endsWith('.pdf'));
  const isDocx = file.type === DOCX_MIME || (file.type === '' && name.endsWith('.docx'));

  if (!isPdf && !isDocx) throw new UnsupportedJdTypeError(file.type);

  const buf = await file.arrayBuffer();

  if (isPdf) return parsePdf(buf);
  return parseDocx(buf);
}

async function parsePdf(buf: ArrayBuffer): Promise<string> {
  try {
    // Dynamic import keeps pdfjs out of the initial bundle.
    const pdfjs = (await import('pdfjs-dist')) as unknown as {
      getDocument: (args: { data: ArrayBuffer }) => { promise: Promise<PdfDocument> };
      GlobalWorkerOptions: { workerSrc: string };
    };
    // Point worker at the CDN-shipped build so we don't have to wire a
    // bundler asset. Versions are pinned in package.json.
    if (typeof window !== 'undefined') {
      pdfjs.GlobalWorkerOptions.workerSrc =
        'https://cdn.jsdelivr.net/npm/pdfjs-dist@4/build/pdf.worker.min.mjs';
    }

    const doc = await pdfjs.getDocument({ data: buf }).promise;
    const parts: string[] = [];
    for (let i = 1; i <= doc.numPages; i++) {
      const page = await doc.getPage(i);
      const txt = await page.getTextContent();
      const lines = txt.items
        .map((it) => ('str' in it ? it.str : ''))
        .filter(Boolean)
        .join(' ');
      parts.push(lines);
    }
    return parts.join('\n\n').trim();
  } catch (e) {
    throw new JdParseError((e as Error).message || 'PDF parse failed');
  }
}

interface PdfDocument {
  numPages: number;
  getPage: (n: number) => Promise<{ getTextContent: () => Promise<{ items: Array<{ str?: string }> }> }>;
}

async function parseDocx(buf: ArrayBuffer): Promise<string> {
  try {
    const mammoth = (await import('mammoth')) as unknown as {
      extractRawText: (args: { arrayBuffer: ArrayBuffer }) => Promise<{ value: string }>;
    };
    const result = await mammoth.extractRawText({ arrayBuffer: buf });
    return (result.value || '').trim();
  } catch (e) {
    throw new JdParseError((e as Error).message || '.docx parse failed');
  }
}
