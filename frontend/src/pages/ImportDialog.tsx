import { useState, useEffect, useRef } from 'react';
import {
  Badge,
  Box,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Modal,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  UnstyledButton,
} from '@mantine/core';
import { MagnifyingGlass } from '@phosphor-icons/react';
import { useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import type { SearchResult } from '../types';
import {
  useImportDirectories,
  useImportProject,
  useMetadataSearch,
  type ImportRequest,
} from '../hooks/useImport';

function normalizeDirName(name: string): string {
  return name.replace(/[-_.]/g, ' ').replace(/\s+/g, ' ').trim();
}

interface ImportDialogProps {
  opened: boolean;
  onClose: () => void;
}

export function ImportDialog({ opened, onClose }: ImportDialogProps) {
  const queryClient = useQueryClient();

  const [selectedDir, setSelectedDir] = useState<string | null>(null);
  const [provider, setProvider] = useState<'anilist' | 'anidb'>('anilist');
  const [searchQuery, setSearchQuery] = useState('');
  const [committedQuery, setCommittedQuery] = useState('');
  const [selectedResult, setSelectedResult] = useState<SearchResult | null>(null);
  const autoSearchedFor = useRef<string | null>(null);

  const { data: directories = [], isLoading: dirsLoading } = useImportDirectories(opened);
  const { data: searchResults = [], isLoading: searching } = useMetadataSearch(
    provider,
    committedQuery,
  );
  const importMutation = useImportProject();

  // Auto-search once when a directory is selected
  useEffect(() => {
    if (!selectedDir || autoSearchedFor.current === selectedDir) return;
    autoSearchedFor.current = selectedDir;
    const q = normalizeDirName(selectedDir);
    setSearchQuery(q);
    setCommittedQuery(q);
    setSelectedResult(null);
  }, [selectedDir]);

  // Clear selected result when provider changes
  useEffect(() => {
    setSelectedResult(null);
  }, [provider, committedQuery]);

  function handleSearch() {
    const q = searchQuery.trim();
    if (q) {
      setCommittedQuery(q);
      setSelectedResult(null);
    }
  }

  function handleSelectDir(name: string) {
    if (name !== selectedDir) {
      autoSearchedFor.current = null;
    }
    setSelectedDir(name);
  }

  function handleClose() {
    setSelectedDir(null);
    setSearchQuery('');
    setCommittedQuery('');
    setSelectedResult(null);
    autoSearchedFor.current = null;
    onClose();
  }

  async function handleImport() {
    if (!selectedDir || !selectedResult) return;
    const req: ImportRequest = {
      directory_name: selectedDir,
      provider,
      provider_id: selectedResult.provider_id,
      anime_title: selectedResult.title,
      anime_title_native: selectedResult.title_native,
      anime_year: selectedResult.year,
    };
    try {
      await importMutation.mutateAsync(req);
      await queryClient.invalidateQueries({ queryKey: ['projects'] });
      await queryClient.invalidateQueries({ queryKey: ['import', 'directories'] });
      handleClose();
    } catch {
      notifications.show({
        color: 'red',
        title: 'Import failed',
        message: 'Could not create the project. Please try again.',
      });
    }
  }

  const canImport = !!selectedDir && !!selectedResult && !importMutation.isPending;

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title="Import Project"
      size="xl"
      styles={{ body: { padding: 0 } }}
    >
      <Group align="stretch" gap={0} style={{ minHeight: 420 }}>
        {/* Left: unimported directories */}
        <Box
          style={{
            width: '42%',
            borderRight: '1px solid var(--mantine-color-dark-4)',
            flexShrink: 0,
          }}
        >
          <Box p="md">
            <Text size="xs" fw={600} mb="sm" c="dimmed" tt="uppercase" style={{ letterSpacing: '0.05em' }}>
              Unimported Directories
            </Text>
            {dirsLoading ? (
              <Center py="xl">
                <Loader size="sm" />
              </Center>
            ) : directories.length === 0 ? (
              <Text size="sm" c="dimmed">
                No new directories found in import root.
              </Text>
            ) : (
              <ScrollArea h={340} offsetScrollbars>
                <Stack gap="xs">
                  {directories.map((dir) => (
                    <UnstyledButton
                      key={dir.name}
                      w="100%"
                      onClick={() => handleSelectDir(dir.name)}
                    >
                      <Card
                        p="xs"
                        radius="sm"
                        withBorder
                        style={{
                          borderColor:
                            selectedDir === dir.name
                              ? 'var(--mantine-color-pink-6)'
                              : undefined,
                          backgroundColor:
                            selectedDir === dir.name
                              ? 'var(--mantine-color-dark-5)'
                              : undefined,
                          cursor: 'pointer',
                        }}
                      >
                        <Text size="sm" fw={500} truncate>
                          {dir.name}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {dir.file_count} {dir.file_count === 1 ? 'file' : 'files'}
                        </Text>
                      </Card>
                    </UnstyledButton>
                  ))}
                </Stack>
              </ScrollArea>
            )}
          </Box>
        </Box>

        {/* Right: anime search */}
        <Box style={{ flex: 1, minWidth: 0 }}>
          <Box p="md">
            <Text size="xs" fw={600} mb="sm" c="dimmed" tt="uppercase" style={{ letterSpacing: '0.05em' }}>
              Anime Match
            </Text>
            <Stack gap="sm">
              <SegmentedControl
                size="xs"
                value={provider}
                onChange={(v) => setProvider(v as 'anilist' | 'anidb')}
                data={[
                  { label: 'AniList', value: 'anilist' },
                  { label: 'AniDB', value: 'anidb' },
                ]}
              />

              <Group gap="xs" align="flex-end">
                <TextInput
                  style={{ flex: 1 }}
                  placeholder="Search anime…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.currentTarget.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                />
                <Button
                  variant="default"
                  size="sm"
                  leftSection={<MagnifyingGlass size={14} />}
                  onClick={handleSearch}
                  loading={searching}
                >
                  Search
                </Button>
              </Group>

              {committedQuery && (
                <ScrollArea h={280} offsetScrollbars>
                  {searching ? (
                    <Center py="md">
                      <Loader size="sm" />
                    </Center>
                  ) : searchResults.length === 0 ? (
                    <Text size="sm" c="dimmed">
                      No results found.
                    </Text>
                  ) : (
                    <Stack gap="xs">
                      {searchResults.map((result) => (
                        <UnstyledButton
                          key={result.provider_id}
                          w="100%"
                          onClick={() => setSelectedResult(result)}
                        >
                          <Card
                            p="xs"
                            radius="sm"
                            withBorder
                            style={{
                              borderColor:
                                selectedResult?.provider_id === result.provider_id
                                  ? 'var(--mantine-color-pink-6)'
                                  : undefined,
                              backgroundColor:
                                selectedResult?.provider_id === result.provider_id
                                  ? 'var(--mantine-color-dark-5)'
                                  : undefined,
                              cursor: 'pointer',
                            }}
                          >
                            <Group justify="space-between" gap="xs" wrap="nowrap">
                              <Box style={{ flex: 1, minWidth: 0 }}>
                                <Text size="sm" fw={500} truncate>
                                  {result.title}
                                </Text>
                                {result.title_native && (
                                  <Text size="xs" c="dimmed" truncate>
                                    {result.title_native}
                                  </Text>
                                )}
                              </Box>
                              <Group gap={4} style={{ flexShrink: 0 }}>
                                {result.year && (
                                  <Badge size="xs" variant="light" color="gray">
                                    {result.year}
                                  </Badge>
                                )}
                                <Badge size="xs" variant="light" color="blue">
                                  {result.media_type}
                                </Badge>
                              </Group>
                            </Group>
                          </Card>
                        </UnstyledButton>
                      ))}
                    </Stack>
                  )}
                </ScrollArea>
              )}
            </Stack>
          </Box>
        </Box>
      </Group>

      {/* Footer */}
      <Box p="md" style={{ borderTop: '1px solid var(--mantine-color-dark-4)' }}>
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            color="pink"
            disabled={!canImport}
            loading={importMutation.isPending}
            onClick={handleImport}
          >
            Import
          </Button>
        </Group>
      </Box>
    </Modal>
  );
}
