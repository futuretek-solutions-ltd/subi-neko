import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import client from '../api/client';

export type OptionsMap = Record<string, string | null>;

export function useOptions() {
  return useQuery<OptionsMap>({
    queryKey: ['options'],
    queryFn: async () => {
      const { data } = await client.get<OptionsMap>('/options');
      return data;
    },
  });
}

export function useSaveOptions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (patch: OptionsMap) => {
      await client.patch('/options', patch);
    },
    onSuccess: (_data, patch) => {
      queryClient.setQueryData<OptionsMap>(['options'], (prev) =>
        prev ? { ...prev, ...patch } : patch
      );
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      notifications.show({
        color: 'red',
        title: 'Failed to save',
        message: msg,
      });
    },
  });
}
