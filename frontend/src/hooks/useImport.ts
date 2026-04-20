import { useQuery, useMutation } from '@tanstack/react-query';
import client from '../api/client';
import type { ImportDirectory, SearchResult } from '../types';

export interface ImportRequest {
  directory_name: string;
  provider: string;
  provider_id: string;
  anime_title: string;
  anime_title_native?: string | null;
  anime_year?: number | null;
}

export function useImportDirectories(enabled: boolean) {
  return useQuery<ImportDirectory[]>({
    queryKey: ['import', 'directories'],
    queryFn: async () => {
      const { data } = await client.get<ImportDirectory[]>('/import/directories');
      return data;
    },
    enabled,
    staleTime: 0,
    gcTime: 0,
  });
}

export function useMetadataSearch(provider: string, query: string) {
  return useQuery<SearchResult[]>({
    queryKey: ['metadata', 'search', provider, query],
    queryFn: async () => {
      const { data } = await client.get<SearchResult[]>('/metadata/search', {
        params: { provider, q: query },
      });
      return data;
    },
    enabled: query.length > 0,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

export function useImportProject() {
  return useMutation({
    mutationFn: async (body: ImportRequest) => {
      const { data } = await client.post('/import', body);
      return data;
    },
  });
}
