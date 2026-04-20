import { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Modal,
  MultiSelect,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Select,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { FilmSlate, GitMerge, Microphone, Warning } from '@phosphor-icons/react';
import type { ProjectCharacterWithSpeakers } from '../types';
import {
  useProjectCharacters,
  useProjectSpeakers,
  useUpdateCharacter,
  useCompleteMapping,
} from '../hooks/useCharacterMapping';

interface CharacterDraft {
  gender: string | null;
  social_position: string | null;
  note: string | null;
  speaker_ids: number[];
  dirty: boolean;
}

type DraftMap = Record<number, CharacterDraft>;

const ROLE_ORDER: Record<string, number> = { MAIN: 0, SUPPORTING: 1, NARRATOR: 2 };
const ROLE_COLORS: Record<string, string> = {
  MAIN: 'pink', SUPPORTING: 'blue', NARRATOR: 'violet', BACKGROUND: 'gray',
};

function sortCharacters(chars: ProjectCharacterWithSpeakers[]) {
  return [...chars].sort((a, b) => {
    const ra = ROLE_ORDER[a.role?.toUpperCase() ?? ''] ?? 99;
    const rb = ROLE_ORDER[b.role?.toUpperCase() ?? ''] ?? 99;
    return ra !== rb ? ra - rb : a.name.localeCompare(b.name);
  });
}

function RoleBadge({ role }: { role: string | null }) {
  if (!role) return null;
  return (
    <Badge size="xs" color={ROLE_COLORS[role.toUpperCase()] ?? 'gray'} variant="light" style={{ flexShrink: 0 }}>
      {role}
    </Badge>
  );
}

function SpeakerCountBadge({ count }: { count: number }) {
  if (count === 0) return <Text size="xs" c="dimmed">(0)</Text>;
  if (count === 1) return <Text size="xs" c="green.6" fw={600}>(1)</Text>;
  return (
    <Tooltip label="Mapped to multiple characters" withArrow>
      <Group gap={2} style={{ cursor: 'default' }}>
        <Warning size={12} color="var(--mantine-color-yellow-5)" weight="fill" />
        <Text size="xs" c="yellow.5" fw={600}>({count})</Text>
      </Group>
    </Tooltip>
  );
}

interface CharacterRowProps {
  character: ProjectCharacterWithSpeakers;
  draft: CharacterDraft;
  speakerOptions: { value: string; label: string }[];
  onChange: (id: number, patch: Partial<Omit<CharacterDraft, 'dirty'>>) => void;
}

function CharacterRow({ character, draft, speakerOptions, onChange }: CharacterRowProps) {
  return (
    <Group
      gap="xs"
      px="sm"
      py={6}
      wrap="nowrap"
      align="center"
      style={{
        borderBottom: '1px solid var(--mantine-color-dark-5)',
        backgroundColor: draft.dirty ? 'var(--mantine-color-dark-6)' : undefined,
        minHeight: 44,
      }}
    >
      <Text size="sm" fw={600} truncate style={{ width: 220, flexShrink: 0 }}>
        {character.name}
      </Text>
      <Box style={{ width: 100, flexShrink: 0 }}>
        <RoleBadge role={character.role} />
      </Box>
      <Select
        size="xs"
        placeholder="Gender"
        style={{ width: 110, flexShrink: 0 }}
        clearable
        data={[
          { value: 'male', label: 'Male' },
          { value: 'female', label: 'Female' },
          { value: 'other', label: 'Other' },
          { value: 'unknown', label: 'Unknown' },
        ]}
        value={draft.gender}
        onChange={(v) => onChange(character.id, { gender: v })}
      />
      <TextInput
        size="xs"
        placeholder="Social position"
        style={{ width: 172, flexShrink: 0 }}
        value={draft.social_position ?? ''}
        onChange={(e) => onChange(character.id, { social_position: e.currentTarget.value || null })}
      />
      <MultiSelect
        size="xs"
        placeholder="Speakers..."
        style={{ width: 200, flexShrink: 0 }}
        data={speakerOptions}
        value={draft.speaker_ids.map(String)}
        onChange={(vals) => onChange(character.id, { speaker_ids: vals.map(Number) })}
        searchable
        hidePickedOptions
      />
      <TextInput
        size="xs"
        placeholder="Notes"
        style={{ width: 192, flexShrink: 0 }}
        value={draft.note ?? ''}
        onChange={(e) => onChange(character.id, { note: e.currentTarget.value || null })}
      />
      <Box style={{ width: 8, flexShrink: 0 }}>
        {draft.dirty && (
          <Tooltip label="Unsaved changes" withArrow>
            <Box style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: 'var(--mantine-color-yellow-5)' }} />
          </Tooltip>
        )}
      </Box>
    </Group>
  );
}

interface CharacterMappingDialogProps {
  projectId: number;
  opened: boolean;
  onClose: () => void;
}

export function CharacterMappingDialog({ projectId, opened, onClose }: CharacterMappingDialogProps) {
  const { data: rawCharacters = [], isLoading: charsLoading } = useProjectCharacters(opened ? projectId : null);
  const { data: speakers = [], isLoading: speakersLoading } = useProjectSpeakers(opened ? projectId : null);
  const characters = useMemo(() => sortCharacters(rawCharacters), [rawCharacters]);

  const updateCharacter = useUpdateCharacter();
  const completeMapping = useCompleteMapping();
  const [drafts, setDrafts] = useState<DraftMap>({});

  useEffect(() => {
    if (characters.length === 0) return;
    setDrafts((prev) => {
      const next: DraftMap = { ...prev };
      for (const char of characters) {
        if (!next[char.id] || !next[char.id].dirty) {
          next[char.id] = {
            gender: char.gender,
            social_position: char.social_position,
            note: char.note,
            speaker_ids: char.speaker_ids,
            dirty: false,
          };
        }
      }
      return next;
    });
  }, [characters]);

  function handleDraftChange(characterId: number, patch: Partial<Omit<CharacterDraft, 'dirty'>>) {
    setDrafts((prev) => ({ ...prev, [characterId]: { ...prev[characterId], ...patch, dirty: true } }));
  }

  const liveSpeakerCounts = useMemo<Record<number, number>>(() => {
    const counts: Record<number, number> = {};
    for (const draft of Object.values(drafts)) {
      for (const sid of draft.speaker_ids) counts[sid] = (counts[sid] ?? 0) + 1;
    }
    return counts;
  }, [drafts]);

  const speakerOptions = useMemo(
    () => speakers.map((s) => ({ value: String(s.id), label: s.name })),
    [speakers],
  );

  const dirtyCount = Object.values(drafts).filter((d) => d.dirty).length;
  const isLoading = charsLoading || speakersLoading;
  const isBusy = updateCharacter.isPending || completeMapping.isPending;
  const unmappedSpeakers = speakers.filter((s) => (liveSpeakerCounts[s.id] ?? 0) === 0);

  async function handleComplete() {
    const dirtyEntries = Object.entries(drafts).filter(([, d]) => d.dirty);
    if (dirtyEntries.length > 0) {
      try {
        await Promise.all(
          dirtyEntries.map(([idStr, draft]) =>
            updateCharacter.mutateAsync({
              projectId,
              characterId: Number(idStr),
              gender: draft.gender,
              social_position: draft.social_position,
              note: draft.note,
              speaker_ids: draft.speaker_ids,
            }),
          ),
        );
        setDrafts((prev) => {
          const next = { ...prev };
          for (const [idStr] of dirtyEntries) next[Number(idStr)] = { ...next[Number(idStr)], dirty: false };
          return next;
        });
      } catch {
        notifications.show({ color: 'red', title: 'Save failed', message: 'Could not save character changes. Please try again.' });
        return;
      }
    }
    try {
      await completeMapping.mutateAsync(projectId);
      notifications.show({ color: 'green', title: 'Mapping complete', message: 'Character mapping saved. Translation will begin shortly.' });
      onClose();
    } catch {
      notifications.show({ color: 'red', title: 'Complete mapping failed', message: 'Could not complete the mapping. Please try again.' });
    }
  }

  function handleClose() {
    if (dirtyCount > 0 && !isBusy) {
      if (!window.confirm(`You have ${dirtyCount} unsaved change(s). Discard and close?`)) return;
    }
    setDrafts({});
    onClose();
  }

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title={
        <Group gap="xs">
          <GitMerge size={18} />
          <Text fw={600}>Character Mapping</Text>
          {dirtyCount > 0 && <Badge size="sm" color="yellow" variant="light">{dirtyCount} unsaved</Badge>}
        </Group>
      }
      size="90%"
      styles={{
        body: { padding: 'var(--mantine-spacing-md)' },
        content: { display: 'flex', flexDirection: 'column' },
        inner: { padding: '2vh 2vw' },
      }}
    >
      {isLoading ? (
        <Center py="xl"><Loader size="sm" /></Center>
      ) : (
        <Group align="stretch" gap="md" wrap="nowrap" style={{ flex: 1, minHeight: 0 }}>

          {/* Left card: anime characters */}
          <Card withBorder radius="md" p={0} style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <Box px="md" py="sm" style={{ borderBottom: '1px solid var(--mantine-color-dark-4)', flexShrink: 0 }}>
              <Group gap="xs" mb={2}>
                <FilmSlate size={15} weight="duotone" color="var(--mantine-color-pink-4)" />
                <Text size="sm" fw={700}>Anime Characters</Text>
              </Group>
              <Text size="xs" c="dimmed">From the anime database — enrich each character and assign subtitle speakers</Text>
            </Box>

            <Group gap="xs" px="sm" py={5} wrap="nowrap" style={{ borderBottom: '1px solid var(--mantine-color-dark-5)', flexShrink: 0, backgroundColor: 'var(--mantine-color-dark-7)' }}>
              <Text size="xs" c="dimmed" style={{ width: 220, flexShrink: 0 }}>Name</Text>
              <Text size="xs" c="dimmed" style={{ width: 100, flexShrink: 0 }}>Role</Text>
              <Text size="xs" c="dimmed" style={{ width: 110, flexShrink: 0 }}>Gender</Text>
              <Text size="xs" c="dimmed" style={{ width: 172, flexShrink: 0 }}>Social position</Text>
              <Text size="xs" c="dimmed" style={{ width: 200, flexShrink: 0 }}>Subtitle speakers</Text>
              <Text size="xs" c="dimmed" style={{ width: 192, flexShrink: 0 }}>Notes</Text>
            </Group>

            <ScrollArea style={{ flex: 1 }}>
              {characters.length === 0 ? (
                <Text size="sm" c="dimmed" p="md">No characters found for this project.</Text>
              ) : (
                characters.map((char) =>
                  drafts[char.id] ? (
                    <CharacterRow key={char.id} character={char} draft={drafts[char.id]} speakerOptions={speakerOptions} onChange={handleDraftChange} />
                  ) : null,
                )
              )}
            </ScrollArea>
          </Card>

          {/* Right card: subtitle speakers */}
          <Card withBorder radius="md" p={0} style={{ width: 240, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <Box px="md" py="sm" style={{ borderBottom: '1px solid var(--mantine-color-dark-4)', flexShrink: 0 }}>
              <Group gap="xs" mb={2}>
                <Microphone size={15} weight="duotone" color="var(--mantine-color-cyan-4)" />
                <Text size="sm" fw={700}>Subtitle Speakers</Text>
              </Group>
              <Text size="xs" c="dimmed">Detected from subtitle files</Text>
            </Box>

            <ScrollArea style={{ flex: 1 }}>
              <Stack gap={0}>
                {speakers.length === 0 ? (
                  <Text size="sm" c="dimmed" p="sm">No speakers discovered.</Text>
                ) : (
                  speakers.map((speaker) => {
                    const count = liveSpeakerCounts[speaker.id] ?? 0;
                    return (
                      <Box key={speaker.id} px="sm" py={10} style={{ borderBottom: '1px solid var(--mantine-color-dark-5)', opacity: count === 0 ? 0.45 : 1 }}>
                        <Group gap="xs" wrap="nowrap" justify="space-between">
                          <Text size="sm" truncate c={count === 0 ? 'dimmed' : undefined} style={{ flex: 1, minWidth: 0 }}>
                            {speaker.name}
                          </Text>
                          <SpeakerCountBadge count={count} />
                        </Group>
                      </Box>
                    );
                  })
                )}
              </Stack>
            </ScrollArea>
          </Card>
        </Group>
      )}

      {/* Footer */}
      <Box pt="md" style={{ flexShrink: 0 }}>
        {unmappedSpeakers.length > 0 && (
          <Group gap="xs" mb="sm">
            <Warning size={14} color="var(--mantine-color-yellow-5)" weight="fill" />
            <Text size="xs" c="yellow.5">
              {unmappedSpeakers.length} speaker{unmappedSpeakers.length > 1 ? 's' : ''} not mapped:{' '}
              {unmappedSpeakers.map((s) => s.name).join(', ')}
            </Text>
          </Group>
        )}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={handleClose} disabled={isBusy}>Cancel</Button>
          <Button color="pink" leftSection={<GitMerge size={14} />} loading={isBusy} onClick={handleComplete}>
            {dirtyCount > 0 ? 'Save & Complete Mapping' : 'Complete Mapping'}
          </Button>
        </Group>
      </Box>
    </Modal>
  );
}
