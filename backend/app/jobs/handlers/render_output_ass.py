from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pysubs2
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SyncSessionLocal
from app.db.models import File, Subtitle, SubtitleEvent, SubtitleStyle
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)


def _str_to_color(s: str | None) -> pysubs2.Color:
    """Parse stored &HAABBGGRR& string back to pysubs2.Color."""
    if not s:
        return pysubs2.Color(255, 255, 255, 0)
    hex_str = s.strip().lstrip("&H").rstrip("&").zfill(8)
    a = int(hex_str[0:2], 16)
    b = int(hex_str[2:4], 16)
    g = int(hex_str[4:6], 16)
    r = int(hex_str[6:8], 16)
    return pysubs2.Color(r, g, b, a)


def _safe_output_path(ctx: JobContext, source_directory: str, relative_path: str) -> Path:
    candidate = (ctx.output_root / source_directory / relative_path).resolve()
    if not candidate.is_relative_to(ctx.output_root.resolve()):
        raise ValueError(f"Resolved path {candidate} escapes output root")
    return candidate


@register_job_handler("render_output_ass")
def render_output_ass(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    file_id: int = payload["file_id"]

    progress(0.05, "Loading DB records")

    with SyncSessionLocal() as session:
        file = session.get(File, file_id, options=[selectinload(File.project)])
        if file is None:
            return JobResult(status="failed", result=None,
                             error_code="FILE_NOT_FOUND",
                             error_message=f"File id={file_id} not found")

        source_directory = file.project.source_directory
        relative_path = file.relative_path

        subtitle = session.scalar(
            select(Subtitle).where(Subtitle.file_id == file_id)
        )
        if subtitle is None:
            return JobResult(status="failed", result=None,
                             error_code="SUBTITLE_NOT_EXTRACTED",
                             error_message="No subtitle record - run extract_subtitles first")

        styles = session.scalars(
            select(SubtitleStyle).where(SubtitleStyle.file_id == file_id)
        ).all()

        events = session.scalars(
            select(SubtitleEvent)
            .where(SubtitleEvent.file_id == file_id)
            .order_by(SubtitleEvent.line_index)
        ).all()

        # Snapshot data before closing session
        subtitle_data = {
            "script_type": subtitle.script_type,
            "wrap_style": subtitle.wrap_style,
            "play_res_x": subtitle.play_res_x,
            "play_res_y": subtitle.play_res_y,
            "scaled_border_and_shadow": subtitle.scaled_border_and_shadow,
            "layout_res_x": subtitle.layout_res_x,
            "layout_res_y": subtitle.layout_res_y,
            "ycbcr_matrix": subtitle.ycbcr_matrix,
            "kerning": subtitle.kerning,
            "extra_script_info_json": subtitle.extra_script_info_json,
        }
        styles_data = [
            {
                "style_name": s.style_name,
                "font_name": s.replacement_font_name or s.font_name,
                "font_size": s.replacement_font_size if s.replacement_font_size is not None else s.font_size,
                "primary_colour": s.primary_colour,
                "secondary_colour": s.secondary_colour,
                "outline_colour": s.outline_colour,
                "back_colour": s.back_colour,
                "bold": s.bold, "italic": s.italic,
                "underline": s.underline, "strikeout": s.strikeout,
                "scale_x": s.scale_x, "scale_y": s.scale_y,
                "spacing": s.spacing, "angle": s.angle,
                "border_style": s.border_style,
                "outline": s.outline, "shadow": s.shadow,
                "alignment": s.alignment,
                "margin_l": s.margin_l, "margin_r": s.margin_r, "margin_v": s.margin_v,
                "encoding": s.encoding,
            }
            for s in styles
        ]
        events_data = [
            {
                "event_type": e.event_type,
                "layer": e.layer,
                "start_ms": e.start_ms,
                "end_ms": e.end_ms,
                "style": e.style,
                "name": e.name or "",
                "margin_l": e.margin_l or 0,
                "margin_r": e.margin_r or 0,
                "margin_v": e.margin_v or 0,
                "effect": e.effect or "",
                "text": e.translated_text if e.translated_text is not None else e.source_text,
            }
            for e in events
        ]

    try:
        output_ass_path = _safe_output_path(
            ctx, source_directory, str(Path(relative_path).with_suffix(".ass"))
        )
    except ValueError as exc:
        return JobResult(status="failed", result=None,
                         error_code="INVALID_PATH", error_message=str(exc))

    progress(0.25, "Building ASS structure")

    subs = pysubs2.SSAFile()
    subs.info.clear()

    # [Script Info]
    if subtitle_data["script_type"]:
        subs.info["ScriptType"] = subtitle_data["script_type"]
    if subtitle_data["wrap_style"] is not None:
        subs.info["WrapStyle"] = str(subtitle_data["wrap_style"])
    if subtitle_data["play_res_x"] is not None:
        subs.info["PlayResX"] = str(subtitle_data["play_res_x"])
    if subtitle_data["play_res_y"] is not None:
        subs.info["PlayResY"] = str(subtitle_data["play_res_y"])
    if subtitle_data["scaled_border_and_shadow"]:
        subs.info["ScaledBorderAndShadow"] = subtitle_data["scaled_border_and_shadow"]
    if subtitle_data["layout_res_x"] is not None:
        subs.info["LayoutResX"] = str(subtitle_data["layout_res_x"])
    if subtitle_data["layout_res_y"] is not None:
        subs.info["LayoutResY"] = str(subtitle_data["layout_res_y"])
    if subtitle_data["ycbcr_matrix"]:
        subs.info["YCbCr Matrix"] = subtitle_data["ycbcr_matrix"]
    if subtitle_data["kerning"]:
        subs.info["Kerning"] = subtitle_data["kerning"]
    if subtitle_data["extra_script_info_json"]:
        extra = json.loads(subtitle_data["extra_script_info_json"])
        subs.info.update(extra)

    subs.info["Title"] = ctx.options.target_lang_name or ""

    # [V4+ Styles]
    subs.styles.clear()
    for sd in styles_data:
        style = pysubs2.SSAStyle(
            fontname=sd["font_name"],
            fontsize=float(sd["font_size"]),
            primarycolor=_str_to_color(sd["primary_colour"]),
            secondarycolor=_str_to_color(sd["secondary_colour"]),
            outlinecolor=_str_to_color(sd["outline_colour"]),
            backcolor=_str_to_color(sd["back_colour"]),
            bold=bool(sd["bold"]) if sd["bold"] is not None else False,
            italic=bool(sd["italic"]) if sd["italic"] is not None else False,
            underline=bool(sd["underline"]) if sd["underline"] is not None else False,
            strikeout=bool(sd["strikeout"]) if sd["strikeout"] is not None else False,
            scalex=float(sd["scale_x"]) if sd["scale_x"] is not None else 100.0,
            scaley=float(sd["scale_y"]) if sd["scale_y"] is not None else 100.0,
            spacing=float(sd["spacing"]) if sd["spacing"] is not None else 0.0,
            angle=float(sd["angle"]) if sd["angle"] is not None else 0.0,
            borderstyle=int(sd["border_style"]) if sd["border_style"] is not None else 1,
            outline=float(sd["outline"]) if sd["outline"] is not None else 2.0,
            shadow=float(sd["shadow"]) if sd["shadow"] is not None else 0.0,
            alignment=int(sd["alignment"]) if sd["alignment"] is not None else 2,
            marginl=int(sd["margin_l"]) if sd["margin_l"] is not None else 10,
            marginr=int(sd["margin_r"]) if sd["margin_r"] is not None else 10,
            marginv=int(sd["margin_v"]) if sd["margin_v"] is not None else 10,
            encoding=int(sd["encoding"]) if sd["encoding"] is not None else 1,
        )
        subs.styles[sd["style_name"]] = style

    # [Events]
    for ed in events_data:
        event = pysubs2.SSAEvent(
            start=ed["start_ms"],
            end=ed["end_ms"],
            layer=ed["layer"],
            style=ed["style"],
            name=ed["name"],
            marginl=ed["margin_l"],
            marginr=ed["margin_r"],
            marginv=ed["margin_v"],
            effect=ed["effect"],
            text=ed["text"],
        )
        event.type = ed["event_type"].capitalize()
        subs.append(event)

    progress(0.75, f"Writing ASS ({len(events_data)} events, {len(styles_data)} styles)")

    output_ass_path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(output_ass_path), encoding="utf-8")

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={
            "output_ass_path": str(output_ass_path),
            "events_written": len(events_data),
        },
        error_code=None,
        error_message=None,
    )
