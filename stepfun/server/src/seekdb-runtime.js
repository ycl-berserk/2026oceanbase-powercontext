import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

const PLATFORM_PACKAGES = {
  'linux-x64': ['@oceanbase/seekdb-node-linux-x64-gnu', 'native/seekdb'],
  'linux-arm64': ['@oceanbase/seekdb-node-linux-arm64-gnu', 'native/seekdb'],
  'darwin-arm64': ['@oceanbase/seekdb-node-darwin-arm64', 'native/seekdb'],
  'win32-x64': ['@oceanbase/seekdb-node-win32-x64', 'seekdb.exe'],
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function platformKey() {
  const arch = process.arch === 'arm64' ? 'arm64' : 'x64';
  return `${process.platform}-${arch}`;
}

/** 在 node_modules 里找随包提供的 seekdb 可执行文件 */
export function findSeekdbBinary() {
  const entry = PLATFORM_PACKAGES[platformKey()];
  if (!entry) {
    throw new Error(
      `seekdb 未提供当前平台的原生包：${platformKey()}。支持 linux-x64 / linux-arm64 / darwin-arm64 / win32-x64。`
    );
  }
  const [pkg, rel] = entry;
  let root;
  try {
    root = path.dirname(require.resolve(`${pkg}/package.json`));
  } catch {
    throw new Error(`缺少原生运行时包 ${pkg}，请重新执行 npm install（不要跳过 optionalDependencies）。`);
  }
  const bin = path.join(root, rel);
  if (!fs.existsSync(bin)) {
    throw new Error(`原生包 ${pkg} 中未找到可执行文件：${bin}`);
  }
  return bin;
}

export function isPortOpen(host, port, timeoutMs = 800) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port });
    const done = (ok) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeoutMs);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
  });
}

export async function findFreePort(host = '127.0.0.1') {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once('error', reject);
    srv.listen(0, host, () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function describeServer(host, port) {
  try {
    const mysql = (await import('mysql2/promise')).default;
    const conn = await mysql.createConnection({ host, port, user: 'root', password: '', connectTimeout: 2000 });
    const [rows] = await conn.query('SELECT VERSION() AS v');
    await conn.end();
    return String(rows[0]?.v ?? '');
  } catch {
    return null;
  }
}

/**
 * 确保有一个可用的 seekdb server：
 * 1) SEEKDB_HOST 指定外部实例 → 直接使用
 * 2) 目标端口已有 seekdb 在跑 → 复用
 * 3) 否则用随包原生二进制拉起一个本地实例（TCP）
 */
export async function ensureSeekdb({ dataDir, port, log = console.log }) {
  const externalHost = process.env.SEEKDB_HOST;
  const targetPort = Number(process.env.SEEKDB_PORT ?? port);

  if (externalHost) {
    const version = await describeServer(externalHost, targetPort);
    if (!version) throw new Error(`无法连接外部 seekdb ${externalHost}:${targetPort}（检查 SEEKDB_HOST/PORT）`);
    log(`[seekdb] 使用外部实例 ${externalHost}:${targetPort} · ${version}`);
    return { mode: 'external', host: externalHost, port: targetPort, version, stop: async () => {} };
  }

  fs.mkdirSync(path.join(dataDir, 'store'), { recursive: true });
  fs.mkdirSync(path.join(dataDir, 'log'), { recursive: true });

  const existing = await describeServer('127.0.0.1', targetPort);
  if (existing) {
    log(`[seekdb] 复用已在监听的本机实例 :${targetPort} · ${existing}`);
    return { mode: 'reuse', host: '127.0.0.1', port: targetPort, version: existing, stop: async () => {} };
  }

  if (await isPortOpen('127.0.0.1', targetPort)) {
    const freePort = await findFreePort();
    log(`[seekdb] 端口 ${targetPort} 被其它进程占用，改用 ${freePort}`);
    return ensureSeekdb({ dataDir, port: freePort, log });
  }

  const bin = findSeekdbBinary();
  const memory = process.env.SEEKDB_MEMORY ?? '2G';
  const logFile = path.join(dataDir, 'spawn.log');
  const out = fs.openSync(logFile, 'w');
  const args = [
    '--port',
    String(targetPort),
    '--base-dir',
    dataDir,
    '--data-dir',
    path.join(dataDir, 'store'),
    '--parameter',
    `memory_limit=${memory}`,
    '--parameter',
    `cpu_count=${process.env.SEEKDB_CPU ?? Math.min(8, Math.max(2, (await import('node:os')).cpus().length - 2))}`,
    '--parameter',
    'datafile_size=1G',
    '--parameter',
    'log_disk_size=2G',
  ];

  log(`[seekdb] 启动本地实例：${path.basename(bin)} --port ${targetPort}（日志 ${logFile}）`);
  const child = spawn(bin, args, {
    cwd: path.dirname(bin),
    detached: true,
    stdio: ['ignore', out, out],
    env: { ...process.env, LD_LIBRARY_PATH: path.dirname(bin) },
  });
  child.unref();

  const deadline = Date.now() + 120_000;
  let version = null;
  while (Date.now() < deadline) {
    await sleep(700);
    version = await describeServer('127.0.0.1', targetPort);
    if (version) break;
  }
  if (!version) {
    throw new Error(
      `seekdb 启动超时（端口 ${targetPort}）。请查看 ${logFile} 和 ${path.join(dataDir, 'log', 'seekdb.log')}。` +
        `可选：设置 SEEKDB_HOST/SEEKDB_PORT 连接已有实例。`
    );
  }
  fs.writeFileSync(path.join(dataDir, 'seekdb.pid'), String(child.pid ?? ''));
  log(`[seekdb] 本地实例就绪 :${targetPort} · ${version}`);

  return {
    mode: 'spawned',
    host: '127.0.0.1',
    port: targetPort,
    version,
    pid: child.pid,
    stop: async () => {
      if (process.env.SEEKDB_KEEP === '1') return;
      try {
        process.kill(child.pid, 'SIGTERM');
      } catch {
        /* 已退出 */
      }
    },
  };
}
