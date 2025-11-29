import asyncio
from playwright.async_api import Error as PlaywrightError

from src import prompts, config
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_strategy import BaseStrategy


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
               print("页面初步符合[多选题]特征，应用多选题策略。")
               return True
           return False
       except PlaywrightError:
           return False

    async def _get_full_question_text_for_ai(self, question_wrap_locator) -> str:
        """从题目区块中提取完整的题目和选项文本。"""
        return await question_wrap_locator.text_content()

    async def execute(self) -> None:
        """执行多选题的解题逻辑。"""
        print("="*20)
        print("开始执行多选题策略...")

        try:
            breadcrumb_parts = await self.driver_service.get_breadcrumb_parts()
            question_locator = self.driver_service.page.locator("div.question-common-abs-choice.multipleChoice").first
            if not breadcrumb_parts or not await question_locator.is_visible():
                print("错误：无法获取页面关键信息（面包屑或题目），终止策略。")
                return
        except Exception as e:
            print(f"提取面包屑或题目容器时出错: {e}")
            return

        cache_write_needed = False
        answers_to_fill = [] # 这将是一个 list[str]，例如 ['A', 'C']

        task_page_cache = self.cache_service.get_task_page_cache(breadcrumb_parts)
        if task_page_cache and task_page_cache.get('type') == self.strategy_type:
            print("在缓存中找到此页面的答案。")
            answers_to_fill = task_page_cache.get('answers', [])
        
        if not answers_to_fill:
            print("缓存未命中，将调用AI进行解答...")
            cache_write_needed = True

            article_text = await self._get_article_text()
            direction_text = await self._get_direction_text()
            question_text = await self._get_full_question_text_for_ai(question_locator)

            article_section = f"以下是文章内容:\n{article_text}\n\n" if article_text else ""
            prompt = (
                f"{prompts.MULTIPLE_CHOICE_PROMPT}\n"
                f"以下是题目的说明:\n{direction_text}\n\n"
                f"{article_section}"
                f"以下是题目和选项:\n{question_text}"
            )
            
            print("按回车键继续以调用AI...")
            await asyncio.to_thread(input)
            
            json_data = self.ai_service.get_chat_completion(prompt)
            if not json_data or "questions" not in json_data or not json_data["questions"]:
                print("未能从AI获取有效答案，终止执行。")
                return

            print(f"AI回答: {json_data}")
            # AI为单个题目返回一个答案列表
            answers_to_fill = [str(char).upper() for char in json_data["questions"][0].get("answer", [])]

        await self._fill_and_submit(answers_to_fill, cache_write_needed, breadcrumb_parts)

    async def _get_article_text(self) -> str:
        """提取文章或听力原文（音频或视频）。"""
        media_url, media_type = await self.driver_service.get_media_source_and_type()
        if media_url:
            print(f"发现 {media_type} 文件，准备转写: {media_url}")
            try:
                article_text = self.ai_service.transcribe_media_from_url(media_url)
                if not article_text:
                    print("警告：媒体文件转写失败。")
                return article_text
            except Exception as e:
                print(f"媒体文件转写时发生错误: {e}")
                return ""
        print("未在本页找到可用的音频或视频文件。")
        return ""

    async def _get_direction_text(self) -> str:
        """提取题目说明文字。"""
        try:
            return await self.driver_service.page.locator(".abs-direction").text_content()
        except Exception:
            print("未找到题目说明（Direction）。")
            return ""

    async def _fill_and_submit(self, answers: list[str], cache_write_needed: bool, breadcrumb_parts: list[str]):
        """将答案填入网页并提交。"""
        try:
            print("正在解析并预验证答案...")
            # 只有一个题目，所以直接定位它的option-wrap
            option_wrap_locator = self.driver_service.page.locator("div.question-common-abs-choice.multipleChoice .option-wrap").first

            options_count = await option_wrap_locator.locator(".option").count()
            # answers 现在直接是 list[str]，无需再循环外层
            for answer_char in answers: # 遍历答案中的每个选项，例如 ['A', 'C']
                answer_index = ord(answer_char) - ord("A")
                if not (0 <= answer_index < options_count):
                    print(f"错误：答案 '{answer_char}' 无效，已终止作答。")
                    return

            print("预验证通过，开始填写答案...")
            for answer_char in answers:
                answer_index = ord(answer_char) - ord("A")
                print(f"选择选项: {answer_char}")
                await option_wrap_locator.locator(".option").nth(answer_index).click()
                await asyncio.sleep(0.2) # 增加点击间隔

            print("答案填写完毕。")

            confirm = await asyncio.to_thread(input, "AI或缓存已选择答案。是否确认提交？[Y/n]: ")
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
            # extract_all_correct_answers_from_analysis_page 现在直接返回 list[str]
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
