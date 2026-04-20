import { useState } from 'react';
import {
  Center,
  Divider,
  Drawer,
  Loader,
  NumberInput,
  PasswordInput,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
  Anchor,
} from '@mantine/core';
import type { OptionsMap } from '../hooks/useOptions';
import { useOptions, useSaveOptions } from '../hooks/useOptions';

// ─── Language list ────────────────────────────────────────────────────────────

const LANGUAGES = [
  { code: 'ar', name: 'Arabic' },
  { code: 'ca', name: 'Catalan' },
  { code: 'zh', name: 'Chinese' },
  { code: 'hr', name: 'Croatian' },
  { code: 'cs', name: 'Czech' },
  { code: 'da', name: 'Danish' },
  { code: 'nl', name: 'Dutch' },
  { code: 'en', name: 'English' },
  { code: 'fi', name: 'Finnish' },
  { code: 'fr', name: 'French' },
  { code: 'de', name: 'German' },
  { code: 'el', name: 'Greek' },
  { code: 'hu', name: 'Hungarian' },
  { code: 'id', name: 'Indonesian' },
  { code: 'it', name: 'Italian' },
  { code: 'ja', name: 'Japanese' },
  { code: 'ko', name: 'Korean' },
  { code: 'no', name: 'Norwegian' },
  { code: 'pl', name: 'Polish' },
  { code: 'pt', name: 'Portuguese' },
  { code: 'ro', name: 'Romanian' },
  { code: 'ru', name: 'Russian' },
  { code: 'sr', name: 'Serbian' },
  { code: 'sk', name: 'Slovak' },
  { code: 'sl', name: 'Slovenian' },
  { code: 'es', name: 'Spanish' },
  { code: 'sv', name: 'Swedish' },
  { code: 'tr', name: 'Turkish' },
  { code: 'uk', name: 'Ukrainian' },
  { code: 'vi', name: 'Vietnamese' },
];

// ─── Field components (save on blur / change) ─────────────────────────────────

function SaveOnBlurText({
  optionKey,
  label,
  description,
  defaultValue,
  placeholder,
}: {
  optionKey: string;
  label: string;
  description: string;
  defaultValue: string | null;
  placeholder?: string;
}) {
  const { mutate } = useSaveOptions();
  return (
    <TextInput
      label={label}
      description={description}
      defaultValue={defaultValue ?? ''}
      placeholder={placeholder}
      onBlur={(e) => mutate({ [optionKey]: e.currentTarget.value || null })}
    />
  );
}

function SaveOnBlurPassword({
  optionKey,
  label,
  description,
  defaultValue,
}: {
  optionKey: string;
  label: string;
  description: string;
  defaultValue: string | null;
}) {
  const { mutate } = useSaveOptions();
  return (
    <PasswordInput
      label={label}
      description={description}
      defaultValue={defaultValue ?? ''}
      onBlur={(e) => mutate({ [optionKey]: e.currentTarget.value || null })}
    />
  );
}

function SaveOnBlurNumber({
  optionKey,
  label,
  description,
  defaultValue,
  min,
  max,
}: {
  optionKey: string;
  label: string;
  description: string;
  defaultValue: string | null;
  min?: number;
  max?: number;
}) {
  const { mutate } = useSaveOptions();
  const [value, setValue] = useState<number | string>(
    defaultValue != null ? Number(defaultValue) : ''
  );
  return (
    <NumberInput
      label={label}
      description={description}
      value={value}
      onChange={setValue}
      onBlur={() => typeof value === 'number' && mutate({ [optionKey]: String(value) })}
      min={min}
      max={max}
    />
  );
}

function SaveOnChangeSelect({
  optionKey,
  label,
  description,
  defaultValue,
  data,
}: {
  optionKey: string;
  label: string;
  description: string;
  defaultValue: string | null;
  data: { value: string; label: string }[];
}) {
  const { mutate } = useSaveOptions();
  const [value, setValue] = useState<string | null>(defaultValue);
  return (
    <Select
      label={label}
      description={description}
      value={value}
      onChange={(v) => { setValue(v); mutate({ [optionKey]: v }); }}
      data={data}
    />
  );
}

function SaveOnBlurTextarea({
  optionKey,
  label,
  description,
  defaultValue,
  onReset,
}: {
  optionKey: string;
  label: string;
  description: string;
  defaultValue: string | null;
  onReset: () => void;
}) {
  const { mutate } = useSaveOptions();
  return (
    <Textarea
      label={
        <span>
          {label}&nbsp;
          <Anchor size="xs" c="dimmed" onClick={onReset} style={{ fontWeight: 400 }}>
            reset to default
          </Anchor>
        </span>
      }
      description={description}
      defaultValue={defaultValue ?? ''}
      onBlur={(e) => mutate({ [optionKey]: e.currentTarget.value || null })}
      autosize
      minRows={4}
      maxRows={14}
      styles={{ input: { fontFamily: 'monospace', fontSize: 12 } }}
    />
  );
}

function SaveOnChangeSwitch({
  optionKey,
  label,
  description,
  defaultValue,
}: {
  optionKey: string;
  label: string;
  description: string;
  defaultValue: string | null;
}) {
  const { mutate } = useSaveOptions();
  const [checked, setChecked] = useState(
    (defaultValue ?? '0').trim().toLowerCase() === '1'
  );
  return (
    <Switch
      label={label}
      description={description}
      checked={checked}
      onChange={(e) => {
        setChecked(e.currentTarget.checked);
        mutate({ [optionKey]: e.currentTarget.checked ? '1' : '0' });
      }}
    />
  );
}

function LanguageSelect({ defaultCode }: { defaultCode: string | null }) {
  const { mutate } = useSaveOptions();
  const [code, setCode] = useState<string | null>(defaultCode);

  const handleChange = (val: string | null) => {
    setCode(val);
    const lang = LANGUAGES.find((l) => l.code === val);
    mutate({ TARGET_LANG_CODE: val, TARGET_LANG_NAME: lang?.name ?? null });
  };

  return (
    <Select
      label="Target language"
      description="Language subtitles will be translated into. Sets both the grammar provider language code and the display name used in LLM prompts."
      value={code}
      onChange={handleChange}
      data={LANGUAGES.map((l) => ({ value: l.code, label: l.name }))}
      searchable
      clearable
      placeholder="Select a language…"
    />
  );
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Stack gap="sm">
      <Title order={6} c="dimmed" style={{ textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {title}
      </Title>
      {children}
    </Stack>
  );
}

// ─── Full options form ────────────────────────────────────────────────────────

function OptionsForm({ options }: { options: OptionsMap }) {
  const { mutate } = useSaveOptions();

  const resetPrompt = (key: string) => mutate({ [key]: null });

  return (
    <Stack gap="xl" pb="xl">
      <Section title="Language">
        <LanguageSelect defaultCode={options['TARGET_LANG_CODE'] ?? null} />
      </Section>

      <Divider />

      <Section title="OpenAI">
        <SaveOnBlurPassword
          optionKey="OPENAI_API_KEY"
          label="API key"
          description="Your OpenAI (or compatible) API key. Never shared outside this app."
          defaultValue={options['OPENAI_API_KEY'] ?? null}
        />
        <SaveOnBlurText
          optionKey="OPENAI_API_BASE"
          label="API base URL"
          description="Override the default OpenAI endpoint. Leave blank for api.openai.com. Useful for Azure OpenAI, local LLMs (Ollama), or proxies."
          defaultValue={options['OPENAI_API_BASE'] ?? null}
          placeholder="https://api.openai.com/v1"
        />
        <SaveOnBlurText
          optionKey="OPENAI_MODEL_CHEAP"
          label="Cheap model"
          description="Used for translation jobs where speed and cost matter."
          defaultValue={options['OPENAI_MODEL_CHEAP'] ?? null}
        />
        <SaveOnBlurText
          optionKey="OPENAI_MODEL_BETTER"
          label="Better model"
          description="Used for repair and LLM review jobs where quality is critical."
          defaultValue={options['OPENAI_MODEL_BETTER'] ?? null}
        />
      </Section>

      <Divider />

      <Section title="Grammar">
        <SaveOnChangeSelect
          optionKey="GRAMMAR_PROVIDER"
          label="Grammar provider"
          description="Grammar and spellcheck provider used during chunk review."
          defaultValue={options['GRAMMAR_PROVIDER'] ?? 'languagetool'}
          data={[
            { value: 'languagetool', label: 'LanguageTool' },
            { value: 'korektor', label: 'Korektor' },
            { value: 'none', label: 'None (skip grammar check)' },
          ]}
        />
        <SaveOnBlurText
          optionKey="GRAMMAR_PROVIDER_BASE_URL"
          label="Grammar provider URL"
          description="REST endpoint of the selected grammar provider. Not used when provider is set to None."
          defaultValue={options['GRAMMAR_PROVIDER_BASE_URL'] ?? null}
          placeholder="http://localhost:8010"
        />
      </Section>

      <Divider />

      <Section title="LLM Review">
        <SaveOnChangeSwitch
          optionKey="LLM_REVIEW_ALWAYS"
          label="Always run LLM review"
          description="Run LLM review on every chunk regardless of rules review results. When off, LLM review only runs on chunks where it was flagged as needed."
          defaultValue={options['LLM_REVIEW_ALWAYS'] ?? '0'}
        />
        <SaveOnChangeSwitch
          optionKey="LLM_REVIEW_FLAGGED_ONLY"
          label="Review only flagged events"
          description="Send only events with existing QA issues to the LLM. When off, the entire chunk is sent for review."
          defaultValue={options['LLM_REVIEW_FLAGGED_ONLY'] ?? '1'}
        />
      </Section>

      <Divider />

      <Section title="Processing">
        <SaveOnBlurNumber
          optionKey="CHUNK_SIZE"
          label="Chunk size"
          description="Number of subtitle lines grouped into a single translation chunk. Larger chunks give more context but cost more tokens."
          defaultValue={options['CHUNK_SIZE'] ?? null}
          min={10}
          max={500}
        />
        <SaveOnBlurNumber
          optionKey="PREPEND_CONTEXT_SIZE"
          label="Context lines"
          description="Lines from the previous chunk prepended for context. Helps the model maintain consistency at chunk boundaries."
          defaultValue={options['PREPEND_CONTEXT_SIZE'] ?? null}
          min={0}
          max={50}
        />
        <SaveOnBlurNumber
          optionKey="JOB_WORKER_COUNT"
          label="Worker threads"
          description="Number of parallel background job workers. Takes effect immediately without restart."
          defaultValue={options['JOB_WORKER_COUNT'] ?? null}
          min={1}
          max={32}
        />
      </Section>

      <Divider />

      <Section title="System">
        <SaveOnChangeSelect
          optionKey="LOG_LEVEL"
          label="Log level"
          description="Minimum severity of log messages written to the server console. Takes effect immediately without restart."
          defaultValue={options['LOG_LEVEL'] ?? 'INFO'}
          data={['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((v) => ({ value: v, label: v }))}
        />
      </Section>

      <Divider />

      <Section title="Prompts">
        <Text size="xs" c="dimmed">
          System prompts sent to the LLM. Use <code style={{ fontFamily: 'monospace' }}>{'{TARGET_LANG_NAME}'}</code> as a placeholder for the target language. Clear a prompt to revert to the built-in default.
        </Text>
        <SaveOnBlurTextarea
          optionKey="TRANSLATION_PROMPT"
          label="Translation prompt"
          description="Instructs the model how to translate subtitle chunks."
          defaultValue={options['TRANSLATION_PROMPT'] ?? null}
          onReset={() => resetPrompt('TRANSLATION_PROMPT')}
        />
        <SaveOnBlurTextarea
          optionKey="REPAIR_PROMPT"
          label="Repair prompt"
          description="Instructs the model how to fix translation errors flagged by validation or review."
          defaultValue={options['REPAIR_PROMPT'] ?? null}
          onReset={() => resetPrompt('REPAIR_PROMPT')}
        />
        <SaveOnBlurTextarea
          optionKey="REVIEW_PROMPT"
          label="LLM review prompt"
          description="Instructs the model how to review translated chunks for quality issues."
          defaultValue={options['REVIEW_PROMPT'] ?? null}
          onReset={() => resetPrompt('REVIEW_PROMPT')}
        />
      </Section>
    </Stack>
  );
}

// ─── Drawer ───────────────────────────────────────────────────────────────────

export function OptionsDrawer({
  opened,
  onClose,
}: {
  opened: boolean;
  onClose: () => void;
}) {
  const { data: options, isLoading } = useOptions();

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={<Title order={4}>Settings</Title>}
      position="right"
      size={520}
      scrollAreaComponent={undefined}
    >
      {isLoading ? (
        <Center h={200}><Loader /></Center>
      ) : options ? (
        <OptionsForm key={JSON.stringify(options)} options={options} />
      ) : null}
    </Drawer>
  );
}
