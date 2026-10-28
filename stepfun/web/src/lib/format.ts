export const fmtMs = (v: number | null | undefined): string => {
  if (v == null) return '—';
  return v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;
};

export const fmtMb = (bytes: number | null | undefined): string => {
  if (!bytes) return '—';
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

export const fmtPct = (v: number | null | undefined, digits = 1): string =>
  v == null ? '—' : `${(v * 100).toFixed(digits)}%`;

export const fmtInt = (v: number | null | undefined): string =>
  v == null ? '—' : new Intl.NumberFormat('zh-CN').format(Math.round(v));

export const fmtTime = (ts: number): string =>
  new Date(ts).toLocaleString('zh-CN', { hour12: false });
