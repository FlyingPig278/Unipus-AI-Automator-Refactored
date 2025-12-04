import asyncio
from playwright.async_api import Error as PlaywrightError

from src import prompts, config
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_strategy import BaseStrategy
from src.utils import logger


class ShortAnswerStrategy(BaseStrategy):
    """
    处理简答题的策略（一页多题）。
    """
    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "short_answer"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        """检查当前页面是否为简答题。"""
        try:
            is_visible = await driver_service.page.locator(".question-inputbox").first.is_visible(timeout=2000)
            if is_visible:
                logger.info("检测到简答题，应用简答题策略。")
                return True
        except PlaywrightError:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False, sub_task_index: int = -1) -> tuple[bool, bool]:
        logger.info("="*20)
        logger.info("开始执行简答题策略...")

        try:
            # 统一提取所有子问题题干和输入框数量
            question_containers = await self.driver_service.page.locator(".question-inputbox").all()
            num_answers_required = len(question_containers)
            
            # 如果没有找到输入框，可能不是预期的页面，提前退出
            if num_answers_required == 0:
                logger.warning("在页面上未找到任何简答题输入框。")
                return False, False

            logger.info("正在并发提取文章、说明等信息...")
            tasks = [
                self._get_article_text(),
                self.driver_service._extract_additional_material_for_ai()
            ]
            results = await asyncio.gather(*tasks)
            article_text, additional_material = results
            direction_text = await self._get_direction_text()
            logger.info("信息提取完毕。")

            full_context = f"{shared_context}\n{article_text}\n{additional_material}".strip()
            is_table_question = "|:---:" in additional_material
            
            sub_questions = []
            for container in question_containers:
                sub_q_text = ""
                try:
                    content = await container.locator(".question-inputbox-header .component-htmlview").text_content(timeout=1000)
                    if content:
                        sub_q_text = content.strip()
                except PlaywrightError:
                    logger.warning("一个简答题的 header 为空，将视其题目内容为空字符串。")
                sub_questions.append(sub_q_text)
            
            sub_questions_text = "\n".join([f"{i+1}. {q}" for i, q in enumerate(sub_questions) if q])
            logger.info(f"提取到 {len(sub_questions)} 个简答题的题干。")

            # 构造关于答案数量的明确指令
            explicit_count_instruction = f"重要指令：页面上共有 {num_answers_required} 个回答框，你必须为每个回答框生成一个答案，总共生成 {num_answers_required} 个答案。"
            # 将此明确指令附加到原有的方向说明中
            final_direction_text = f"{direction_text}\n\n{explicit_count_instruction}"

            if is_table_question:
                logger.info("检测到表格题型，使用专用的表格Prompt。")
                prompt = prompts.TABLE_SHORT_ANSWER_PROMPT.format(
                    direction_text=final_direction_text,
                    article_text=full_context,
                    sub_questions=sub_questions_text
                )
            else:
                logger.info("使用标准简答题Prompt。")
                article_section = f"以下是文章或听力原文内容:\n{full_context}\n\n" if full_context else ""
                prompt = prompts.SHORT_ANSWER_PROMPT.format(
                    direction_text=final_direction_text,
                    article_text=article_section,
                    sub_questions=sub_questions_text
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
            if not json_data or "answers" not in json_data or not isinstance(json_data["answers"], list):
                logger.error("未能从AI获取有效的答案列表。")
                return False, False

            answers_to_fill = json_data["answers"]
            logger.info(f"AI已生成 {len(answers_to_fill)} 个回答。")

            # 因为此策略不支持缓存，所以第二个返回值总是False
            succeeded, _ = await self._fill_and_submit(answers_to_fill, is_chained_task=is_chained_task)
            return succeeded, False

        except Exception as e:
            logger.error(f"执行简答题策略时发生错误: {e}")
            return False, False

    async def _get_article_text(self) -> str:
        try:
            media_url, media_type = await self.driver_service.get_media_source_and_type()
            if media_url:
                logger.info(f"发现 {media_type} 文件，准备转写...")
                return self.ai_service.transcribe_media_from_url(media_url)
            
            article_locator = self.driver_service.page.locator(".comp-common-article-content")
            if await article_locator.is_visible(timeout=1000):
                logger.info("发现文章容器，正在提取文本...")
                return await article_locator.text_content()
        except Exception:
            pass
        logger.info("未找到文章/媒体材料。")
        return ""

    async def _fill_and_submit(self, answers: list[str], is_chained_task: bool = False) -> tuple[bool, bool]:
        try:
            textarea_locators = await self.driver_service.page.locator("textarea.question-inputbox-input").all()

            if len(answers) != len(textarea_locators):
                logger.error(f"AI返回的答案数量 ({len(answers)}) 与页面输入框数量 ({len(textarea_locators)}) 不匹配，终止作答。")
                return False, False

            logger.info("开始填写答案...")
            for i, textarea_locator in enumerate(textarea_locators):
                answer_text = answers[i]
                logger.info(f"第 {i+1} 题，填入: '{answer_text[:50]}...'")
                await textarea_locator.fill(answer_text)
                await asyncio.sleep(0.2)

            logger.success("答案填写完毕。")

            if not is_chained_task:
                should_submit = True
                if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                    confirm = await asyncio.to_thread(input, "AI已填写答案。是否确认提交？[Y/n]: ")
                    if confirm.strip().upper() not in ["Y", ""]:
                        should_submit = False
                
                if should_submit:
                    await self.driver_service.page.click(".btn")
                    await self.driver_service.handle_rate_limit_modal()
                    logger.info("答案已提交。正在处理最终确认弹窗...")
                    await self.driver_service.handle_submission_confirmation()
                    return True, False
                else:
                    logger.warning("用户取消提交。")
                    return False, False
            else:
                return True, False
        except Exception as e:
            logger.error(f"填写或提交答案时出错: {e}")
            return False, False

    async def close(self) -> None:
        pass

