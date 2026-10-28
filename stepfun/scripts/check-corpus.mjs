#!/usr/bin/env node
/**
 * 校验评测集：文档文件存在、id 唯一、每条查询的 gold 都能对上文档 id。
 *   node scripts/check-corpus.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const corpusDir = path.resolve(here, '../web/public/corpus');
const evalPath = path.join(corpusDir, 'eval.json');

const data = JSON.parse(fs.readFileSync(evalPath, 'utf8'));
const errors = [];
const ids = new Set();

for (const doc of data.docs) {
  if (ids.has(doc.id)) errors.push(`文档 id 重复：${doc.id}`);
  ids.add(doc.id);
  const file = path.join(corpusDir, doc.file);
  if (!fs.existsSync(file)) errors.push(`缺少文件：${doc.file}`);
  else if (fs.readFileSync(file, 'utf8').trim().length < 100) errors.push(`文件过短：${doc.file}`);
}

for (const q of data.queries) {
  if (!q.query?.trim()) errors.push('存在空查询');
  if (!Array.isArray(q.gold) || q.gold.length === 0) errors.push(`查询缺少 gold：${q.query}`);
  for (const g of q.gold ?? []) {
    if (!ids.has(g)) errors.push(`查询「${q.query}」的 gold 不存在：${g}`);
  }
}

const chars = data.docs.reduce((sum, d) => {
  const file = path.join(corpusDir, d.file);
  return sum + (fs.existsSync(file) ? fs.readFileSync(file, 'utf8').length : 0);
}, 0);

if (errors.length) {
  console.error(errors.map((e) => `✗ ${e}`).join('\n'));
  process.exit(1);
}

console.log(`✓ 语料校验通过：${data.docs.length} 篇 / ${chars} 字符 / ${data.queries.length} 条查询`);
