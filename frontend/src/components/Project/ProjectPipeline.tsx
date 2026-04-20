import { Box, Button, Group, Paper, Stack, Text } from '@mantine/core';
import { CheckCircle, GitMerge, Hourglass, Play, Stop, Warning } from '@phosphor-icons/react';
import type { Project, VideoFile } from '../../types';
import { useProjectCharacters } from '../../hooks/useCharacterMapping';
import { useProjectStats } from '../../hooks/useProjects';

// ─── State helpers ────────────────────────────────────────────────────────────

type StepState = 'waiting' | 'active' | 'needs_attention' | 'completed';

const STATUS_RANK: Record<string, number> = {
  new: 0,
  discovering: 1,
  waiting_for_mapping: 2,
  processing: 3,
  review_required: 4,
  completed: 5,
  failed: -1,
};

const STATE_COLOR: Record<StepState, string> = {
  waiting: 'var(--mantine-color-dark-3)',
  active: 'var(--mantine-color-blue-4)',
  needs_attention: 'var(--mantine-color-yellow-5)',
  completed: 'var(--mantine-color-green-5)',
};

const STATE_LABEL: Record<StepState, string> = {
  waiting: 'Waiting',
  active: 'Processing',
  needs_attention: 'Needs attention',
  completed: 'Completed',
};

function StepIcon({ state, size = 14 }: { state: StepState; size?: number }) {
  const color = STATE_COLOR[state];
  if (state === 'waiting') return <Hourglass size={size} color={color} />;
  if (state === 'active') return <Play size={size} color={color} weight="fill" />;
  if (state === 'needs_attention') return <Warning size={size} color={color} weight="fill" />;
  return <CheckCircle size={size} color={color} weight="fill" />;
}

// ─── Single step box ──────────────────────────────────────────────────────────

interface StepBoxProps {
  title: string;
  state: StepState;
  detail: React.ReactNode;
}

function StepBox({ title, state, detail }: StepBoxProps) {
  const color = STATE_COLOR[state];
  return (
    <Paper
      p="sm"
      withBorder
      style={{
        flex: 1,
        minWidth: 0,
        opacity: state === 'waiting' ? 0.5 : 1,
        borderColor: state === 'waiting' ? 'var(--mantine-color-dark-5)' : undefined,
      }}
    >
      <Stack gap={6}>
        <Text size="xs" fw={700} tt="uppercase" c="dimmed" style={{ letterSpacing: '0.05em' }}>
          {title}
        </Text>
        <Group gap={5} wrap="nowrap">
          <StepIcon state={state} />
          <Text size="sm" fw={500} c={color}>{STATE_LABEL[state]}</Text>
        </Group>
        <Box>{detail}</Box>
      </Stack>
    </Paper>
  );
}

// ─── Main pipeline component ──────────────────────────────────────────────────

interface ProjectPipelineProps {
  project: Project;
  files: VideoFile[];
  onMapCharacters: () => void;
}

export function ProjectPipeline({ project, files, onMapCharacters }: ProjectPipelineProps) {
  const rank = STATUS_RANK[project.status] ?? 0;

  const { data: characters = [] } = useProjectCharacters(project.id);
  const { data: stats } = useProjectStats(project.id);

  // Aggregate counts from files
  const filesTotal = files.length;
  const filesDiscovered = files.filter((f) => f.status !== 'new' && f.status !== 'discovering').length;
  const filesCompleted = files.filter((f) => f.status === 'completed').length;
  const chunksTotal = files.reduce((s, f) => s + (f.chunks_total ?? 0), 0);
  const chunksDone = files.reduce((s, f) => s + (f.chunks_done ?? 0), 0);

  const unmappedChars = characters.filter((c) => c.speaker_ids.length === 0).length;

  // ── Preparation ──────────────────────────────────────────────────────────
  const prepState: StepState =
    rank >= 2 ? 'completed' : rank >= 1 ? 'active' : 'waiting';

  const prepDetail = (
    <Text size="xs" c="dimmed">
      {filesDiscovered}/{filesTotal} files
    </Text>
  );

  // ── Characters ───────────────────────────────────────────────────────────
  const charState: StepState =
    rank >= 3 ? 'completed' : rank >= 2 ? 'needs_attention' : 'waiting';

  const charDetail =
    charState === 'needs_attention' ? (
      <Button
        size="xs"
        variant="light"
        color="pink"
        leftSection={<GitMerge size={12} />}
        onClick={onMapCharacters}
        mt={2}
      >
        Map {unmappedChars > 0 ? unmappedChars : characters.length} characters
      </Button>
    ) : charState === 'completed' ? (
      <Text size="xs" c="dimmed">{characters.length} characters mapped</Text>
    ) : (
      <Text size="xs" c="dimmed">—</Text>
    );

  // ── Translation ──────────────────────────────────────────────────────────
  const transState: StepState =
    rank >= 4 ? 'completed' : rank >= 3 ? 'active' : 'waiting';

  const transDetail = (
    <Text size="xs" c="dimmed">
      {chunksDone}/{chunksTotal} chunks
    </Text>
  );

  // ── Review ───────────────────────────────────────────────────────────────
  const reviewState: StepState =
    rank >= 5 ? 'completed' : rank >= 4 ? 'needs_attention' : 'waiting';

  const reviewDetail =
    reviewState !== 'waiting' ? (
      <Group gap={8} wrap="nowrap">
        {(stats?.qa_errors ?? 0) > 0 && (
          <Group gap={3} wrap="nowrap">
            <Stop size={12} color="var(--mantine-color-red-5)" weight="fill" />
            <Text size="xs" c="red">{stats!.qa_errors}</Text>
          </Group>
        )}
        {(stats?.qa_warnings ?? 0) > 0 && (
          <Group gap={3} wrap="nowrap">
            <Warning size={12} color="var(--mantine-color-yellow-5)" weight="fill" />
            <Text size="xs" c="yellow">{stats!.qa_warnings}</Text>
          </Group>
        )}
        {(stats?.qa_errors ?? 0) === 0 && (stats?.qa_warnings ?? 0) === 0 && (
          <Text size="xs" c="dimmed">No issues</Text>
        )}
      </Group>
    ) : (
      <Text size="xs" c="dimmed">—</Text>
    );

  // ── Output ───────────────────────────────────────────────────────────────
  const outputState: StepState =
    rank >= 5 ? 'completed' : rank >= 4 ? 'active' : 'waiting';

  const outputDetail = (
    <Text size="xs" c="dimmed">
      {filesCompleted}/{filesTotal} files
    </Text>
  );

  return (
    <Group gap="xs" align="stretch" wrap="nowrap">
      <StepBox title="Preparation" state={prepState} detail={prepDetail} />
      <StepBox title="Characters" state={charState} detail={charDetail} />
      <StepBox title="Translation" state={transState} detail={transDetail} />
      <StepBox title="Review" state={reviewState} detail={reviewDetail} />
      <StepBox title="Output" state={outputState} detail={outputDetail} />
    </Group>
  );
}
