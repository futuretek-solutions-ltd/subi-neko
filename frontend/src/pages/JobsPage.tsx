import { Badge, Card, Group, Progress, Stack, Text, Title } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import type { Job, JobStatus } from '../types';

const STATUS_COLORS: Record<JobStatus, string> = {
  queued: 'gray',
  running: 'blue',
  completed: 'green',
  failed: 'red',
  cancelled: 'orange',
};

function JobCard({ job }: { job: Job }) {
  return (
    <Card withBorder radius="md" p="sm">
      <Group justify="space-between" mb={4}>
        <Text fw={500} size="sm">{job.job_type}</Text>
        <Badge color={STATUS_COLORS[job.status]} size="sm">{job.status}</Badge>
      </Group>
      {job.status === 'running' && (
        <Progress value={(job.progress ?? 0) * 100} size="sm" mb={4} animated />
      )}
      {job.message && <Text size="xs" c="dimmed">{job.message}</Text>}
      {job.error_message && <Text size="xs" c="red">{job.error_message}</Text>}
      <Text size="xs" c="dimmed" mt={4}>ID: {job.id}</Text>
    </Card>
  );
}

export default function JobsPage() {
  const queryClient = useQueryClient();
  const jobs = (queryClient.getQueryData<Job[]>(['jobs']) ?? [])
    .slice()
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  return (
    <>
      <Title order={2} mb="md">Job Queue</Title>
      {jobs.length === 0 ? (
        <Text c="dimmed">No jobs yet.</Text>
      ) : (
        <Stack gap="xs">
          {jobs.map((job) => <JobCard key={job.id} job={job} />)}
        </Stack>
      )}
    </>
  );
}
