import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import type { Project, ProjectCharacterWithSpeakers, ProjectSpeakerWithCount } from '../types';

interface CharacterUpdatePayload {
  projectId: number;
  characterId: number;
  gender: string | null;
  social_position: string | null;
  note: string | null;
  speaker_ids: number[];
}

interface SpeakerUpdatePayload {
  projectId: number;
  speakerId: number;
  gender: string | null;
}

export function useProjectCharacters(projectId: number | null) {
  return useQuery<ProjectCharacterWithSpeakers[]>({
    queryKey: ['projects', projectId, 'characters'],
    queryFn: async () => {
      const { data } = await client.get<ProjectCharacterWithSpeakers[]>(
        `/projects/${projectId}/characters`,
      );
      return data;
    },
    enabled: projectId !== null,
  });
}

export function useProjectSpeakers(projectId: number | null) {
  return useQuery<ProjectSpeakerWithCount[]>({
    queryKey: ['projects', projectId, 'speakers'],
    queryFn: async () => {
      const { data } = await client.get<ProjectSpeakerWithCount[]>(
        `/projects/${projectId}/speakers`,
      );
      return data;
    },
    enabled: projectId !== null,
  });
}

export function useUpdateCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CharacterUpdatePayload) => {
      const { data } = await client.put<ProjectCharacterWithSpeakers>(
        `/projects/${payload.projectId}/characters/${payload.characterId}`,
        {
          gender: payload.gender,
          social_position: payload.social_position,
          note: payload.note,
          speaker_ids: payload.speaker_ids,
        },
      );
      return data;
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ['projects', variables.projectId, 'characters'],
      });
      queryClient.invalidateQueries({
        queryKey: ['projects', variables.projectId, 'speakers'],
      });
    },
  });
}

export function useUpdateSpeaker() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: SpeakerUpdatePayload) => {
      const { data } = await client.put<ProjectSpeakerWithCount>(
        `/projects/${payload.projectId}/speakers/${payload.speakerId}`,
        { gender: payload.gender },
      );
      return data;
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ['projects', variables.projectId, 'speakers'],
      });
    },
  });
}

export function useCompleteMapping() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (projectId: number) => {
      const { data } = await client.post<Project>(
        `/projects/${projectId}/complete-mapping`,
      );
      return data;
    },
    onSuccess: (_data, projectId) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'files'] });
    },
  });
}
