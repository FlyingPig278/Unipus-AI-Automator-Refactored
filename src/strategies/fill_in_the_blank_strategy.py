import asyncio
import re
import html
from playwright.async_api import Error as PlaywrightError

from src import prompts, config
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_strategy import BaseStrategy


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
                print("检测到填空题，应用填空题策略。")
                return True
        except PlaywrightError:
            return False
        return False

    async def execute(self) -> None:
        """执行填空题的解题逻辑。"""
        print("="*20)
        print("开始执行填空题策略...")

        try:
            breadcrumb_parts = await self.driver_service.get_breadcrumb_parts()
            if not breadcrumb_parts:
                raise Exception("无法获取页面面包屑，终止策略。")
        except Exception as e:
            print(f"提取面包屑时出错: {e}")
            return

        cache_write_needed = False
        answers_to_fill = []

        task_page_cache = self.cache_service.get_task_page_cache(breadcrumb_parts)
        if not config.FORCE_AI and task_page_cache and task_page_cache.get('type') == self.strategy_type and task_page_cache.get('answers'):
            print("在缓存中找到此页面的答案。")
            answers_to_fill = task_page_cache.get('answers', [])
        elif config.FORCE_AI and task_page_cache:
            print("FORCE_AI为True，强制忽略缓存，调用AI。")
        
        if not answers_to_fill:
            print("缓存未命中，将调用AI进行解答...")
            cache_write_needed = True

            article_text = await self._get_article_text()
            direction_text = await self._get_direction_text()
            
            question_locator = self.driver_service.page.locator(".question-common-abs-reply")
            question_html = await question_locator.inner_html()
            
            # 增加HTML解码步骤
            unescaped_html = html.unescape(question_html)
            
            question_text_for_ai = re.sub(r'<span class="fe-scoop".*?</span>', ' ___ ', unescaped_html)
            question_text_for_ai = re.sub(r'<.*?>', '', question_text_for_ai).strip()

            prompt = prompts.FILL_IN_THE_BLANK_PROMPT.format(
                direction_text=direction_text,
                article_text=article_text,
                question_text=question_text_for_ai
            )

            print("=" * 50)
            print("即将发送给 AI 的完整 Prompt 如下：")
            print(prompt)
            print("=" * 50)
            confirm = await asyncio.to_thread(input, "是否确认发送此 Prompt？[Y/n]: ")
            if confirm.strip().upper() not in ["Y", ""]:
                print("用户取消了 AI 调用，终止当前任务。")
                return
            
            json_data = self.ai_service.get_chat_completion(prompt)
            if not json_data or "questions" not in json_data or not json_data["questions"]:
                raise Exception("未能从AI获取有效答案。")

            print(f"AI回答: {json_data}")
            answers_to_fill = json_data["questions"][0].get("answer", [])

        await self._fill_and_submit(answers_to_fill, cache_write_needed, breadcrumb_parts)

    async def _get_article_text(self) -> str:
        """提取文章或听力原文（音频或视频）。"""
        media_url, media_type = await self.driver_service.get_media_source_and_type()
        if media_url:
            print(f"发现 {media_type} 文件，准备转写...")
            try:
                article_text = self.ai_service.transcribe_media_from_url(media_url)
                if not article_text:
                    print("警告：媒体文件转写失败。")
                return article_text
            except Exception as e:
                print(f"媒体文件转写时发生错误: {e}")
                return ""
        try:
            article_locator = self.driver_service.page.locator(".comp-common-article-content")
            if await article_locator.is_visible():
                print("发现文章容器，正在提取文本...")
                return await article_locator.text_content()
        except PlaywrightError:
            pass
        
        print("未在本页找到可用的音频、视频或文章。")
        return ""

    async def _get_direction_text(self) -> str:
        """提取题目说明文字。"""
        try:
            return await self.driver_service.page.locator(".abs-direction").text_content()
        except PlaywrightError:
            print("未找到题目说明（Direction）。")
            return ""

    async def _fill_and_submit(self, answers: list[str], cache_write_needed: bool, breadcrumb_parts: list[str]):
        """将答案填入网页并提交。"""
        try:
            print("正在解析并预验证答案...")
            input_locators = await self.driver_service.page.locator(".fe-scoop .comp-abs-input input").all()

            if len(answers) != len(input_locators):
                print(f"错误：AI返回的答案数量 ({len(answers)}) 与页面输入框数量 ({len(input_locators)}) 不匹配，终止作答。")
                return

            print("预验证通过，开始填写答案...")
            for i, input_locator in enumerate(input_locators):
                answer_text = answers[i]
                print(f"第 {i+1} 个空，填入: '{answer_text}'")
                await input_locator.fill(answer_text)
                await asyncio.sleep(0.2)

            print("答案填写完毕。")

            confirm = await asyncio.to_thread(input, "AI或缓存已填写答案。是否确认提交？[Y/n]: ")
            if confirm.strip().upper() in ["Y", ""]:
                await self.driver_service.page.click(".btn")
                print("答案已提交。正在处理最终确认弹窗...")
                await self.driver_service.handle_submission_confirmation()
                if cache_write_needed:
                    print("准备从解析页面提取正确答案并写入缓存...")
                    await self._write_answers_to_cache(breadcrumb_parts)
            else:
                print("用户取消提交。")

        except Exception as e:
            print(f"填写或提交答案时出错: {e}")

    async def _write_answers_to_cache(self, breadcrumb_parts: list[str]):
        """导航到答案解析页面，提取正确答案，并写入缓存。"""
        try:
            await self.driver_service._navigate_to_answer_analysis_page()
            correct_answers_list = await self.driver_service.extract_all_correct_answers_from_analysis_page()

            if not correct_answers_list:
                print("警告：未能从解析页面提取到任何答案，无法更新缓存。" )
                return
            
            self.cache_service.save_task_page_answers(
                breadcrumb_parts,
                self.strategy_type,
                correct_answers_list
            )

        except Exception as e:
            print(f"写入缓存过程中发生错误: {e}")
