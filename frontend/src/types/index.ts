// ─── Projects ────────────────────────────────────────────────────────────────

export type ProjectStatus =
  | 'new'
  | 'discovering'
  | 'waiting_for_mapping'
  | 'processing'
  | 'review_required'
  | 'completed'
  | 'failed';

export type SpeakerMappingStatus =
  | 'awaiting_discovery'
  | 'mapping_required'
  | 'mapping_complete'
  | 'no_speakers';

export interface Project {
  id: number;
  name: string;
  source_directory: string;
  anime_provider: string;
  anime_external_id: string;
  speaker_mapping_status: SpeakerMappingStatus;
  status: ProjectStatus;
  is_paused: boolean;
  created_at: string;
  updated_at: string;
}

// ─── Files ────────────────────────────────────────────────────────────────────

export type FileStatus =
  | 'new'
  | 'discovering'
  | 'waiting'
  | 'ready'
  | 'processing'
  | 'review_required'
  | 'muxing'
  | 'completed'
  | 'paused'
  | 'failed';

export type FileBlockingReason =
  | 'project_mapping_required'
  | 'user_review_required'
  | 'subtitle_missing'
  | 'subtitle_parse_failed'
  | 'translation_failed'
  | 'validation_failed'
  | 'mux_failed'
  | 'paused';

export interface SubtitleChunk {
  id: number;
  chunk_index: number;
  translate_from_line: number;
  translate_to_line: number;
  status: string;
  model: string | null;
  llm_review_needed: boolean;
  retry_count: number;
  repair_attempt_count: number;
  last_error_code: string | null;
  last_error_message: string | null;
  failed_job_type: string | null;
  qa_errors: number;
  qa_warnings: number;
  jobs: Record<string, ChunkJob>;
}

export interface ChunkJob {
  id: number;
  job_type: string;
  status: JobStatus;
  attempt_count: number;
  result: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  scheduled_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface VideoFile {
  id: number;
  project_id: number;
  filename: string;
  relative_path: string;
  status: FileStatus;
  blocking_reason: FileBlockingReason | null;
  detected_subtitle_format: string | null;
  subtitle_track_index: number | null;
  retry_count: number;
  last_error_code: string | null;
  last_error_message: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  chunks_done?: number | null;
  chunks_total?: number | null;
  qa_issues: number;
  qa_errors: number;
  qa_warnings: number;
}

export interface QaIssue {
  id: number;
  severity: string;
  qa_type: string;
  message: string;
  details_json: string | null;
  created_at: string;
}

export interface SubtitleEventEditorRow {
  id: number;
  file_id: number;
  line_index: number;
  event_type: string;
  source_text: string;
  translated_text: string | null;
  original_ai_translated_text: string | null;
  speaker_name: string | null;
  character_name: string | null;
  character_gender: string | null;
  is_user_edited: boolean;
  is_locked: boolean;
  is_approved: boolean;
  issues: QaIssue[];
}

// ─── Characters & Speakers ───────────────────────────────────────────────────

export interface ProjectCharacter {
  id: number;
  project_id: number;
  external_id: string | null;
  name: string;
  role: string | null;
  gender: string | null;
  social_position: string | null;
  aliases: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectCharacterWithSpeakers extends ProjectCharacter {
  speaker_ids: number[];
}

export interface ProjectSpeakerWithCount extends ProjectSpeaker {
  mapping_count: number;
}

export interface ProjectSpeaker {
  id: number;
  project_id: number;
  name: string;
  created_at: string;
  updated_at: string;
}

// ─── Project stats ────────────────────────────────────────────────────────────

export interface ProjectStats {
  qa_errors: number;
  qa_warnings: number;
}



export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface Job {
  id: number;
  project_id: number;
  file_id: number | null;
  job_type: string;
  status: JobStatus;
  dedupe_key: string;
  priority: number;
  payload_json: string | null;
  result_json: string | null;
  attempt_count: number;
  max_attempts: number;
  error_code: string | null;
  error_message: string | null;
  scheduled_at: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  // Real-time progress — in-memory only, delivered via WebSocket
  progress?: number;
  message?: string;
  project_name?: string;
}

// ─── Scheduler ───────────────────────────────────────────────────────────────

export type TriggerType = 'cron' | 'interval';

export interface ScheduledTask {
  id: string;
  name: string;
  job_type: string;
  project_id: number;
  payload: Record<string, unknown>;
  trigger_type: TriggerType;
  trigger_config: Record<string, unknown>;
  enabled: boolean;
  last_triggered_at: string | null;
  created_at: string;
}

// ─── Metadata ─────────────────────────────────────────────────────────────────

export interface SearchResult {
  provider_id: string;
  title: string;
  title_native: string | null;
  year: number | null;
  media_type: string;
}

// ─── Import ───────────────────────────────────────────────────────────────────

export interface ImportDirectory {
  name: string;
  file_count: number;
}

// ─── WebSocket Events ─────────────────────────────────────────────────────────

export type WsEvent =
  | { event: 'job_created'; data: WsJobData }
  | { event: 'job_update'; data: WsJobData }
  | { event: 'job_progress'; data: { job_id: number; progress: number; message: string } }
  | { event: 'project_updated'; data: { project_id: number } }
  | { event: 'chunk_progress'; data: { file_id: number; project_id: number; chunks_done: number; chunks_total: number } }
  | { event: 'scheduler_trigger'; data: { schedule_id: string; job_id: number } };

export interface WsJobData {
  job_id: number;
  status?: JobStatus | string;
  project_id?: number;
  file_id?: number | null;
  job_type?: string;
  payload_json?: string | null;
  result_json?: string | null;
  attempt_count?: number;
  error_code?: string | null;
  error_message?: string | null;
  scheduled_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string;
}

