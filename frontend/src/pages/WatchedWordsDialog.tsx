import { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Eye, Plus, Trash } from '@phosphor-icons/react';
import type { ProjectWatchedWord, WatchedWordType } from '../types';
import { useCreateProjectWatchedWord, useDeleteProjectWatchedWord, useProjectWatchedWords } from '../hooks/useProjects';

interface WatchedWordsDialogProps {
  projectId: number;
  opened: boolean;
  onClose: () => void;
}

function WatchedWordSection({
  title,
  wordType,
  words,
  adding,
  deletingId,
  onAdd,
  onDelete,
}: {
  title: string;
  wordType: WatchedWordType;
  words: ProjectWatchedWord[];
  adding: boolean;
  deletingId: number | null;
  onAdd: (word: string, wordType: WatchedWordType) => Promise<void>;
  onDelete: (wordId: number) => Promise<void>;
}) {
  const [word, setWord] = useState('');

  async function handleSubmit() {
    const trimmed = word.trim();
    if (!trimmed) return;
    await onAdd(trimmed, wordType);
    setWord('');
  }

  return (
    <Stack gap="xs">
      <Group justify="space-between" align="center">
        <Text size="sm" fw={700}>{title}</Text>
        <Badge size="xs" variant="light" color={wordType === 'original' ? 'blue' : 'green'}>
          {words.length}
        </Badge>
      </Group>
      <Group gap="xs" align="flex-end" wrap="nowrap">
        <TextInput
          value={word}
          onChange={(event) => setWord(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void handleSubmit();
            }
          }}
          placeholder="Add watched word"
          size="sm"
          style={{ flex: 1 }}
        />
        <Button
          size="sm"
          leftSection={<Plus size={14} />}
          loading={adding}
          disabled={!word.trim()}
          onClick={() => void handleSubmit()}
        >
          Add
        </Button>
      </Group>
      {words.length === 0 ? (
        <Text size="xs" c="dimmed">No watched words.</Text>
      ) : (
        <Stack gap={6}>
          {words.map((item) => (
            <Group
              key={item.id}
              gap="xs"
              justify="space-between"
              wrap="nowrap"
              px="xs"
              py={6}
              style={{
                border: '1px solid var(--mantine-color-dark-5)',
                borderRadius: 6,
                backgroundColor: 'var(--mantine-color-dark-7)',
              }}
            >
              <Text size="sm" truncate title={item.word}>{item.word}</Text>
              <Tooltip label="Remove watched word" withArrow>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  color="red"
                  aria-label={`Remove ${item.word}`}
                  loading={deletingId === item.id}
                  onClick={() => void onDelete(item.id)}
                >
                  <Trash size={14} />
                </ActionIcon>
              </Tooltip>
            </Group>
          ))}
        </Stack>
      )}
    </Stack>
  );
}

export function WatchedWordsDialog({ projectId, opened, onClose }: WatchedWordsDialogProps) {
  const { data: words = [], isLoading } = useProjectWatchedWords(projectId, opened);
  const createWord = useCreateProjectWatchedWord(projectId);
  const deleteWord = useDeleteProjectWatchedWord(projectId);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const originalWords = words.filter((word) => word.word_type === 'original');
  const translatedWords = words.filter((word) => word.word_type === 'translated');

  async function handleAdd(word: string, wordType: WatchedWordType) {
    try {
      await createWord.mutateAsync({ word, word_type: wordType });
    } catch {
      notifications.show({
        color: 'red',
        title: 'Could not add watched word',
        message: 'Check that the word is not already listed in this section.',
      });
    }
  }

  async function handleDelete(wordId: number) {
    setDeletingId(wordId);
    try {
      await deleteWord.mutateAsync(wordId);
    } catch {
      notifications.show({ color: 'red', title: 'Remove failed', message: 'Could not remove the watched word.' });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={(
        <Group gap="xs">
          <Eye size={18} />
          <Text fw={600}>Watched Words</Text>
        </Group>
      )}
      size="lg"
    >
      {isLoading ? (
        <Center py="xl"><Loader size="sm" /></Center>
      ) : (
        <Stack gap="lg">
          <WatchedWordSection
            title="Original words"
            wordType="original"
            words={originalWords}
            adding={createWord.isPending}
            deletingId={deletingId}
            onAdd={handleAdd}
            onDelete={handleDelete}
          />
          <WatchedWordSection
            title="Translated words"
            wordType="translated"
            words={translatedWords}
            adding={createWord.isPending}
            deletingId={deletingId}
            onAdd={handleAdd}
            onDelete={handleDelete}
          />
        </Stack>
      )}
    </Modal>
  );
}
