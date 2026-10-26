// Isolated adapter around the unmodified, vendored Readest converter.
// Book XML is consumed locally on stdin; this process has no network workflow.
import fs from 'node:fs';
import { createHash } from 'node:crypto';
import { stripTypeScriptTypes } from 'node:module';
import { JSDOM } from '../.runtime/node/node_modules/jsdom/lib/api.js';

const sourceURL = new URL('../third_party/positions/xcfi.ts', import.meta.url);
const cfiURL = new URL('../third_party/positions/epubcfi.mjs', import.meta.url);
const { parse, toRange } = await import(cfiURL.href);
let source = fs.readFileSync(sourceURL, 'utf8')
  .replace("import { BookDoc } from '@/libs/document';", '')
  .replace("import { BookFormat } from '@/types/book';", '')
  .replace("'foliate-js/epubcfi.js'", JSON.stringify(cfiURL.href));
source = stripTypeScriptTypes(source, { mode: 'strip' });
const { XCFI } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const requests = JSON.parse(fs.readFileSync(0, 'utf8'));
const results = [];
for (const request of requests) {
  const { window } = new JSDOM(request.xml, { contentType: 'application/xhtml+xml' });
  for (const name of ['Node', 'NodeFilter', 'Range', 'Element', 'Text']) globalThis[name] = window[name];
  try {
    const doc = window.document;
    if (doc.querySelector('parsererror')) throw new Error('Invalid XHTML');
    const converter = new XCFI(doc, request.spine_index);
    if (request.xpointer) {
      results.push({ cfi: converter.xPointerToCFI(request.xpointer, request.end_xpointer) });
    } else {
      const converted = converter.cfiToXPointer(request.cfi);
      const result = { ...converted, reverse_cfi: converter.xPointerToCFI(converted.pos0 || converted.xpointer, converted.pos1) };
      if (request.inspect_range) {
        const parts = parse(request.cfi);
        if (!parts.parent) throw new Error('A highlight requires a CFI range');
        parts.parent.shift(); // Foliate toRange consumes the document path.
        const range = toRange(doc, parts);
        if (!range || range.collapsed) throw new Error('The highlight range is empty');
        result.selection_sha256 = createHash('sha256').update(range.toString(), 'utf8').digest('hex');
      }
      results.push(result);
    }
  } catch (error) {
    results.push({ error: error.message });
  } finally {
    window.close();
  }
}
process.stdout.write(JSON.stringify(results));
