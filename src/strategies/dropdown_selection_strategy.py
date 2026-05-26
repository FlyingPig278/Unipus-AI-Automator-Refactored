import asyncio
import re

from playwright.async_api import Error as PlaywrightError

from src import prompts, config
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_strategy import BaseStrategy
from src.utils import logger


class DropdownSelectionStrategy(BaseStrategy):
    """
    处理下拉填空题。

    这类题目使用 .fe-scoop 承载空位，但作答控件是 Ant Dropdown，
    选项通常藏在 scoop-select-wrapper 内的隐藏测宽节点中。
    """

    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "dropdown_selection"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        try:
            dropdown_blank = driver_service.page.locator(
                ".comp-scoop-reply-dropdown-selection-overflow .fe-scoop "
                ".ant-dropdown-trigger.user-answer"
            ).first
            if await dropdown_blank.is_visible(timeout=2000):
                logger.info("检测到下拉填空题，应用下拉填空题策略。")
                return True
        except PlaywrightError:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False, sub_task_index: int = -1) -> tuple[bool, bool]:
        logger.info("=" * 20)
        logger.info("开始执行下拉填空题策略...")

        try:
            base_breadcrumb_parts = await self.driver_service.get_breadcrumb_parts()
            blank_count = await self.driver_service.page.locator(".question-common-abs-reply .fe-scoop").count()
            if not base_breadcrumb_parts or blank_count == 0:
                logger.error("无法获取页面关键信息（面包屑或下拉空），终止策略。")
                return False, False
        except Exception as e:
            logger.error(f"提取面包屑或下拉空时出错: {e}")
            return False, False

        current_breadcrumb_parts = base_breadcrumb_parts
        if is_chained_task and sub_task_index != -1:
            current_breadcrumb_parts = base_breadcrumb_parts + [str(sub_task_index)]
            logger.info(f"题中题缓存路径：{' -> '.join(current_breadcrumb_parts)}")

        cache_write_needed = False
        answers_to_select = []
        use_cache = False

        if not is_chained_task or sub_task_index != -1:
            task_page_cache = self.cache_service.get_task_page_cache(current_breadcrumb_parts)
            if not config.FORCE_AI and task_page_cache and task_page_cache.get("type") == self.strategy_type:
                cached_answers = task_page_cache.get("answers", [])
                if len(cached_answers) == blank_count:
                    logger.info("在缓存中找到此页面的下拉题答案。")
                    answers_to_select = cached_answers
                    use_cache = True
                else:
                    logger.warning("缓存答案数量与当前下拉空数量不匹配，将调用AI。")
            elif config.FORCE_AI and task_page_cache:
                logger.info("FORCE_AI为True，强制忽略缓存，调用AI。")

        option_groups = await self._extract_option_groups()
        if len(option_groups) != blank_count:
            logger.error(f"提取到的选项组数量 ({len(option_groups)}) 与下拉空数量 ({blank_count}) 不匹配。")
            return False, False

        if not use_cache:
            logger.info("缓存未命中，将调用AI进行解答...")
            cache_write_needed = True

            logger.info("正在并发提取视频/音频、说明、题干和额外材料...")
            tasks = [
                self._get_article_text(),
                self._get_direction_text(),
                self.driver_service._extract_additional_material_for_ai(),
                self._get_question_text_for_ai(),
            ]
            article_text, direction_text, additional_material, question_text = await asyncio.gather(*tasks)
            logger.info("信息提取完毕。")

            full_context = f"{shared_context}\n{article_text}\n{additional_material}".strip()
            options_text = self._format_options_for_prompt(option_groups)
            prompt = prompts.DROPDOWN_SELECTION_PROMPT.format(
                direction_text=direction_text,
                article_text=full_context,
                question_text=question_text,
                options_text=options_text,
                blank_count=blank_count,
            )

            if not config.IS_AUTO_MODE:
                logger.info("=" * 50)
                logger.info("即将发送给 AI 的完整 Prompt 如下：")
                logger.info(prompt)
                logger.info("=" * 50)

            if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                confirm = await asyncio.to_thread(input, "是否确认发送此 Prompt？[Y/n]: ")
                if confirm.strip().upper() not in ["Y", ""]:
                    logger.warning("用户取消了 AI 调用，终止当前任务。")
                    return False, False

            json_data = self.ai_service.get_chat_completion(prompt)
            if not json_data:
                logger.error("未能从AI获取有效的下拉题答案列表。")
                return False, False

            answers_to_select = json_data.get("answers")
            if answers_to_select is None and isinstance(json_data.get("questions"), list) and json_data["questions"]:
                answers_to_select = json_data["questions"][0].get("answer")

            if not isinstance(answers_to_select, list):
                logger.error("AI返回格式中没有有效的 answers 列表。")
                return False, False

            logger.debug(f"AI回答: {json_data}")

        return await self._fill_and_submit(
            answers_to_select,
            option_groups,
            cache_write_needed,
            current_breadcrumb_parts,
            is_chained_task=is_chained_task,
        )

    async def _get_article_text(self) -> str:
        media_url, media_type = await self.driver_service.get_media_source_and_type()
        if media_url:
            logger.info(f"发现 {media_type} 文件，准备转写: {media_url}")
            try:
                article_text = self.ai_service.transcribe_media_from_url(media_url)
                if not article_text:
                    logger.warning("媒体文件转写失败。")
                return article_text
            except Exception as e:
                logger.error(f"媒体文件转写时发生错误: {e}")
                return ""
        logger.info("未在本页找到可用的音频或视频文件。")
        return ""

    async def _extract_option_groups(self) -> list[list[str]]:
        return await self.driver_service.page.evaluate(
            """
            () => Array.from(document.querySelectorAll('.question-common-abs-reply .fe-scoop')).map((blank) => {
                const rawOptions = Array.from(blank.querySelectorAll('.scoop-select-wrapper > div i, .select-option'))
                    .map((node) => (node.textContent || '').replace(/\\s+/g, ' ').trim())
                    .filter(Boolean);
                return Array.from(new Set(rawOptions));
            })
            """
        )

    async def _get_question_text_for_ai(self) -> str:
        return await self.driver_service.page.evaluate(
            """
            () => {
                const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim();
                const root = document.querySelector('.question-common-abs-reply');
                if (!root) return '';

                const clone = root.cloneNode(true);
                clone.querySelectorAll('script, style, svg').forEach((node) => node.remove());
                clone.querySelectorAll('.fe-scoop').forEach((node, index) => {
                    node.replaceWith(document.createTextNode(`[Blank ${index + 1}]`));
                });

                const tables = Array.from(clone.querySelectorAll('table'));
                if (tables.length) {
                    return tables.map((table) => {
                        const rows = Array.from(table.querySelectorAll('tr')).map((row) => {
                            const cells = Array.from(row.querySelectorAll('th, td')).map((cell) => normalize(cell.textContent));
                            return `| ${cells.join(' | ')} |`;
                        }).filter((row) => row !== '|  |');

                        if (rows.length <= 1) return rows.join('\\n');
                        const columnCount = Math.max(...rows.map((row) => row.split('|').length - 2));
                        const separator = `|${Array.from({ length: columnCount }, () => ':---:').join('|')}|`;
                        return [rows[0], separator, ...rows.slice(1)].join('\\n');
                    }).join('\\n\\n');
                }

                return normalize(clone.textContent);
            }
            """
        )

    def _format_options_for_prompt(self, option_groups: list[list[str]]) -> str:
        sections = []
        for i, options in enumerate(option_groups, start=1):
            option_lines = [f"{index}. {text}" for index, text in enumerate(options, start=1)]
            sections.append(f"[Blank {i}] options:\n" + "\n".join(option_lines))
        return "\n\n".join(sections)

    async def _fill_and_submit(
        self,
        answers: list[str],
        option_groups: list[list[str]],
        cache_write_needed: bool,
        breadcrumb_parts: list[str],
        is_chained_task: bool = False,
    ) -> tuple[bool, bool]:
        try:
            blank_locators = await self.driver_service.page.locator(".question-common-abs-reply .fe-scoop").all()
            if len(answers) != len(blank_locators):
                logger.error(f"AI返回的答案数量 ({len(answers)}) 与下拉空数量 ({len(blank_locators)}) 不匹配，终止作答。")
                return False, False

            selected_indices = []
            for i, answer in enumerate(answers):
                option_index = self._resolve_answer_to_option_index(str(answer), option_groups[i])
                if option_index is None:
                    logger.error(f"第 {i + 1} 个空的答案 '{answer}' 未匹配到任何候选项，终止作答。")
                    return False, False
                selected_indices.append(option_index)

            logger.info("预验证通过，开始选择下拉答案...")
            for i, blank_locator in enumerate(blank_locators):
                option_index = selected_indices[i]
                answer_text = option_groups[i][option_index]
                logger.info(f"第 {i + 1} 个空，选择: '{answer_text}'")

                trigger = blank_locator.locator(".ant-dropdown-trigger.user-answer").first
                await trigger.click()
                visible_options = self.driver_service.page.locator(
                    ".ant-dropdown:not(.ant-dropdown-hidden) .select-option"
                )
                await visible_options.first.wait_for(state="visible", timeout=3000)
                await visible_options.nth(option_index).click()
                await asyncio.sleep(0.2)

            logger.success("下拉题答案选择完毕。")

            if not is_chained_task:
                should_submit = True
                if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                    confirm = await asyncio.to_thread(input, "AI或缓存已选择答案。是否确认提交？[Y/n]: ")
                    if confirm.strip().upper() not in ["Y", ""]:
                        should_submit = False

                if should_submit:
                    await self.driver_service.page.click(".btn")
                    await self.driver_service.handle_rate_limit_modal()
                    logger.info("答案已提交。正在处理最终确认弹窗...")
                    await self.driver_service.handle_submission_confirmation()
                    if cache_write_needed:
                        logger.info("准备从解析页面提取正确答案并写入缓存...")
                        await self._write_answers_to_cache(breadcrumb_parts)
                    return True, cache_write_needed

                logger.warning("用户取消提交。")
                return False, False

            return True, cache_write_needed

        except Exception as e:
            logger.error(f"填写或提交下拉题答案时出错: {e}")
            return False, False

    def _resolve_answer_to_option_index(self, answer: str, options: list[str]) -> int | None:
        cleaned = self._normalize_answer(answer)

        digit_match = re.fullmatch(r"(?:option\s*)?(\d+)", cleaned)
        if digit_match:
            index = int(digit_match.group(1)) - 1
            return index if 0 <= index < len(options) else None

        letter_match = re.fullmatch(r"(?:option\s*)?([a-z])", cleaned)
        if letter_match:
            index = ord(letter_match.group(1)) - ord("a")
            return index if 0 <= index < len(options) else None

        prefixed_match = re.match(r"^(?:option\s*)?(?:\d+|[a-z])[\.\):、]\s*(.+)$", cleaned)
        if prefixed_match:
            cleaned = prefixed_match.group(1).strip()

        normalized_options = [self._normalize_answer(option) for option in options]
        if cleaned in normalized_options:
            return normalized_options.index(cleaned)

        for i, option in enumerate(normalized_options):
            if cleaned and (cleaned in option or option in cleaned):
                return i

        return None

    @staticmethod
    def _normalize_answer(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip().lower()

    async def _write_answers_to_cache(self, breadcrumb_parts: list[str]):
        try:
            await self.driver_service._navigate_to_answer_analysis_page()
            correct_answers_list = await self.driver_service.extract_dropdown_selection_answers_from_analysis_page()

            if not correct_answers_list:
                logger.warning("未能从解析页面提取到任何下拉题答案，无法更新缓存。")
                return

            self.cache_service.save_task_page_answers(
                breadcrumb_parts,
                self.strategy_type,
                correct_answers_list,
            )
        except Exception as e:
            logger.error(f"写入下拉题缓存过程中发生错误: {e}")
