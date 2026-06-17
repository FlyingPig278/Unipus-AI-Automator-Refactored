from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils import logger


UNCACHED_ANSWER = "未缓存"


@dataclass
class ListeningExportEntry:
    breadcrumb: list[str]
    question_index: int
    media_url: str
    transcript: str
    question: str
    options: list[str]
    answer: str


class ListeningExportService:
    """Collect audio-only choice questions and render them as a review document."""

    def __init__(self, driver_service: Any = None, ai_service: Any = None, cache_service: Any = None):
        self.driver_service = driver_service
        self.ai_service = ai_service
        self.cache_service = cache_service

    @staticmethod
    def map_answers_to_questions(strategy_type: str | None, answers: list[str], question_count: int) -> list[str]:
        if question_count <= 0:
            return []

        normalized_answers = [str(answer).strip().upper() for answer in answers if str(answer).strip()]
        if not normalized_answers:
            return [UNCACHED_ANSWER] * question_count

        if strategy_type == "multiple_choice" and question_count == 1:
            return [", ".join(normalized_answers)]

        if len(normalized_answers) == question_count:
            return normalized_answers

        mapped = normalized_answers[:question_count]
        mapped.extend([UNCACHED_ANSWER] * (question_count - len(mapped)))
        return mapped

    @staticmethod
    def render_markdown(entries: list[ListeningExportEntry], generated_at: str | None = None) -> str:
        timestamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "# U校园听力题导出",
            "",
            f"生成时间：{timestamp}",
            f"题目数量：{len(entries)}",
            "",
        ]

        for index, entry in enumerate(entries, start=1):
            breadcrumb = " > ".join(entry.breadcrumb)
            lines.extend(
                [
                    f"## {index}. {breadcrumb}",
                    "",
                    f"- 题号：{entry.question_index}",
                    f"- 音频：{entry.media_url or '未找到音频地址'}",
                    f"- 答案：{entry.answer or UNCACHED_ANSWER}",
                    "",
                    "### 听力原文",
                    "",
                    entry.transcript.strip() or "未提取到听力原文。",
                    "",
                    "### 题目",
                    "",
                    entry.question.strip() or "未提取到题干。",
                    "",
                    "### 选项",
                    "",
                ]
            )
            lines.extend(option.strip() for option in entry.options if option.strip())
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def write_markdown(path: str | Path, entries: list[ListeningExportEntry]) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ListeningExportService.render_markdown(entries), encoding="utf-8")

    async def collect_current_task_entries(self) -> list[ListeningExportEntry]:
        base_breadcrumb_parts = await self.driver_service.get_breadcrumb_parts()
        if not base_breadcrumb_parts:
            logger.warning("听力保存模式：无法获取当前任务面包屑，跳过。")
            return []

        entries: list[ListeningExportEntry] = []
        shared_transcript = ""
        shared_media_url = ""
        sub_task_index = 0

        while True:
            button_text = await self._get_action_button_text()
            is_chained_page = sub_task_index > 0 or "下一题" in button_text or "下一页" in button_text
            breadcrumb_parts = (
                base_breadcrumb_parts + [str(sub_task_index)]
                if is_chained_page
                else base_breadcrumb_parts
            )

            page_entries, shared_transcript, shared_media_url = await self.collect_current_page_entries(
                breadcrumb_parts,
                shared_transcript,
                shared_media_url,
            )
            entries.extend(page_entries)

            if "下一题" in button_text or "下一页" in button_text:
                action_btn = self.driver_service.page.locator(
                    ".btn:has-text('下一题'), .btn:has-text('下一页')"
                ).first
                logger.info("听力保存模式：进入下一个子题页面。")
                await action_btn.click()
                await asyncio.sleep(1)
                await self.driver_service.handle_common_popups()
                sub_task_index += 1
                continue

            return entries

    async def collect_current_page_entries(
        self,
        breadcrumb_parts: list[str],
        shared_transcript: str = "",
        shared_media_url: str = "",
    ) -> tuple[list[ListeningExportEntry], str, str]:
        media_url, media_type = await self.driver_service.get_media_source_and_type()
        if media_type == "video":
            logger.info("听力保存模式：检测到视频材料，按配置跳过。")
            return [], shared_transcript, shared_media_url

        page_transcript = ""
        if media_type == "audio" and media_url:
            logger.info(f"听力保存模式：发现音频，开始转写: {media_url}")
            try:
                page_transcript = self.ai_service.transcribe_media_from_url(media_url) or ""
            except Exception as e:
                logger.warning(f"听力保存模式：音频转写失败，将继续保存题干和选项: {e}")

        accumulated_transcript = "\n\n".join(
            part.strip() for part in [shared_transcript, page_transcript] if part and part.strip()
        )
        accumulated_media_url = " ; ".join(
            part.strip() for part in [shared_media_url, media_url or ""] if part and part.strip()
        )
        questions = await self.extract_choice_questions()

        if not questions:
            if page_transcript:
                logger.info("听力保存模式：当前页只有音频材料，保存为后续子题上下文。")
                return [], accumulated_transcript, accumulated_media_url
            return [], shared_transcript, shared_media_url

        entry_transcript = page_transcript.strip() or shared_transcript.strip()
        entry_media_url = media_url or shared_media_url
        if not entry_transcript:
            logger.info("听力保存模式：当前选择题页没有音频上下文，跳过非听力题。")
            return [], shared_transcript, shared_media_url

        cache = self.cache_service.get_task_page_cache(breadcrumb_parts) if self.cache_service else None
        cache_type = cache.get("type") if isinstance(cache, dict) else self._infer_strategy_type(questions)
        cached_answers = cache.get("answers", []) if isinstance(cache, dict) else []
        answers = self.map_answers_to_questions(cache_type, cached_answers, len(questions))

        entries = []
        for index, question in enumerate(questions, start=1):
            entries.append(
                ListeningExportEntry(
                    breadcrumb=breadcrumb_parts,
                    question_index=index,
                    media_url=entry_media_url or "",
                    transcript=entry_transcript,
                    question=question["question"],
                    options=question["options"],
                    answer=answers[index - 1] if index - 1 < len(answers) else UNCACHED_ANSWER,
                )
            )

        logger.info(f"听力保存模式：当前页保存 {len(entries)} 道听力选择题。")
        return entries, accumulated_transcript, accumulated_media_url

    async def extract_choice_questions(self) -> list[dict[str, Any]]:
        return await self.driver_service.page.evaluate(
            """
            () => Array.from(document.querySelectorAll('.question-common-abs-choice'))
                .map((wrap) => {
                    const title = (wrap.querySelector('.ques-title')?.textContent || '').trim();
                    const options = Array.from(wrap.querySelectorAll('.option'))
                        .map((option) => {
                            const caption = (option.querySelector('.caption')?.textContent || '').trim();
                            const content = (option.querySelector('.content')?.textContent || '').trim();
                            return `${caption}. ${content}`.replace(/\\s+/g, ' ').trim();
                        })
                        .filter(Boolean);
                    return {
                        strategy_type: wrap.classList.contains('multipleChoice') ? 'multiple_choice' : 'single_choice',
                        question: title.replace(/\\s+/g, ' '),
                        options
                    };
                })
                .filter((question) => question.options.length > 0)
            """
        )

    async def _get_action_button_text(self) -> str:
        try:
            action_btn = self.driver_service.page.locator(
                ".btn:has-text('下一题'), .btn:has-text('下一页'), .btn:has-text('提 交'), .btn:has-text('提交')"
            ).first
            await action_btn.wait_for(state="visible", timeout=2000)
            return (await action_btn.text_content() or "").strip()
        except Exception:
            return ""

    def _infer_strategy_type(self, questions: list[dict[str, Any]]) -> str:
        if len(questions) == 1:
            return questions[0].get("strategy_type", "single_choice")
        return "single_choice"
