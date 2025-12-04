import asyncio
import re
import html
from playwright.async_api import Error as PlaywrightError

from src import prompts, config
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_strategy import BaseStrategy
from src.utils import logger


class FillInTheBlankStrategy(BaseStrategy):
    """
    处理填空题的策略。
    适用于从上下文（文章、听力）中提取信息并填入文本的题目。
    """
    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "fill_in_the_blank"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        """检查当前页面是否为填空题。"""
        try:
            is_visible = await driver_service.page.locator("div.question-common-abs-scoop.comp-scoop-reply.fill-blank-reply").first.is_visible(timeout=2000)
            if is_visible:
                logger.info("检测到填空题，应用填空题策略。")
                return True
        except PlaywrightError:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        logger.info("=" * 20)
        logger.info("开始执行填空题策略...")

        try:
            breadcrumb_parts = await self.driver_service.get_breadcrumb_parts()
            if not breadcrumb_parts:
                logger.error("无法获取页面面包屑，终止策略。")
                return False
        except Exception as e:
            logger.error(f"提取面包屑时出错: {e}")
            return False

        cache_write_needed = False
        answers_to_fill = []
        use_cache = False

        if not is_chained_task:
            task_page_cache = self.cache_service.get_task_page_cache(breadcrumb_parts)
            if not config.FORCE_AI and task_page_cache and task_page_cache.get(
                    'type') == self.strategy_type and task_page_cache.get('answers'):
                logger.info("在缓存中找到此页面的答案。")
                answers_to_fill = task_page_cache.get('answers', [])
                use_cache = True
            elif config.FORCE_AI and task_page_cache:
                logger.info("FORCE_AI为True，强制忽略缓存，调用AI。")

        if use_cache:
            logger.info("所有题目均在缓存中找到答案，直接填写。")
        else:
            if is_chained_task:
                logger.info("处于“题中题”模式，跳过缓存，直接调用AI。")
            else:
                logger.info("缓存未命中，将调用AI进行解答...")

            cache_write_needed = not is_chained_task

            logger.info("正在并发提取文章、说明、题目等信息...")
            tasks = [
                self._get_article_text(),
                self.driver_service._extract_additional_material_for_ai()
            ]
            results = await asyncio.gather(*tasks)
            article_text, additional_material = results
            # 此处 direction_text 和 question_text 紧密耦合，不适合并发
            direction_text = await self._get_direction_text()
            logger.info("信息提取完毕。")

            full_context = f"{shared_context}\n{article_text}\n{additional_material}".strip()

            question_locator = self.driver_service.page.locator(".question-common-abs-reply")
            question_html = await question_locator.inner_html()
            unescaped_html = html.unescape(question_html)
            question_text_for_ai = re.sub(r'<span class="fe-scoop".*?</span>', ' ___ ', unescaped_html)
            question_text_for_ai = re.sub(r'<.*?>', '', question_text_for_ai).strip()

            prompt = prompts.FILL_IN_THE_BLANK_PROMPT.format(
                direction_text=direction_text,
                article_text=full_context,
                question_text=question_text_for_ai
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
                    return False

            json_data = self.ai_service.get_chat_completion(prompt)
            if not json_data or "questions" not in json_data or not json_data["questions"]:
                logger.error("未能从AI获取有效答案。")
                return False

            logger.debug(f"AI回答: {json_data}")
            answers_to_fill = json_data["questions"][0].get("answer", [])

        return await self._fill_and_submit(answers_to_fill, cache_write_needed, breadcrumb_parts,is_chained_task=is_chained_task)

    async def _get_article_text(self) -> str:
        media_url, media_type = await self.driver_service.get_media_source_and_type()
        if media_url:
            logger.info(f"发现 {media_type} 文件，准备转写...")
            try:
                article_text = self.ai_service.transcribe_media_from_url(media_url)
                if not article_text:
                    logger.warning("媒体文件转写失败。")
                return article_text
            except Exception as e:
                logger.error(f"媒体文件转写时发生错误: {e}")
                return ""
        try:
            article_locator = self.driver_service.page.locator(".comp-common-article-content")
            if await article_locator.is_visible():
                logger.info("发现文章容器，正在提取文本...")
                return await article_locator.text_content()
        except PlaywrightError:
            pass
        
        logger.info("未在本页找到可用的音频、视频或文章。")
        return ""

    async def _fill_and_submit(self, answers: list[str], cache_write_needed: bool, breadcrumb_parts: list[str],
                               is_chained_task: bool = False) -> bool:
        try:
            logger.debug("正在解析并预验证答案...")
            input_locators = await self.driver_service.page.locator(".fe-scoop .comp-abs-input input").all()

            if len(answers) != len(input_locators):
                logger.error(f"AI返回的答案数量 ({len(answers)}) 与页面输入框数量 ({len(input_locators)}) 不匹配，终止作答。")
                return False

            logger.info("预验证通过，开始填写答案...")
            for i, input_locator in enumerate(input_locators):
                answer_text = answers[i]
                logger.info(f"第 {i + 1} 个空，填入: '{answer_text}'")
                await input_locator.fill(answer_text)
                await asyncio.sleep(0.2)

            logger.success("答案填写完毕。")

            if not is_chained_task:
                should_submit = True
                if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                    confirm = await asyncio.to_thread(input, "AI或缓存已填写答案。是否确认提交？[Y/n]: ")
                    if confirm.strip().upper() not in ["Y", ""]:
                        should_submit = False
                
                if should_submit:
                    await self.driver_service.page.click(".btn")
                    logger.info("答案已提交。正在处理最终确认弹窗...")
                    await self.driver_service.handle_submission_confirmation()
                    if cache_write_needed:
                        logger.info("准备从解析页面提取正确答案并写入缓存...")
                        await self._write_answers_to_cache(breadcrumb_parts)
                    return True
                else:
                    logger.warning("用户取消提交。")
                    return False
            else:
                return True

        except Exception as e:
            logger.error(f"填写或提交答案时出错: {e}")
            return False

    async def _write_answers_to_cache(self, breadcrumb_parts: list[str]):
        try:
            await self.driver_service._navigate_to_answer_analysis_page()
            correct_answers_list = await self.driver_service.extract_fill_in_the_blank_answers_from_analysis_page()

            if not correct_answers_list:
                logger.warning("未能从解析页面提取到任何答案，无法更新缓存。" )
                return
            
            self.cache_service.save_task_page_answers(
                breadcrumb_parts,
                self.strategy_type,
                correct_answers_list
            )

        except Exception as e:
            logger.error(f"写入缓存过程中发生错误: {e}")
