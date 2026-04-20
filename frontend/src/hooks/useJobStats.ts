import { useQuery } from '@tanstack/react-query';
import client from '../api/client';

export interface JobTypeStat {
  avg_secs: number;
  sample_count: number;
}

export function useJobStats(): Record<string, JobTypeStat> {
  const { data } = useQuery<Record<string, JobTypeStat>>({
    queryKey: ['job-stats'],
    queryFn: async () => {
      const { data } = await client.get<Record<string, JobTypeStat>>('/jobs/stats/durations');
      return data;
    },
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });
  return data ?? {};
}
