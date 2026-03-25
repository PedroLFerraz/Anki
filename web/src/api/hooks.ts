import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as api from './client';
import type { GenerateRequest, ArtistRequest, ExportRequest } from './types';

export function useCards(params?: { deck_type?: string; status?: string }) {
  return useQuery({
    queryKey: ['cards', params],
    queryFn: () => api.fetchCards(params),
  });
}

export function useDeckTypes() {
  return useQuery({
    queryKey: ['deck-types'],
    queryFn: api.fetchDeckTypes,
  });
}

export function useAnalytics(deck_type?: string) {
  return useQuery({
    queryKey: ['analytics', deck_type],
    queryFn: () => api.fetchAnalytics(deck_type),
  });
}

export function useUpdateCardStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ cardId, status }: { cardId: number; status: string }) =>
      api.updateCardStatus(cardId, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cards'] }),
  });
}

export function useFetchMedia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (cardId: number) => api.fetchMediaForCard(cardId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cards'] }),
  });
}

export function useGenerate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: GenerateRequest) => api.generateCards(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cards'] }),
  });
}

export function useGenerateFromArtist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ArtistRequest) => api.generateFromArtist(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cards'] }),
  });
}

export function useExport() {
  return useMutation({
    mutationFn: (data: ExportRequest) => api.exportCards(data),
  });
}

export function useClearCards() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params?: { status?: string; deck_type?: string }) =>
      api.clearCards(params?.status, params?.deck_type),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cards'] }),
  });
}
