import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import type { Project, ProjectStats, SubtitleChunk, VideoFile } from '../types';

export function useProjects() {
  return useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: async () => {
      const { data } = await client.get<Project[]>('/projects');
      return data;
    },
  });
}

export function useProjectFiles(projectId: number | null) {
  return useQuery<VideoFile[]>({
    queryKey: ['projects', projectId, 'files'],
    queryFn: async () => {
      const { data } = await client.get<VideoFile[]>(`/projects/${projectId}/files`);
      return data;
    },
    enabled: projectId !== null,
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (projectId: number) => {
      await client.delete(`/projects/${projectId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['import', 'directories'] });
    },
  });
}

export function usePauseProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (projectId: number) => {
      const { data } = await client.post<Project>(`/projects/${projectId}/pause`);
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects'] }),
  });
}

export function useResumeProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (projectId: number) => {
      const { data } = await client.post<Project>(`/projects/${projectId}/resume`);
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects'] }),
  });
}

export function useFileChunks(projectId: number, fileId: number, enabled: boolean) {
  return useQuery<SubtitleChunk[]>({
    queryKey: ['projects', projectId, 'files', fileId, 'chunks'],
    queryFn: async () => {
      const { data } = await client.get<SubtitleChunk[]>(`/projects/${projectId}/files/${fileId}/chunks`);
      return data;
    },
    enabled,
    staleTime: 10_000,
  });
}

export function useProjectStats(projectId: number | null) {
  return useQuery<ProjectStats>({
    queryKey: ['projects', projectId, 'stats'],
    queryFn: async () => {
      const { data } = await client.get<ProjectStats>(`/projects/${projectId}/stats`);
      return data;
    },
    enabled: projectId !== null,
    staleTime: 30_000,
  });
}

export function useRetryChunk(projectId: number, fileId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (chunkIndex: number) => {
      const { data } = await client.post<SubtitleChunk>(
        `/projects/${projectId}/files/${fileId}/chunks/${chunkIndex}/retry`,
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'files', fileId, 'chunks'] });
      queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'files'] });
    },
  });
}

/** Invalidate project + file queries when a job completes — call inside useJobSocket. */
export function useInvalidateProjectsOnJob() {
  // No-op — invalidation is now handled inside useJobSocket directly.
}
