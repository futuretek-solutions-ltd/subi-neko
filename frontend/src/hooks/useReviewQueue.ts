import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import type { ReviewQueue } from '../types';

export function useReviewQueue(projectId: number, enabled: boolean) {
  return useQuery<ReviewQueue>({
    queryKey: ['projects', projectId, 'review-queue'],
    queryFn: async () => {
      const { data } = await client.get<ReviewQueue>(`/projects/${projectId}/review-queue`);
      return data;
    },
    enabled,
    staleTime: 5_000,
  });
}

function invalidateQueueCaches(queryClient: ReturnType<typeof useQueryClient>, projectId: number) {
  queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'review-queue'] });
  queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'files'] });
  queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'stats'] });
}

export function useResolveQueueItem(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ fileId, issueId }: { fileId: number; issueId: number }) => {
      await client.post(`/projects/${projectId}/files/${fileId}/qa-issues/${issueId}/resolve`);
    },
    onSuccess: () => invalidateQueueCaches(queryClient, projectId),
  });
}

export function useSaveQueueTranslation(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ fileId, eventId, translatedText }: {
      fileId: number; eventId: number; translatedText: string;
    }) => {
      await client.put(
        `/projects/${projectId}/files/${fileId}/subtitle-events/${eventId}`,
        { translated_text: translatedText },
      );
    },
    onSuccess: () => invalidateQueueCaches(queryClient, projectId),
  });
}

export function useBulkResolve(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      ids?: number[]; severity?: string; qa_type?: string; file_ids?: number[];
    }) => {
      const { data } = await client.post<{ resolved: number }>(
        `/projects/${projectId}/qa-items/bulk-resolve`, body,
      );
      return data;
    },
    onSuccess: () => invalidateQueueCaches(queryClient, projectId),
  });
}
