import { Badge, Button, Group, Paper, Stack, Text, Tooltip } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  ArrowClockwiseIcon,
  CheckCircle,
  Hourglass,
  MinusCircle,
  ShieldCheck,
  SpinnerGap,
  UsersThree,
  Warning,
  XCircle,
} from '@phosphor-icons/react';
import type { ContextComponent, ContextComponentKey, Project } from '../../types';
import {
  useApproveContext,
  useContextStatus,
  useRetryContextComponent,
} from '../../hooks/useProjects';

const COMPONENT_LABELS: Record<ContextComponentKey, string> = {
  discovery: 'File discovery',
  speaker_aggregation: 'Speaker aggregation',
  character_mapping: 'Character mapping',
  style_bible: 'Style bible',
  glossary: 'Glossary',
  address_pairs: 'T–V pairs',
  character_styles: 'Character voices',
};

type RetryableComponent = 'speaker_aggregation' | 'character_mapping' | 'style_bible';
const RETRYABLE: Set<string> = new Set(['speaker_aggregation', 'character_mapping', 'style_bible']);

const CONFIDENCE_COLORS: Record<string, string> = {
  high: 'green',
  medium: 'yellow',
  low: 'red',
};

function ComponentIcon({ status }: { status: ContextComponent['status'] }) {
  switch (status) {
    case 'complete':
      return <CheckCircle size={14} color="var(--mantine-color-green-5)" weight="fill" />;
    case 'running':
      return <SpinnerGap size={14} color="var(--mantine-color-blue-4)" />;
    case 'failed':
      return <XCircle size={14} color="var(--mantine-color-red-5)" weight="fill" />;
    case 'skipped':
      return <MinusCircle size={14} color="var(--mantine-color-dark-3)" />;
    default:
      return <Hourglass size={14} color="var(--mantine-color-dark-3)" />;
  }
}

function componentSummary(component: ContextComponent): string | null {
  const d = component.detail as Record<string, number | null | undefined>;
  switch (component.key) {
    case 'discovery': {
      const missing = d.files_missing_subs ? ` · ${d.files_missing_subs} without subtitles` : '';
      return `${d.files_discovered ?? 0}/${d.files_total ?? 0} files${missing}`;
    }
    case 'speaker_aggregation':
      return component.status === 'complete'
        ? `${d.speakers_total ?? 0} speakers (${d.extras ?? 0} extras)`
        : null;
    case 'character_mapping':
      if (component.status === 'complete' && d.roster_empty) {
        return 'no character metadata from provider — mapping skipped';
      }
      return component.status === 'complete'
        ? `${d.mapped ?? 0} mapped · ${d.unmapped_non_extra ?? 0} unmapped · ${d.below_threshold ?? 0} low confidence`
        : null;
    case 'style_bible':
      if (component.status === 'skipped') return 'disabled in options';
      return component.status === 'complete' ? `version ${d.version}` : null;
    default:
      return null;
  }
}

export function ContextReviewPanel({
  project,
  onReviewCharacters,
}: {
  project: Project;
  onReviewCharacters: () => void;
}) {
  const { data: context } = useContextStatus(project.id);
  const approve = useApproveContext(project.id);
  const retry = useRetryContextComponent(project.id);

  if (!context || context.state === 'approved' || project.status === 'new') {
    return null;
  }

  const gating = context.components.filter((c) => c.status !== 'info');
  const info = context.components.filter((c) => c.status === 'info');
  const confidence = context.confidence;
  const attention = context.attention;

  function handleApprove() {
    if (
      confidence.overall === 'low'
      && !window.confirm(
        'Mapping confidence is LOW — unmapped or uncertain speakers can degrade '
        + 'gender agreement and voice consistency across the whole project. '
        + 'Approve the translation context anyway?',
      )
    ) {
      return;
    }
    approve.mutate(undefined, {
      onSuccess: () => notifications.show({
        color: 'green',
        message: 'Translation context approved — files are ready to translate.',
      }),
      onError: () => notifications.show({
        color: 'red',
        message: 'Approval failed — the context is not ready yet.',
      }),
    });
  }

  return (
    <Paper p="md" withBorder>
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Group gap="xs">
            <ShieldCheck size={18} />
            <Text fw={700}>Translation context</Text>
            <Badge
              size="sm"
              variant="light"
              color={
                context.state === 'failed' ? 'red'
                : context.state === 'ready_for_review' ? 'yellow'
                : 'blue'
              }
            >
              {context.state === 'ready_for_review' ? 'ready for review' : context.state}
            </Badge>
          </Group>
          <Group gap="xs">
            <Button
              size="xs"
              variant="default"
              leftSection={<UsersThree size={14} />}
              onClick={onReviewCharacters}
            >
              Review characters
            </Button>
            <Tooltip
              label="Translation cannot start until the context is approved"
              disabled={context.state === 'ready_for_review'}
              withArrow
            >
              <Button
                size="xs"
                color="green"
                leftSection={<CheckCircle size={14} />}
                disabled={context.state !== 'ready_for_review'}
                loading={approve.isPending}
                onClick={handleApprove}
              >
                Approve context
              </Button>
            </Tooltip>
          </Group>
        </Group>

        <Group gap="lg" align="flex-start" wrap="wrap">
          {/* Component checklist */}
          <Stack gap={6} style={{ minWidth: 280 }}>
            {gating.map((component) => (
              <Group key={component.key} gap={8} wrap="nowrap">
                <ComponentIcon status={component.status} />
                <Text size="sm" style={{ width: 150 }}>
                  {COMPONENT_LABELS[component.key]}
                </Text>
                {component.status === 'failed' ? (
                  <Group gap={6} wrap="nowrap">
                    <Tooltip label={component.error_message ?? 'Job failed'} withArrow multiline maw={360}>
                      <Text size="xs" c="red" truncate style={{ maxWidth: 180 }}>
                        {component.error_code ?? 'failed'}
                      </Text>
                    </Tooltip>
                    {RETRYABLE.has(component.key) && (
                      <Button
                        size="compact-xs"
                        variant="light"
                        color="red"
                        leftSection={<ArrowClockwiseIcon size={12} />}
                        loading={retry.isPending && retry.variables === component.key}
                        onClick={() => retry.mutate(component.key as RetryableComponent)}
                      >
                        Retry
                      </Button>
                    )}
                  </Group>
                ) : (
                  <Text size="xs" c="dimmed">
                    {componentSummary(component) ?? component.status}
                  </Text>
                )}
              </Group>
            ))}
            <Text size="xs" c="dimmed" mt={2}>
              {info
                .map((c) => `${COMPONENT_LABELS[c.key]}: ${Object.values(c.detail)[0] ?? 0}`)
                .join(' · ')}
            </Text>
          </Stack>

          {/* Confidence + attention */}
          <Stack gap={6} style={{ flex: 1, minWidth: 260 }}>
            <Group gap="xs">
              <Text size="sm" fw={600}>Mapping confidence</Text>
              <Badge size="sm" color={CONFIDENCE_COLORS[confidence.overall]} variant="light">
                {confidence.overall}
              </Badge>
              {confidence.line_weighted_coverage != null && (
                <Text size="xs" c="dimmed">
                  {Math.round(confidence.line_weighted_coverage * 100)}% of dialogue lines from
                  confidently mapped speakers
                </Text>
              )}
              {confidence.non_extra === 0 && (
                <Text size="xs" c="dimmed">no named speakers found</Text>
              )}
            </Group>
            {attention.length > 0 && (
              <Stack gap={2}>
                {attention.slice(0, 6).map((item) => (
                  <Group key={`${item.type}-${item.speaker_id ?? 'project'}`} gap={6} wrap="nowrap">
                    <Warning size={12} color="var(--mantine-color-yellow-5)" weight="fill" />
                    <Text size="xs">
                      {item.type === 'empty_character_roster'
                        ? (item.message
                          ?? 'Metadata provider returned no characters — genders unknown, mapping skipped.')
                        : item.type === 'unmapped_speaker'
                        ? `"${item.name}" is unmapped (${item.line_count} lines)`
                        : `"${item.name}" → ${item.character_name ?? '?'} at ${Math.round((item.confidence ?? 0) * 100)}% (${item.line_count} lines)`}
                    </Text>
                  </Group>
                ))}
                {attention.length > 6 && (
                  <Text size="xs" c="dimmed">…and {attention.length - 6} more in the Characters tab</Text>
                )}
              </Stack>
            )}
          </Stack>
        </Group>
      </Stack>
    </Paper>
  );
}
