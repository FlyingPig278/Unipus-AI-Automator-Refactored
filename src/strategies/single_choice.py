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

class SingleChoiceStrategy(BaseStrategy):
    """
    单选题的处理策略。
    适用于页面上包含明确的A, B, C, D选项的题目。
    实现了“缓存优先，AI后备”的逻辑。
    """
    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "single_choice"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
       """检查当前页面是否为单选题。"""
       try:
           is_question_wrap_visible = await driver_service.page.locator("div.question-common-abs-choice:not(.multipleChoice)").first.is_visible(timeout=2000)
           is_option_wrap_visible = await driver_service.page.locator(".option-wrap").first.is_visible(timeout=2000)
           
           if is_question_wrap_visible and is_option_wrap_visible:
               logger.info("页面初步符合[单选题]特征，应用单选题策略。")
               return True
           return False
       except PlaywrightError:
           return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        logger.info("="*20)
        logger.info("开始执行单选题策略...")

        try:
            breadcrumb_parts = await self.driver_service.get_breadcrumb_parts()
            original_question_locators = await self.driver_service.page.locator(".question-common-abs-reply").all()
            if not breadcrumb_parts or not original_question_locators:
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
            if not config.FORCE_AI and task_page_cache and task_page_cache.get('type') == self.strategy_type:
                logger.info("在缓存中找到此页面的记录，正在校验...")
                cached_answers = task_page_cache.get('answers', [])
                if len(cached_answers) == len(original_question_locators):
                    use_cache = True
                    answers_to_fill = cached_answers
                else:
                    logger.warning("缓存答案数量与当前页面题目数量不匹配，将调用AI。")
            elif config.FORCE_AI:
                logger.info("FORCE_AI为True，强制忽略缓存，调用AI。")

        if use_cache:
            logger.info("所有题目均在缓存中找到答案，直接填写。")
        else:
            if is_chained_task:
                logger.info("处于“题中题”模式，跳过缓存，直接调用AI。")
            else:
                logger.info("缓存未命中或不完整，将调用AI进行解答...")
            
            cache_write_needed = not is_chained_task

            logger.info("正在并发提取文章、说明、题目等信息...")
            tasks = [
                self._get_article_text(),
                self._get_direction_text(),
                self.driver_service._extract_additional_material_for_ai()
            ]
            results = await asyncio.gather(*tasks)
            article_text, direction_text, additional_material = results
            logger.info("信息提取完毕。")

            question_texts = []
            for qw_locator in original_question_locators:
                title = await qw_locator.locator(".ques-title").text_content()
                
                options_text_parts = []
                option_locators = await qw_locator.locator(".option").all()
                for opt_loc in option_locators:
                    caption = await opt_loc.locator(".caption").text_content()
                    content_html = await opt_loc.locator(".content").inner_html()
                    processed_content = re.sub(r'<span style="text-decoration: underline;">(.*?)</span>', r'*\1*', content_html, flags=re.IGNORECASE | re.DOTALL)
                    processed_content = re.sub(r'<u>(.*?)</u>', r'*\1*', processed_content, flags=re.IGNORECASE | re.DOTALL)
                    processed_content = re.sub(r'<.*?>', '', processed_content)
                    processed_content = html.unescape(processed_content)
                    
                    options_text_parts.append(f"{caption.strip()}. {processed_content.strip()}")
                
                options_text = "\n".join(options_text_parts)
                full_text = f"{title.strip()}\n{options_text}"
                question_texts.append(full_text)

            full_questions_and_options_text = "\n\n".join(question_texts)
            combined_context = f"{shared_context}\n{article_text}"
            
            article_section = f"以下是文章或听力原文内容:\n{combined_context}\n\n" if combined_context.strip() else ""
            prompt = (
                f"{prompts.SINGLE_CHOICE_PROMPT}\n"
                f"以下是题目的说明:\n{direction_text}\n\n"
                f"{article_section}"
                f"{additional_material}\n"
                f"以下是题目和选项:\n{full_questions_and_options_text}"
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
            if not json_data or "questions" not in json_data:
                logger.error("未能从AI获取有效答案，终止执行。")
                return False

            logger.debug(f"AI回答: {json_data}")
            answers_to_fill = [str(item["answer"]).upper() for item in json_data.get("questions", []) if "answer" in item]

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
            option_wraps_locators = await self.driver_service.page.locator(".option-wrap").all()

            if len(answers) != len(option_wraps_locators):
                logger.error(f"收到的答案数量 ({len(answers)}) 与页面题目数量 ({len(option_wraps_locators)}) 不匹配，为避免错位，已终止此题作答。")
                return False

            is_valid = True
            for i, option_wrap_locator in enumerate(option_wraps_locators):
               answer_char = answers[i]
               options_count = await option_wrap_locator.locator(".option").count()
               answer_index = ord(answer_char) - ord("A")
               if not (0 <= answer_index < options_count):
                   logger.error(f"第 {i+1} 题的答案 '{answer_char}' 无效（选项范围是 A-{chr(ord('A')+options_count-1)}），已终止此题作答。")
                   is_valid = False
                   break

            if not is_valid:
               return False

            logger.info("预验证通过，开始填写答案...")
            for i, option_wrap_locator in enumerate(option_wraps_locators):
               answer_char = answers[i]
               answer_index = ord(answer_char) - ord("A")
               logger.info(f"第 {i+1} 题，选择选项: {answer_char}")
               await option_wrap_locator.locator(".option").nth(answer_index).click()

            logger.success("答案填写完毕。")

            if not is_chained_task:
                should_submit = True
                if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                    confirm = await asyncio.to_thread(input, "AI或缓存已选择答案。是否确认提交？[Y/n]: ")
                    if confirm.strip().upper() not in ["Y", ""]:
                        logger.warning("用户取消提交。")
                        should_submit = False
                
                if should_submit:
                    await self.driver_service.page.click(".btn")
                    await self.driver_service.handle_rate_limit_modal()
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
            extracted_analysis_answers = await self.driver_service.extract_all_correct_answers_from_analysis_page()

            if not extracted_analysis_answers:
                logger.warning("未能从解析页面提取到任何答案，无法更新缓存。" )
                return
            
            self.cache_service.save_task_page_answers(
                breadcrumb_parts,
                self.strategy_type,
                extracted_analysis_answers
            )

        except Exception as e:
            logger.error(f"写入缓存过程中发生错误: {e}")

