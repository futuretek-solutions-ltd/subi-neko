import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Float, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProjectStatus(str, Enum):
    NEW = "new"
    DISCOVERING = "discovering"
    WAITING_FOR_MAPPING = "waiting_for_mapping"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    COMPLETED = "completed"
    FAILED = "failed"


class FileStatus(str, Enum):
    NEW = "new"
    DISCOVERING = "discovering"
    WAITING = "waiting"
    READY = "ready"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    MUXING = "muxing"
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"


class FileBlockingReason(str, Enum):
    PROJECT_MAPPING_REQUIRED = "project_mapping_required"
    USER_REVIEW_REQUIRED = "user_review_required"
    SUBTITLE_MISSING = "subtitle_missing"
    SUBTITLE_PARSE_FAILED = "subtitle_parse_failed"
    TRANSLATION_FAILED = "translation_failed"
    VALIDATION_FAILED = "validation_failed"
    MUX_FAILED = "mux_failed"
    PAUSED = "paused"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class Option(Base):
    __tablename__ = "options"
    __table_args__ = (
        Index("idx_options_name", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now(), onupdate=func.now())


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("idx_projects_status", "status"),
        Index("idx_projects_mapping_status", "speaker_mapping_status"),
        UniqueConstraint("source_directory", name="uq_projects_source_directory"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_directory: Mapped[str] = mapped_column(Text, nullable=False)
    anime_provider: Mapped[str] = mapped_column(Text, nullable=False)
    anime_external_id: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_mapping_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="awaiting_discovery")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="new")
    is_paused: Mapped[bool] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now(), onupdate=func.now())

    files: Mapped[list["File"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    characters: Mapped[list["ProjectCharacter"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    speakers: Mapped[list["ProjectSpeaker"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    jobs: Mapped[list["JobRecord"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectCharacter(Base):
    __tablename__ = "project_characters"
    __table_args__ = (
        Index("idx_project_characters_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    social_position: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    aliases: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now(), onupdate=func.now())

    project: Mapped["Project"] = relationship(back_populates="characters")
    speaker_mappings: Mapped[list["SpeakerCharacterMapping"]] = relationship(back_populates="character", cascade="all, delete-orphan")


class ProjectSpeaker(Base):
    __tablename__ = "project_speakers"
    __table_args__ = (
        UniqueConstraint("project_id", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now(), onupdate=func.now())

    project: Mapped["Project"] = relationship(back_populates="speakers")
    character_mappings: Mapped[list["SpeakerCharacterMapping"]] = relationship(back_populates="speaker", cascade="all, delete-orphan")


class SpeakerCharacterMapping(Base):
    __tablename__ = "speaker_character_mappings"
    __table_args__ = (
        Index("idx_speaker_character_mappings_character", "character_id"),
    )

    project_speaker_id: Mapped[int] = mapped_column(Integer, ForeignKey("project_speakers.id", ondelete="CASCADE"), primary_key=True)
    character_id: Mapped[int] = mapped_column(Integer, ForeignKey("project_characters.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())

    speaker: Mapped["ProjectSpeaker"] = relationship(back_populates="character_mappings")
    character: Mapped["ProjectCharacter"] = relationship(back_populates="speaker_mappings")


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("project_id", "relative_path"),
        Index("idx_files_project_status", "project_id", "status"),
        Index("idx_files_project_blocking_reason", "project_id", "blocking_reason"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="new")
    blocking_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detected_subtitle_format: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subtitle_track_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="files")
    subtitle: Mapped[Optional["Subtitle"]] = relationship(back_populates="file", cascade="all, delete-orphan", uselist=False)
    subtitle_events: Mapped[list["SubtitleEvent"]] = relationship(back_populates="file", cascade="all, delete-orphan")
    subtitle_styles: Mapped[list["SubtitleStyle"]] = relationship(back_populates="file", cascade="all, delete-orphan")
    subtitle_chunks: Mapped[list["SubtitleChunk"]] = relationship(back_populates="file", cascade="all, delete-orphan")
    qa_items: Mapped[list["QaItem"]] = relationship(back_populates="file", cascade="all, delete-orphan")
    jobs: Mapped[list["JobRecord"]] = relationship(back_populates="file", cascade="all, delete-orphan")


class Subtitle(Base):
    __tablename__ = "subtitles"
    __table_args__ = (
        UniqueConstraint("file_id"),
        Index("idx_subtitles_file", "file_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    script_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    wrap_style: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    play_res_x: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    play_res_y: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scaled_border_and_shadow: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    layout_res_x: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    layout_res_y: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ycbcr_matrix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kerning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_script_info_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now(), onupdate=func.now())

    file: Mapped["File"] = relationship(back_populates="subtitle")


class SubtitleEvent(Base):
    __tablename__ = "subtitle_events"
    __table_args__ = (
        UniqueConstraint("file_id", "line_index"),
        Index("idx_subtitle_events_file_translation_status", "file_id", "translation_status"),
        Index("idx_subtitle_events_file_event_type", "file_id", "event_type"),
        Index("idx_subtitle_events_file_name", "file_id", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    line_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    layer: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    style: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    margin_l: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    margin_r: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    margin_v: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    effect: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_ai_translated_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    translation_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    is_user_edited: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_locked: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_approved: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now(), onupdate=func.now())

    file: Mapped["File"] = relationship(back_populates="subtitle_events")
    qa_items: Mapped[list["QaItem"]] = relationship(back_populates="subtitle_event", cascade="all, delete-orphan")


class SubtitleStyle(Base):
    __tablename__ = "subtitle_styles"
    __table_args__ = (
        UniqueConstraint("file_id", "style_name"),
        Index("idx_subtitle_styles_file_font_check_status", "file_id", "font_check_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    style_name: Mapped[str] = mapped_column(Text, nullable=False)
    font_name: Mapped[str] = mapped_column(Text, nullable=False)
    font_size: Mapped[float] = mapped_column(Float, nullable=False)
    primary_colour: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    secondary_colour: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outline_colour: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    back_colour: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bold: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    italic: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    underline: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    strikeout: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scale_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scale_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spacing: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    angle: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    border_style: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    outline: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shadow: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    alignment: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    margin_l: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    margin_r: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    margin_v: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    encoding: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    replacement_font_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    replacement_font_size: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    font_check_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unchecked")
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now(), onupdate=func.now())

    file: Mapped["File"] = relationship(back_populates="subtitle_styles")


class QaItem(Base):
    __tablename__ = "qa_items"
    __table_args__ = (
        Index("idx_qa_items_file_resolved_severity", "file_id", "is_resolved", "severity"),
        Index("idx_qa_items_event", "subtitle_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    subtitle_event_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("subtitle_events.id", ondelete="CASCADE"), nullable=True)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    qa_type: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_resolved: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(Text, nullable=True)

    file: Mapped["File"] = relationship(back_populates="qa_items")
    subtitle_event: Mapped[Optional["SubtitleEvent"]] = relationship(back_populates="qa_items")


class SubtitleChunk(Base):
    __tablename__ = "subtitle_chunks"
    __table_args__ = (
        UniqueConstraint("file_id", "chunk_index"),
        Index("idx_subtitle_chunks_file", "file_id"),
        Index("idx_subtitle_chunks_file_status", "file_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    translate_from_line: Mapped[int] = mapped_column(Integer, nullable=False)
    translate_to_line: Mapped[int] = mapped_column(Integer, nullable=False)
    context_prepend_from_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    context_prepend_to_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_review_needed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    repair_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failed_job_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now(), onupdate=func.now())

    file: Mapped["File"] = relationship(back_populates="subtitle_chunks")


class JobRecord(Base):
    """DB-backed job record. Source of truth for all job state."""
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("dedupe_key"),
        Index("idx_jobs_status_priority_scheduled", "status", "priority", "scheduled_at"),
        Index("idx_jobs_project_status", "project_id", "status"),
        Index("idx_jobs_file_status", "file_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=True)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    error_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(Text, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Text, nullable=False, server_default=func.now(), onupdate=func.now())

    project: Mapped["Project"] = relationship(back_populates="jobs")
    file: Mapped[Optional["File"]] = relationship(back_populates="jobs")
