import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Center,
  Group,
  Kbd,
  Loader,
  Modal,
  ScrollArea,
  Stack,
  Text,
  Textarea,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { ListChecks } from '@phosphor-icons/react';
import type { ReviewQueueItem } from '../types';
import {
  useBulkResolve,
  useResolveQueueItem,
  useReviewQueue,
  useSaveQueueTranslation,
} from '../hooks/useReviewQueue';

const SEVERITY_COLORS: Record<string, string> = {
  blocker: 'red',
  warning: 'yellow',
  info: 'blue',
};

function QueueRow({
  item,
  active,
  projectId,
  onActivate,
  onResolved,
}: {
  item: ReviewQueueItem;
  active: boolean;
  projectId: number;
  onActivate: () => void;
  onResolved: () => void;
}) {
  const resolve = useResolveQueueItem(projectId);
  const save = useSaveQueueTranslation(projectId);
  const [draft, setDraft] = useState(item.translated_text ?? '');
  const [syncedText, setSyncedText] = useState(item.translated_text);
  const rowRef = useRef<HTMLDivElement | null>(null);
  const textRef = useRef<HTMLTextAreaElement | null>(null);

  // Render-phase sync: refresh the draft when the server text changes.
  if (item.translated_text !== syncedText) {
    setSyncedText(item.translated_text);
    setDraft(item.translated_text ?? '');
  }

  useEffect(() => {
    if (active) rowRef.current?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  async function handleResolve() {
    try {
      await resolve.mutateAsync({ fileId: item.file_id, issueId: item.id });
      onResolved();
    } catch {
      notifications.show({ color: 'red', message: 'Could not resolve the issue.' });
    }
  }

  async function handleSaveAndResolve() {
    try {
      if (item.event_id !== null && draft !== (item.translated_text ?? '')) {
        await save.mutateAsync({
          fileId: item.file_id,
          eventId: item.event_id,
          translatedText: draft,
        });
      }
      await handleResolve();
    } catch {
      notifications.show({ color: 'red', message: 'Could not save the translation.' });
    }
  }

  return (
    <Stack
      ref={rowRef}
      gap={6}
      p="sm"
      onClick={onActivate}
      style={{
        border: `1px solid var(--mantine-color-${active ? 'blue' : 'dark'}-${active ? 7 : 5})`,
        outline: active ? '1px solid var(--mantine-color-blue-5)' : undefined,
        borderRadius: 8,
        cursor: 'pointer',
        backgroundColor: active ? 'var(--mantine-color-dark-6)' : undefined,
      }}
    >
      <Group gap="xs" wrap="nowrap">
        <Badge size="xs" variant="filled" color={SEVERITY_COLORS[item.severity] ?? 'gray'}>
          {item.severity}
        </Badge>
        <Badge size="xs" variant="light" color="gray">{item.qa_type.replace(/_/g, ' ')}</Badge>
        {item.translation_confidence !== null && (
          <Badge size="xs" variant="light" color="grape">
            conf {Math.round(item.translation_confidence * 100)}%
          </Badge>
        )}
        <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>
          {item.filename}{item.line_index !== null ? ` · line ${item.line_index + 1}` : ''}
          {item.speaker ? ` · ${item.speaker}` : ''}
        </Text>
      </Group>
      <Text size="xs" c="dimmed">{item.message}</Text>
      {item.source_text !== null && (
        <Text size="sm" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>
          {item.source_text}
        </Text>
      )}
      {item.event_id !== null ? (
        <Textarea
          ref={textRef}
          size="sm"
          autosize
          minRows={1}
          maxRows={4}
          value={draft}
          onChange={(e) => setDraft(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              void handleSaveAndResolve();
            }
          }}
        />
      ) : null}
      <Group gap="xs" justify="flex-end">
        <Button
          size="compact-xs"
          variant="subtle"
          loading={resolve.isPending}
          onClick={(e) => { e.stopPropagation(); void handleResolve(); }}
        >
          Resolve
        </Button>
        {item.event_id !== null && (
          <Button
            size="compact-xs"
            variant="light"
            color="green"
            loading={save.isPending}
            onClick={(e) => { e.stopPropagation(); void handleSaveAndResolve(); }}
          >
            Save & resolve
          </Button>
        )}
      </Group>
    </Stack>
  );
}

interface ReviewQueueDialogProps {
  projectId: number;
  opened: boolean;
  onClose: () => void;
}

export function ReviewQueueDialog({ projectId, opened, onClose }: ReviewQueueDialogProps) {
  const { data, isLoading } = useReviewQueue(projectId, opened);
  const bulkResolve = useBulkResolve(projectId);
  const [activeIndex, setActiveIndex] = useState(0);

  const items = useMemo(() => data?.items ?? [], [data]);

  // Clamp at usage time — the list shrinks as items get resolved.
  const clampedIndex = Math.min(activeIndex, Math.max(0, items.length - 1));

  // j/k keyboard navigation on the dialog body (not while typing).
  function handleKeyDown(e: React.KeyboardEvent) {
    const tag = (e.target as HTMLElement).tagName;
    if (tag === 'TEXTAREA' || tag === 'INPUT') return;
    if (e.key === 'j') setActiveIndex(Math.min(clampedIndex + 1, items.length - 1));
    if (e.key === 'k') setActiveIndex(Math.max(clampedIndex - 1, 0));
  }

  const warningCount = items.filter((i) => i.severity !== 'blocker').length;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <Group gap="xs">
          <ListChecks size={18} />
          <Text fw={700}>Review queue</Text>
          {data && <Badge size="sm" variant="light">{data.total} unresolved</Badge>}
        </Group>
      }
      size="60rem"
    >
      <Stack gap="sm" onKeyDown={handleKeyDown}>
        <Group justify="space-between">
          <Text size="xs" c="dimmed">
            Most severe and least confident first. <Kbd size="xs">j</Kbd>/<Kbd size="xs">k</Kbd> to move,{' '}
            <Kbd size="xs">Ctrl</Kbd>+<Kbd size="xs">Enter</Kbd> in the text box to save & resolve.
          </Text>
          {warningCount > 0 && (
            <Button
              size="compact-xs"
              variant="subtle"
              color="yellow"
              loading={bulkResolve.isPending}
              onClick={() => {
                if (window.confirm(`Resolve all ${warningCount} non-blocker issue(s) in this project?`)) {
                  void bulkResolve.mutateAsync({ severity: 'warning' })
                    .then(() => bulkResolve.mutateAsync({ severity: 'info' }));
                }
              }}
            >
              Resolve all warnings
            </Button>
          )}
        </Group>
        {isLoading ? (
          <Center py="xl"><Loader size="sm" /></Center>
        ) : items.length === 0 ? (
          <Center py="xl">
            <Text size="sm" c="dimmed">Nothing to review — all clear.</Text>
          </Center>
        ) : (
          <ScrollArea.Autosize mah="65vh">
            <Stack gap="xs">
              {items.map((item, index) => (
                <QueueRow
                  key={item.id}
                  item={item}
                  active={index === clampedIndex}
                  projectId={projectId}
                  onActivate={() => setActiveIndex(index)}
                  onResolved={() => setActiveIndex(Math.max(0, Math.min(clampedIndex, items.length - 2)))}
                />
              ))}
            </Stack>
          </ScrollArea.Autosize>
        )}
      </Stack>
    </Modal>
  );
}
