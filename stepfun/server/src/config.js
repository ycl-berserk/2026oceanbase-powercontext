import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const repoRoot = path.resolve(here, '../..');

/** seekdb 数据目录（本地实例的 base-dir，内部还有 store/ 与 log/） */
export const SEEKDB_DATA_DIR = process.env.SEEKDB_DATA_DIR ?? path.join(repoRoot, 'data', 'seekdb');
/** seekdb server 监听端口；SEEKDB_HOST 存在时表示连接外部实例 */
export const SEEKDB_PORT = Number(process.env.SEEKDB_PORT ?? 2881);
/** seekdb 内部的 database 名 */
export const SEEKDB_DATABASE = process.env.SEEKDB_DATABASE ?? 'kb';
/** 集合名前缀，避免和库里的其它表冲突 */
export const COLLECTION_PREFIX = 'kb_';
/** 知识库注册表（关系表，与向量集合同库） */
export const REGISTRY_TABLE = 'kb_registry';

export const PORT = Number(process.env.PORT ?? 8787);

export const WEB_DIST = path.join(repoRoot, 'web', 'dist');

export function ensureDataDir() {
  fs.mkdirSync(SEEKDB_DATA_DIR, { recursive: true });
}
