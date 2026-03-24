const BASE = '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchCards(params?: { deck_type?: string; status?: string }) {
  const sp = new URLSearchParams();
  if (params?.deck_type) sp.set('deck_type', params.deck_type);
  if (params?.status) sp.set('status', params.status);
  const qs = sp.toString();
  return request<import('./types').Card[]>(`/api/cards${qs ? `?${qs}` : ''}`);
}

export async function updateCardStatus(cardId: number, status: string) {
  return request<{ id: number; status: string }>(`/api/cards/${cardId}`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

export async function fetchMediaForCard(cardId: number) {
  return request<import('./types').FetchMediaResult>(`/api/cards/${cardId}/fetch-media`, {
    method: 'POST',
  });
}

export async function generateCards(data: import('./types').GenerateRequest) {
  return request<import('./types').GenerateResponse>('/api/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function generateFromArtist(data: import('./types').ArtistRequest) {
  return request<import('./types').GenerateResponse>('/api/generate/artist', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function exportCards(data: import('./types').ExportRequest) {
  const res = await fetch(`${BASE}/api/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  return res.blob();
}

export async function fetchDeckTypes() {
  return request<import('./types').DeckType[]>('/api/deck-types');
}

export async function fetchAnalytics(deck_type?: string) {
  const qs = deck_type ? `?deck_type=${deck_type}` : '';
  return request<import('./types').AnalyticsRow[]>(`/api/analytics${qs}`);
}
