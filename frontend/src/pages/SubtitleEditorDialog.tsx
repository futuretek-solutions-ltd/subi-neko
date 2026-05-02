import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Center,
  Checkbox,
  Group,
  Loader,
  Modal,
  ScrollArea,
  Stack,
  Table,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { ArrowCounterClockwise, CheckCircle, NotePencil, WarningCircle } from '@phosphor-icons/react';
import type { QaIssue, SubtitleEventEditorRow, VideoFile } from '../types';
import { useResolveQaIssue, useRevertSubtitleEvent, useSubtitleEvents, useUpdateSubtitleEvent } from '../hooks/useSubtitleEditor';

interface SubtitleDraft {
  translated_text: string;
  dirty: boolean;
}

type DraftMap = Record<number, SubtitleDraft>;

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'red',
  error: 'red',
  high: 'red',
  warning: 'yellow',
  medium: 'yellow',
  info: 'blue',
  low: 'blue',
};

const SEVERITY_RANK: Record<string, number> = {
  critical: 0,
  error: 1,
  high: 1,
  warning: 2,
  medium: 2,
  info: 3,
  low: 3,
};

function sortIssues(issues: QaIssue[]) {
  return [...issues].sort((a, b) => {
    const ar = SEVERITY_RANK[a.severity.toLowerCase()] ?? 99;
    const br = SEVERITY_RANK[b.severity.toLowerCase()] ?? 99;
    if (ar !== br) return ar - br;
    return a.id - b.id;
  });
}

function IssueRow({
  issue,
  onResolve,
  resolving,
}: {
  issue: QaIssue;
  onResolve: (issueId: number) => void;
  resolving: boolean;
}) {
  const color = SEVERITY_COLORS[issue.severity.toLowerCase()] ?? 'gray';

  return (
    <Group
      gap="xs"
      wrap="nowrap"
      align="flex-start"
      px="xs"
      py={6}
      style={{
        border: '1px solid var(--mantine-color-dark-5)',
        borderRadius: 6,
        backgroundColor: 'var(--mantine-color-dark-7)',
      }}
    >
      <Badge size="xs" color={color} variant="light" style={{ width: 64, flexShrink: 0 }}>
        {issue.severity}
      </Badge>
      <Box style={{ flex: 1, minWidth: 0 }}>
        <Group gap={6} wrap="nowrap" mb={2}>
          <Text size="xs" fw={600} truncate>
            {issue.qa_type.replace(/_/g, ' ')}
          </Text>
        </Group>
        <Text size="xs" c="dimmed" style={{ whiteSpace: 'normal' }}>
          {issue.message}
        </Text>
      </Box>
      <Tooltip label="Resolve issue" withArrow>
        <Button
          size="compact-xs"
          variant="subtle"
          color="green"
          loading={resolving}
          leftSection={<CheckCircle size={13} />}
          onClick={() => onResolve(issue.id)}
          style={{ flexShrink: 0 }}
        >
          Solve
        </Button>
      </Tooltip>
    </Group>
  );
}

const SubtitleRow = memo(function SubtitleRow({
  row,
  draft,
  resolvingIssueId,
  saving,
  reverting,
  onChange,
  onBlurSave,
  onRevert,
  onResolve,
}: {
  row: SubtitleEventEditorRow;
  draft: SubtitleDraft;
  resolvingIssueId: number | null;
  saving: boolean;
  reverting: boolean;
  onChange: (eventId: number, translatedText: string) => void;
  onBlurSave: (row: SubtitleEventEditorRow) => void;
  onRevert: (row: SubtitleEventEditorRow) => void;
  onResolve: (issueId: number) => void;
}) {
  const issues = sortIssues(row.issues);
  const canRevert = row.original_ai_translated_text !== null
    && draft.translated_text !== row.original_ai_translated_text;

  return (
    <Table.Tr style={{ backgroundColor: draft.dirty ? 'var(--mantine-color-dark-6)' : undefined }}>
      <Table.Td style={{ width: 86, verticalAlign: 'top' }}>
        <Group gap={6} wrap="nowrap">
          <Text size="sm" fw={600}>{row.line_index + 1}</Text>
          {draft.dirty && (
            <Tooltip label="Unsaved changes" withArrow>
              <Box style={{ width: 7, height: 7, borderRadius: '50%', backgroundColor: 'var(--mantine-color-orange-5)', flexShrink: 0 }} />
            </Tooltip>
          )}
        </Group>
        {row.speaker_name && (
          <Stack gap={2} mt={8}>
            <Text size="xs" c="dimmed" truncate title={row.speaker_name}>
              {row.speaker_name}
            </Text>
            {row.character_name && (
              <Group gap={4} wrap="nowrap">
                <Badge size="xs" variant="light" color="blue" style={{ maxWidth: 82 }}>
                  <Text size="xs" truncate>{row.character_name}</Text>
                </Badge>
                {row.character_gender && (
                  <Badge size="xs" variant="outline" color="gray">
                    {row.character_gender}
                  </Badge>
                )}
              </Group>
            )}
          </Stack>
        )}
      </Table.Td>
      <Table.Td style={{ width: '30%', verticalAlign: 'top' }}>
        <Textarea
          autosize
          minRows={2}
          maxRows={8}
          value={row.source_text}
          readOnly
          styles={{ input: { fontSize: 13, lineHeight: 1.35 } }}
        />
      </Table.Td>
      <Table.Td style={{ width: '30%', verticalAlign: 'top' }}>
        <Group gap={6} align="flex-start" wrap="nowrap">
          <Textarea
            autosize
            minRows={2}
            maxRows={8}
            value={draft.translated_text}
            onChange={(e) => onChange(row.id, e.currentTarget.value)}
            onBlur={() => onBlurSave(row)}
            disabled={saving || reverting}
            styles={{ root: { flex: 1 }, input: { fontSize: 13, lineHeight: 1.35 } }}
          />
          <Tooltip label="Revert to AI translation" withArrow>
            <ActionIcon
              size="sm"
              variant="subtle"
              color="gray"
              aria-label="Revert to AI translation"
              disabled={!canRevert || saving || reverting}
              loading={reverting}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => onRevert(row)}
            >
              <ArrowCounterClockwise size={15} />
            </ActionIcon>
          </Tooltip>
        </Group>
        {saving && <Text size="xs" c="dimmed" mt={4}>Saving…</Text>}
      </Table.Td>
      <Table.Td style={{ verticalAlign: 'top' }}>
        {issues.length === 0 ? (
          <Text size="xs" c="dimmed">No issues</Text>
        ) : (
          <Stack gap={6}>
            {issues.map((issue) => (
              <IssueRow
                key={issue.id}
                issue={issue}
                resolving={resolvingIssueId === issue.id}
                onResolve={onResolve}
              />
            ))}
          </Stack>
        )}
      </Table.Td>
    </Table.Tr>
  );
}, (prev, next) => (
  prev.row === next.row
  && prev.draft === next.draft
  && prev.saving === next.saving
  && prev.reverting === next.reverting
  && !prev.row.issues.some((issue) => issue.id === prev.resolvingIssueId || issue.id === next.resolvingIssueId)
));

interface SubtitleEditorDialogProps {
  projectId: number;
  file: VideoFile | null;
  opened: boolean;
  onClose: () => void;
}

export function SubtitleEditorDialog({ projectId, file, opened, onClose }: SubtitleEditorDialogProps) {
  const fileId = file?.id ?? null;
  const { data: rows = [], isLoading } = useSubtitleEvents(projectId, fileId, opened);
  const updateSubtitleEvent = useUpdateSubtitleEvent();
  const revertSubtitleEvent = useRevertSubtitleEvent();
  const resolveQaIssue = useResolveQaIssue();
  const [drafts, setDrafts] = useState<DraftMap>({});
  const [resolvingIssueId, setResolvingIssueId] = useState<number | null>(null);
  const [savingEventId, setSavingEventId] = useState<number | null>(null);
  const [revertingEventId, setRevertingEventId] = useState<number | null>(null);
  const [issuesOnly, setIssuesOnly] = useState(false);

  useEffect(() => {
    if (!opened) return;
    setDrafts((prev) => {
      const next: DraftMap = { ...prev };
      for (const row of rows) {
        if (!next[row.id] || !next[row.id].dirty) {
          next[row.id] = {
            translated_text: row.translated_text ?? '',
            dirty: false,
          };
        }
      }
      return next;
    });
  }, [opened, rows]);

  const dirtyCount = useMemo(
    () => Object.values(drafts).filter((draft) => draft.dirty).length,
    [drafts],
  );
  const issueSummary = useMemo(() => {
    const counts = new Map<string, { qa_type: string; severity: string; count: number }>();
    for (const row of rows) {
      for (const issue of row.issues) {
        const key = `${issue.severity}:${issue.qa_type}`;
        const existing = counts.get(key);
        if (existing) {
          existing.count += 1;
        } else {
          counts.set(key, { qa_type: issue.qa_type, severity: issue.severity, count: 1 });
        }
      }
    }
    return [...counts.values()].sort((a, b) => {
      const ar = SEVERITY_RANK[a.severity.toLowerCase()] ?? 99;
      const br = SEVERITY_RANK[b.severity.toLowerCase()] ?? 99;
      if (ar !== br) return ar - br;
      return b.count - a.count;
    });
  }, [rows]);
  const issueCount = issueSummary.reduce((sum, item) => sum + item.count, 0);
  const visibleRows = useMemo(
    () => (issuesOnly ? rows.filter((row) => row.issues.length > 0) : rows),
    [issuesOnly, rows],
  );
  const isBusy = updateSubtitleEvent.isPending || revertSubtitleEvent.isPending || resolveQaIssue.isPending;

  const handleDraftChange = useCallback((eventId: number, translatedText: string) => {
    setDrafts((prev) => ({
      ...prev,
      [eventId]: {
        ...prev[eventId],
        translated_text: translatedText,
        dirty: true,
      },
    }));
  }, []);

  const handleBlurSave = useCallback(async (row: SubtitleEventEditorRow) => {
    if (!file) return;
    const draft = drafts[row.id];
    if (!draft || !draft.dirty) return;
    if (draft.translated_text === (row.translated_text ?? '')) {
      setDrafts((prev) => ({
        ...prev,
        [row.id]: { ...draft, dirty: false },
      }));
      return;
    }

    setSavingEventId(row.id);
    try {
      const saved = await updateSubtitleEvent.mutateAsync({
        projectId,
        fileId: file.id,
        eventId: row.id,
        translated_text: draft.translated_text || null,
      });
      setDrafts((prev) => {
        const current = prev[row.id];
        if (!current) return prev;
        return {
          ...prev,
          [row.id]: {
            translated_text: saved.translated_text ?? '',
            dirty: false,
          },
        };
      });
    } catch {
      notifications.show({ color: 'red', title: 'Save failed', message: 'Could not save subtitle edits.' });
    } finally {
      setSavingEventId(null);
    }
  }, [drafts, file, projectId, updateSubtitleEvent]);

  const handleRevert = useCallback(async (row: SubtitleEventEditorRow) => {
    if (!file) return;
    setRevertingEventId(row.id);
    try {
      const reverted = await revertSubtitleEvent.mutateAsync({ projectId, fileId: file.id, eventId: row.id });
      setDrafts((prev) => ({
        ...prev,
        [row.id]: {
          translated_text: reverted.translated_text ?? '',
          dirty: false,
        },
      }));
    } catch {
      notifications.show({ color: 'red', title: 'Revert failed', message: 'Could not restore the original AI translation.' });
    } finally {
      setRevertingEventId(null);
    }
  }, [file, projectId, revertSubtitleEvent]);

  const handleResolve = useCallback(async (issueId: number) => {
    if (!file) return;
    setResolvingIssueId(issueId);
    try {
      await resolveQaIssue.mutateAsync({ projectId, fileId: file.id, issueId });
    } catch {
      notifications.show({ color: 'red', title: 'Resolve failed', message: 'Could not resolve the QA issue.' });
    } finally {
      setResolvingIssueId(null);
    }
  }, [file, projectId, resolveQaIssue]);

  function handleClose() {
    setDrafts({});
    setIssuesOnly(false);
    onClose();
  }

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title={
        <Group gap="xs">
          <NotePencil size={18} />
          <Text fw={600}>Subtitle Editor</Text>
          {file && <Text size="sm" c="dimmed">{file.filename}</Text>}
          {dirtyCount > 0 && <Badge size="sm" color="orange" variant="light">{dirtyCount} unsaved</Badge>}
          {issueCount > 0 && <Badge size="sm" color="red" variant="light">{issueCount} issues</Badge>}
        </Group>
      }
      size="95%"
      styles={{
        body: { padding: 'var(--mantine-spacing-md)' },
        content: { display: 'flex', flexDirection: 'column' },
        inner: { padding: '2vh 2vw' },
      }}
    >
      {isLoading ? (
        <Center py="xl"><Loader size="sm" /></Center>
      ) : rows.length === 0 ? (
        <Center py="xl">
          <Group gap="xs">
            <WarningCircle size={16} />
            <Text size="sm" c="dimmed">No subtitle events found for this file.</Text>
          </Group>
        </Center>
      ) : (
        <Stack gap="sm">
          <Group justify="space-between" gap="sm">
            <Group gap="xs" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
              <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                Showing {visibleRows.length} of {rows.length} events
              </Text>
              {issueSummary.length > 0 && (
                <Group gap={4} wrap="nowrap" style={{ minWidth: 0, overflow: 'hidden' }}>
                  {issueSummary.map((item) => (
                    <Badge
                      key={`${item.severity}:${item.qa_type}`}
                      size="xs"
                      color={SEVERITY_COLORS[item.severity.toLowerCase()] ?? 'gray'}
                      variant="light"
                      title={`${item.count} ${item.qa_type.replace(/_/g, ' ')}`}
                      style={{ flexShrink: 0 }}
                    >
                      {item.qa_type.replace(/_/g, ' ')}: {item.count}
                    </Badge>
                  ))}
                </Group>
              )}
            </Group>
            <Checkbox
              size="xs"
              checked={issuesOnly}
              label="Show only events with issues"
              onChange={(e) => setIssuesOnly(e.currentTarget.checked)}
            />
          </Group>

          {visibleRows.length === 0 ? (
            <Center h="70vh">
              <Text size="sm" c="dimmed">No events with unresolved issues.</Text>
            </Center>
          ) : (
            <ScrollArea h="70vh" type="auto">
              <Table striped highlightOnHover withColumnBorders style={{ tableLayout: 'fixed' }}>
                <Table.Thead style={{ position: 'sticky', top: 0, zIndex: 1, backgroundColor: 'var(--mantine-color-dark-7)' }}>
                  <Table.Tr>
                    <Table.Th style={{ width: 86 }}>Event</Table.Th>
                    <Table.Th style={{ width: '30%' }}>English text</Table.Th>
                    <Table.Th style={{ width: '30%' }}>Translation</Table.Th>
                    <Table.Th>Issues</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {visibleRows.map((row) => (
                    drafts[row.id] ? (
                      <SubtitleRow
                        key={row.id}
                        row={row}
                        draft={drafts[row.id]}
                        resolvingIssueId={resolvingIssueId}
                        saving={savingEventId === row.id}
                        reverting={revertingEventId === row.id}
                        onChange={handleDraftChange}
                        onBlurSave={handleBlurSave}
                        onRevert={handleRevert}
                        onResolve={handleResolve}
                      />
                    ) : null
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          )}
        </Stack>
      )}

      {isBusy && (
        <Box pt="md" style={{ flexShrink: 0 }}>
          <Text size="xs" c="dimmed">Saving changes…</Text>
        </Box>
      )}
    </Modal>
  );
}
