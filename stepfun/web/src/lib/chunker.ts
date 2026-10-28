import type { Chunk } from './types';

export interface ChunkOptions {
  /** 单块最大字符数 */
  maxChars: number;
  /** 相邻块重叠字符数 */
  overlap: number;
}

export const DEFAULT_CHUNK_OPTIONS: ChunkOptions = { maxChars: 320, overlap: 64 };

/** 去掉 YAML frontmatter 与 Markdown 标记，保留可读正文 */
export function cleanText(raw: string): string {
  let text = raw.replace(/^\uFEFF/, '');
  if (text.startsWith('---')) {
    const end = text.indexOf('\n---', 3);
    if (end > 0) text = text.slice(end + 4);
  }
  text = text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s{0,3}>\s?/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/\r\n?/g, '\n');
  return text.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
}

/** 以中英文句末标点为界切句，保留标点 */
export function splitSentences(text: string): string[] {
  const out: string[] = [];
  for (const para of text.split(/\n+/)) {
    const trimmed = para.trim();
    if (!trimmed) continue;
    const parts = trimmed.match(/[^。！？!?；;]+[。！？!?；;]?/g) ?? [trimmed];
    for (const p of parts) {
      const s = p.trim();
      if (s) out.push(s);
    }
  }
  return out;
}

function hardSplit(sentence: string, maxChars: number): string[] {
  const pieces: string[] = [];
  for (let i = 0; i < sentence.length; i += maxChars) {
    pieces.push(sentence.slice(i, i + maxChars));
  }
  return pieces;
}

/**
 * 按句子累积到 maxChars 上限切块，块间保留 overlap 字符重叠，避免语义被切断。
 */
export function chunkText(
  docId: string,
  docTitle: string,
  source: string,
  rawText: string,
  options: Partial<ChunkOptions> = {}
): Chunk[] {
  const { maxChars, overlap } = { ...DEFAULT_CHUNK_OPTIONS, ...options };
  const sentences = splitSentences(cleanText(rawText)).flatMap((s) =>
    s.length > maxChars ? hardSplit(s, maxChars) : [s]
  );

  const chunks: string[] = [];
  let current = '';
  for (const sentence of sentences) {
    if (!current) {
      current = sentence;
      continue;
    }
    if (current.length + sentence.length <= maxChars) {
      current += sentence;
    } else {
      chunks.push(current);
      const tail = overlap > 0 ? current.slice(-overlap) : '';
      current = tail + sentence;
      // 重叠后仍超长时先落盘，避免无限增长
      if (current.length > maxChars * 1.5) {
        chunks.push(current.slice(0, maxChars));
        current = current.slice(maxChars - overlap);
      }
    }
  }
  if (current) chunks.push(current);

  return chunks
    .map((text) => text.trim())
    .filter((text) => text.length > 0)
    .map((text, index) => ({
      id: `${docId}#${String(index).padStart(3, '0')}`,
      text,
      metadata: {
        docId,
        docTitle,
        chunkIndex: index,
        chars: text.length,
        source,
      },
    }));
}
