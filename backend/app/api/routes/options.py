from typing import Annotated

from fastapi import APIRouter, Body

from app.db import options as options_store

router = APIRouter(prefix="/options", tags=["options"])


@router.get("", response_model=dict[str, str | None])
async def get_options() -> dict[str, str | None]:
    opts = await options_store.asnapshot()
    return {
        "TARGET_LANG_NAME": opts.target_lang_name,
        "TARGET_LANG_CODE": opts.target_lang_code,
        "CHUNK_SIZE": str(opts.chunk_size),
        "PREPEND_CONTEXT_SIZE": str(opts.prepend_context_size),
        "OPENAI_API_BASE": opts.openai_api_base,
        "OPENAI_API_KEY": opts.openai_api_key,
        "OPENAI_MODEL_CHEAP": opts.openai_model_cheap,
        "OPENAI_MODEL_BETTER": opts.openai_model_better,
        "GRAMMAR_PROVIDER": opts.grammar_provider,
        "GRAMMAR_PROVIDER_BASE_URL": opts.grammar_provider_base_url,
        "LOG_LEVEL": opts.log_level,
        "JOB_WORKER_COUNT": str(opts.job_worker_count),
        "LLM_REVIEW_ALWAYS": "1" if opts.llm_review_always else "0",
        "LLM_REVIEW_FLAGGED_ONLY": "1" if opts.llm_review_flagged_only else "0",
        "TRANSLATION_PROMPT": opts.translation_prompt,
        "REPAIR_PROMPT": opts.repair_prompt,
        "REVIEW_PROMPT": opts.review_prompt,
    }


@router.patch("", status_code=204)
async def patch_options(
    body: Annotated[dict[str, str | None], Body()],
) -> None:
    for key, value in body.items():
        await options_store.aset(key, value or None)
