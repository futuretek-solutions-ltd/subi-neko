import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import type { ProjectStats, SubtitleEventEditorRow, VideoFile } from '../types';

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
    onMutate: async (variables) => {
      const queryKey = ['projects', variables.projectId, 'files', variables.fileId, 'subtitle-events'];
      const rows = queryClient.getQueryData<SubtitleEventEditorRow[]>(queryKey);
      const issue = rows
        ?.flatMap((row) => row.issues)
        .find((item) => item.id === variables.issueId);
      return { issue };
    },
    onSuccess: (data, variables, context) => {
      queryClient.setQueryData<SubtitleEventEditorRow[]>(
        ['projects', variables.projectId, 'files', variables.fileId, 'subtitle-events'],
        (rows) => rows?.map((row) => (row.id === data.id ? data : row)),
      );
      const issue = context?.issue;
      if (!issue) return;
      const isError = ['critical', 'error', 'high'].includes(issue.severity.toLowerCase());
      queryClient.setQueryData<VideoFile[]>(
        ['projects', variables.projectId, 'files'],
        (files) => files?.map((file) => {
          if (file.id !== variables.fileId) return file;
          return {
            ...file,
            qa_issues: Math.max(0, file.qa_issues - 1),
            qa_errors: isError ? Math.max(0, file.qa_errors - 1) : file.qa_errors,
            qa_warnings: isError ? file.qa_warnings : Math.max(0, file.qa_warnings - 1),
          };
        }),
      );
      queryClient.setQueryData<ProjectStats>(
        ['projects', variables.projectId, 'stats'],
        (stats) => stats
          ? {
              qa_errors: isError ? Math.max(0, stats.qa_errors - 1) : stats.qa_errors,
              qa_warnings: isError ? stats.qa_warnings : Math.max(0, stats.qa_warnings - 1),
            }
          : stats,
      );
    },
  });
}
