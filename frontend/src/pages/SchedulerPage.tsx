import { Badge, Card, Group, Stack, Text, Title } from '@mantine/core';
import type { ScheduledTask } from '../types';

function ScheduleCard({ task }: { task: ScheduledTask }) {
  return (
    <Card withBorder radius="md" p="sm">
      <Group justify="space-between" mb={4}>
        <Text fw={500} size="sm">{task.name}</Text>
        <Badge color={task.enabled ? 'green' : 'gray'} size="sm">
          {task.enabled ? 'enabled' : 'disabled'}
        </Badge>
      </Group>
      <Text size="xs" c="dimmed">Job type: {task.job_type}</Text>
      <Text size="xs" c="dimmed">
        Trigger: {task.trigger_type} — {JSON.stringify(task.trigger_config)}
      </Text>
      {task.last_triggered_at && (
        <Text size="xs" c="dimmed">Last run: {new Date(task.last_triggered_at).toLocaleString()}</Text>
      )}
    </Card>
  );
}

export default function SchedulerPage() {
  // Populated via React Query once the schedules API route is added
  const tasks: ScheduledTask[] = [];

  return (
    <>
      <Title order={2} mb="md">Scheduler</Title>
      {tasks.length === 0 ? (
        <Text c="dimmed">No scheduled tasks configured.</Text>
      ) : (
        <Stack gap="xs">
          {tasks.map((t) => <ScheduleCard key={t.id} task={t} />)}
        </Stack>
      )}
    </>
  );
}
