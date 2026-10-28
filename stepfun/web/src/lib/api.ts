import type { KbInfo, SearchResponse } from './types';

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error(data?.error ?? `HTTP ${res.status}`);
  return data as T;
}

export const api = {
  health: () =>
    request<{ ok: boolean; mode: string; path: string; database: string; version: string }>('/api/health'),

  listKbs: () => request<{ kbs: KbInfo[] }>('/api/kbs'),

  createKb: (body: { name: string; label: string; model: string; dimension: number }) =>
    request<{ name: string; createMs: number }>('/api/kbs', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  deleteKb: (name: string) => request<{ ok: boolean }>(`/api/kbs/${name}`, { method: 'DELETE' }),

  addDocuments: (
    name: string,
    body: {
      chunks: { id: string; text: string; metadata: Record<string, unknown> }[];
      embeddings: number[][];
      batchSize?: number;
      refresh?: boolean;
      verify?: boolean;
    }
  ) =>
    request<{
      inserted: number;
      total: number;
      timings: { writeMs: number; refreshMs: number };
      verification: { probeId: string; hit: boolean; topIds: string[]; probeMs: number } | null;
    }>(`/api/kbs/${name}/documents`, { method: 'POST', body: JSON.stringify(body) }),

  listDocuments: (name: string, limit = 50, offset = 0) =>
    request<{ docs: { id: string; text: string; metadata: Record<string, unknown> | null }[] }>(
      `/api/kbs/${name}/documents?limit=${limit}&offset=${offset}`
    ),

  deleteDocuments: (name: string, ids: string[]) =>
    request<{ deleted: number; total: number }>(`/api/kbs/${name}/documents`, {
      method: 'DELETE',
      body: JSON.stringify({ ids }),
    }),

  refresh: (name: string) =>
    request<{ refreshMs: number; total: number }>(`/api/kbs/${name}/refresh`, { method: 'POST' }),

  search: (
    name: string,
    body: {
      query: string;
      embedding?: number[];
      keyword?: string;
      mode?: 'hybrid' | 'vector' | 'keyword';
      topK?: number;
      poolSize?: number;
      rankWindowSize?: number;
      rankConstant?: number;
    }
  ) =>
    request<SearchResponse>(`/api/kbs/${name}/search`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};
