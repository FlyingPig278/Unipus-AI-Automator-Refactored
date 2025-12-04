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


class MultipleChoiceStrategy(BaseStrategy):
    """
    多选题的处理策略。
    假设一个页面只有一个多选题。
    """
    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "multiple_choice"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
       """检查当前页面是否为多选题。"""
       try:
           is_question_wrap_visible = await driver_service.page.locator("div.question-common-abs-choice.multipleChoice").first.is_visible(timeout=2000)
           is_option_wrap_visible = await driver_service.page.locator(".option-wrap").first.is_visible(timeout=2000)
           
           if is_question_wrap_visible and is_option_wrap_visible:
               logger.info("页面初步符合[多选题]特征，应用多选题策略。")
               return True
           return False
       except PlaywrightError:
           return False

    async def _get_full_question_text_for_ai(self, question_wrap_locator) -> str:
        """从题目区块中提取完整的题目和选项文本，并处理下划线。"""
        title = await question_wrap_locator.locator(".ques-title").text_content()
        
        options_text_parts = []
        option_locators = await question_wrap_locator.locator(".option").all()
        for opt_loc in option_locators:
            caption = await opt_loc.locator(".caption").text_content()
            content_html = await opt_loc.locator(".content").inner_html()
            
            processed_content = re.sub(r'<span style="text-decoration: underline;">(.*?)</span>', r'*\1*', content_html, flags=re.IGNORECASE | re.DOTALL)
            processed_content = re.sub(r'<u>(.*?)</u>', r'*\1*', processed_content, flags=re.IGNORECASE | re.DOTALL)
            
            processed_content = re.sub(r'<.*?>', '', processed_content)
            processed_content = html.unescape(processed_content)
            
            options_text_parts.append(f"{caption.strip()}. {processed_content.strip()}")
        
        options_text = "\n".join(options_text_parts)
        return f"{title.strip()}\n{options_text}"

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        logger.info("="*20)
        logger.info("开始执行多选题策略...")

        try:
            breadcrumb_parts = await self.driver_service.get_breadcrumb_parts()
            question_locator = self.driver_service.page.locator("div.question-common-abs-choice.multipleChoice").first
            if not breadcrumb_parts or not await question_locator.is_visible():
                logger.error("无法获取页面关键信息（面包屑或题目），终止策略。")
                return False
        except Exception as e:
            logger.error(f"提取面包屑或题目容器时出错: {e}")
            return False

        cache_write_needed = False
        answers_to_fill = [] 
        use_cache = False

        if not is_chained_task:
            task_page_cache = self.cache_service.get_task_page_cache(breadcrumb_parts)
            if not config.FORCE_AI and task_page_cache and task_page_cache.get('type') == self.strategy_type and task_page_cache.get('answers'):
                logger.info("在缓存中找到此页面的答案。")
                answers_to_fill = task_page_cache['answers']
                use_cache = True
            elif config.FORCE_AI and task_page_cache:
                logger.info("FORCE_AI为True，强制忽略缓存，调用AI。")
        
        if not use_cache:
            if is_chained_task:
                logger.info("处于“题中题”模式，跳过缓存，直接调用AI。")
            else:
                logger.info("缓存未命中，将调用AI进行解答...")
            
            cache_write_needed = not is_chained_task

            logger.info("正在并发提取文章、说明、题目等信息...")
            tasks = [
                self._get_article_text(),
                self.driver_service._extract_additional_material_for_ai(),
                self._get_full_question_text_for_ai(question_locator)
            ]
            results = await asyncio.gather(*tasks)
            article_text, additional_material, question_text = results
            # 多选题的 direction_text 和 question_text 是一样的，所以不需要单独获取
            direction_text = question_text
            logger.info("信息提取完毕。")

            combined_context = f"{shared_context}\n{article_text}"

            article_section = f"以下是文章内容:\n{combined_context}\n\n" if combined_context.strip() else ""
            prompt = (
                f"{prompts.MULTIPLE_CHOICE_PROMPT}\n"
                f"以下是题目的说明:\n{direction_text}\n\n"
                f"{article_section}"
                f"{additional_material}\n"
                f"以下是题目和选项:\n{question_text}"
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
                logger.error("未能从AI获取有效答案，终止执行。")
                return False

            logger.debug(f"AI回答: {json_data}")
            answers_to_fill = [str(char).upper() for char in json_data["questions"][0].get("answer", [])]

        return await self._fill_and_submit(answers_to_fill, cache_write_needed, breadcrumb_parts, is_chained_task=is_chained_task)

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

    async def _fill_and_submit(self, answers: list[str], cache_write_needed: bool, breadcrumb_parts: list[str], is_chained_task: bool = False) -> bool:
        try:
            logger.debug("正在解析并预验证答案...")
            option_wrap_locator = self.driver_service.page.locator("div.question-common-abs-choice.multipleChoice .option-wrap").first

            options_count = await option_wrap_locator.locator(".option").count()
            
            is_valid = True
            for answer_char in answers: 
                answer_index = ord(answer_char) - ord("A")
                if not (0 <= answer_index < options_count):
                    logger.error(f"答案 '{answer_char}' 无效，已终止作答。")
                    is_valid = False
                    break
            
            if not is_valid:
                return False

            logger.info("预验证通过，开始填写答案...")
            for answer_char in answers:
                answer_index = ord(answer_char) - ord("A")
                logger.info(f"选择选项: {answer_char}")
                await option_wrap_locator.locator(".option").nth(answer_index).click()
                await asyncio.sleep(0.2)

            logger.success("答案填写完毕。")

            if not is_chained_task:
                should_submit = True
                if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                    confirm = await asyncio.to_thread(input, "AI或缓存已更新答案顺序。是否确认提交？[Y/n]: ")
                    if confirm.strip().upper() not in ["Y", ""]:
                        logger.warning("用户取消提交。")
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
                    return False
            else:
                return True

        except Exception as e:
            logger.error(f"填写或提交答案时出错: {e}")
            return False

    async def _write_answers_to_cache(self, breadcrumb_parts: list[str]):
        try:
            await self.driver_service._navigate_to_answer_analysis_page()
            correct_answers_list = await self.driver_service.extract_all_correct_answers_from_analysis_page()

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
