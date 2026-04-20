import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import type { SubtitleEventEditorRow } from '../types';

interface UpdateSubtitleEventPayload {
  projectId: number;
  fileId: number;
  eventId: number;
  translated_text: string | null;
}

interface RevertSubtitleEventPayload {
  projectId: number;
  fileId: number;
  eventId: number;
}

interface ResolveQaIssuePayload {
  projectId: number;
  fileId: number;
  issueId: number;
}

export function useSubtitleEvents(projectId: number, fileId: number | null, enabled: boolean) {
  return useQuery<SubtitleEventEditorRow[]>({
    queryKey: ['projects', projectId, 'files', fileId, 'subtitle-events'],
    queryFn: async () => {
      const { data } = await client.get<SubtitleEventEditorRow[]>(
        `/projects/${projectId}/files/${fileId}/subtitle-events`,
      );
      return data;
    },
    enabled: enabled && fileId !== null,
  });
}

export function useUpdateSubtitleEvent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: UpdateSubtitleEventPayload) => {
      const { data } = await client.put<SubtitleEventEditorRow>(
        `/projects/${payload.projectId}/files/${payload.fileId}/subtitle-events/${payload.eventId}`,
        {
          translated_text: payload.translated_text,
        },
      );
      return data;
    },
    onSuccess: (data, variables) => {
      queryClient.setQueryData<SubtitleEventEditorRow[]>(
        ['projects', variables.projectId, 'files', variables.fileId, 'subtitle-events'],
        (rows) => rows?.map((row) => (row.id === data.id ? data : row)),
      );
      queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId, 'files'] });
    },
  });
}

export function useRevertSubtitleEvent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: RevertSubtitleEventPayload) => {
      const { data } = await client.post<SubtitleEventEditorRow>(
        `/projects/${payload.projectId}/files/${payload.fileId}/subtitle-events/${payload.eventId}/revert`,
      );
      return data;
    },
    onSuccess: (data, variables) => {
      queryClient.setQueryData<SubtitleEventEditorRow[]>(
        ['projects', variables.projectId, 'files', variables.fileId, 'subtitle-events'],
        (rows) => rows?.map((row) => (row.id === data.id ? data : row)),
      );
      queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId, 'files'] });
    },
  });
}

export function useResolveQaIssue() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ResolveQaIssuePayload) => {
      const { data } = await client.post<SubtitleEventEditorRow>(
        `/projects/${payload.projectId}/files/${payload.fileId}/qa-issues/${payload.issueId}/resolve`,
      );
      return data;
    },
    onSuccess: (data, variables) => {
      queryClient.setQueryData<SubtitleEventEditorRow[]>(
        ['projects', variables.projectId, 'files', variables.fileId, 'subtitle-events'],
        (rows) => rows?.map((row) => (row.id === data.id ? data : row)),
      );
      queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId, 'files', variables.fileId, 'chunks'] });
      queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId, 'files'] });
      queryClient.invalidateQueries({ queryKey: ['projects', variables.projectId, 'stats'] });
    },
  });
}
