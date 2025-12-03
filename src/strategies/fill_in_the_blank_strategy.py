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

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        """执行填空题的解题逻辑，根据is_chained_task标志决定是否使用缓存。
        返回 True 表示成功完成（不包括提交，如果is_chained_task为True），
        返回 False 表示因故提前终止（如用户取消，内部错误等）。
        """
        print("=" * 20)
        print("开始执行填空题策略...")

        try:
            breadcrumb_parts = await self.driver_service.get_breadcrumb_parts()
            if not breadcrumb_parts:
                print("错误：无法获取页面面包屑，终止策略。")
                return False
        except Exception as e:
            print(f"提取面包屑时出错: {e}")
            return False

        cache_write_needed = False
        answers_to_fill = []
        use_cache = False

        # 1. 检查缓存（仅当不是“题中题”模式时）
        if not is_chained_task:
            task_page_cache = self.cache_service.get_task_page_cache(breadcrumb_parts)
            if not config.FORCE_AI and task_page_cache and task_page_cache.get(
                    'type') == self.strategy_type and task_page_cache.get('answers'):
                print("在缓存中找到此页面的答案。")
                answers_to_fill = task_page_cache.get('answers', [])
                use_cache = True
            elif config.FORCE_AI and task_page_cache:
                print("FORCE_AI为True，强制忽略缓存，调用AI。")

        # 2. 根据缓存情况决定下一步
        if use_cache:
            print("所有题目均在缓存中找到答案，直接填写。")
        else:
            if is_chained_task:
                print("处于“题中题”模式，跳过缓存，直接调用AI。")
            else:
                print("缓存未命中，将调用AI进行解答...")

            cache_write_needed = not is_chained_task  # 只有在非题中题模式下才写真正的缓存

            # 使用 asyncio.gather 并发执行所有独立的异步信息提取任务
            print("正在并发提取文章、说明、题目等信息...")
            tasks = [
                self._get_article_text(),
                self.driver_service._extract_additional_material_for_ai(),
                self._get_direction_text()
            ]
            results = await asyncio.gather(*tasks)
            article_text, additional_material, direction_text = results
            print("信息提取完毕。")

            # 将共享上下文和本地上下文结合
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
                print("=" * 50)
                print("即将发送给 AI 的完整 Prompt 如下：")
                print(prompt)
                print("=" * 50)

            if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                confirm = await asyncio.to_thread(input, "是否确认发送此 Prompt？[Y/n]: ")
                if confirm.strip().upper() not in ["Y", ""]:
                    print("用户取消了 AI 调用，终止当前任务。")
                    return False

            json_data = self.ai_service.get_chat_completion(prompt)
            if not json_data or "questions" not in json_data or not json_data["questions"]:
                print("未能从AI获取有效答案。")
                return False

            print(f"AI回答: {json_data}")
            answers_to_fill = json_data["questions"][0].get("answer", [])

        return await self._fill_and_submit(answers_to_fill, cache_write_needed, breadcrumb_parts,is_chained_task=is_chained_task)

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

    async def _fill_and_submit(self, answers: list[str], cache_write_needed: bool, breadcrumb_parts: list[str],
                               is_chained_task: bool = False) -> bool:
        """将答案填入网页。如果不是“题中题”模式，则同时处理提交。
        返回 True 表示成功完成（包括提交，如果非题中题），返回 False 表示因故提前终止。
        """
        try:
            print("正在解析并预验证答案...")
            input_locators = await self.driver_service.page.locator(".fe-scoop .comp-abs-input input").all()

            if len(answers) != len(input_locators):
                print(
                    f"错误：AI返回的答案数量 ({len(answers)}) 与页面输入框数量 ({len(input_locators)}) 不匹配，终止作答。")
                return False

            print("预验证通过，开始填写答案...")
            for i, input_locator in enumerate(input_locators):
                answer_text = answers[i]
                print(f"第 {i + 1} 个空，填入: '{answer_text}'")
                await input_locator.fill(answer_text)
                await asyncio.sleep(0.2)

            print("答案填写完毕。")

            # 如果不是“题中题”的一部分，则执行提交流程
            if not is_chained_task:
                should_submit = True
                if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                    confirm = await asyncio.to_thread(input, "AI或缓存已填写答案。是否确认提交？[Y/n]: ")
                    if confirm.strip().upper() not in ["Y", ""]:
                        should_submit = False
                
                if should_submit:
                    await self.driver_service.page.click(".btn")
                    print("答案已提交。正在处理最终确认弹窗...")
                    await self.driver_service.handle_submission_confirmation()
                    if cache_write_needed:
                        print("准备从解析页面提取正确答案并写入缓存...")
                        await self._write_answers_to_cache(breadcrumb_parts)
                    return True  # 提交成功
                else:
                    print("用户取消提交。")
                    return False  # 用户取消
            else:
                return True  # 在题中题模式下，填写成功即视为成功

        except Exception as e:
            print(f"填写或提交答案时出错: {e}")
            return False  # 填写或提交失败

    async def _write_answers_to_cache(self, breadcrumb_parts: list[str]):
        """导航到答案解析页面，提取正确答案，并写入缓存。"""
        try:
            await self.driver_service._navigate_to_answer_analysis_page()
            correct_answers_list = await self.driver_service.extract_fill_in_the_blank_answers_from_analysis_page()

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
