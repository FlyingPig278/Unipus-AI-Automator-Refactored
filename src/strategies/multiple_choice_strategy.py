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
    适用于页面上包含明确的A, B, C, D...选项，且可以多选的题目。
    实现了“缓存优先，AI后备”的逻辑。
    """
    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "multiple_choice"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
       """检查当前页面是否为多选题。"""
       try:
           # 检查是否存在question-common-abs-choice，且包含multipleChoice类
           is_question_wrap_visible = await driver_service.page.locator("div.question-common-abs-choice.multipleChoice").first.is_visible(timeout=2000)
           is_option_wrap_visible = await driver_service.page.locator(".option-wrap").first.is_visible(timeout=2000) # 确保有选项包裹器
           
           if is_question_wrap_visible and is_option_wrap_visible:
               print("页面初步符合[多选题]特征，应用多选题策略。")
               return True
           return False
       except PlaywrightError:
           return False

    async def _get_full_question_text_for_ai(self, question_wrap_locator) -> str:
        """
        从单个题目区块中提取完整的题目和选项文本，用于AI Prompt。
        """
        return await question_wrap_locator.text_content()

    async def execute(self) -> None:
        """执行多选题的解题逻辑，优先从缓存中查找答案（数组模式）。"""
        print("="*20)
        print("开始执行多选题策略...")

        try:
            breadcrumb_parts = await self.driver_service.get_breadcrumb_parts()
            original_question_locators = await self.driver_service.page.locator("div.question-common-abs-choice.multipleChoice").all() # 定位所有多选题块
            if not breadcrumb_parts or not original_question_locators:
                print("错误：无法获取页面关键信息（面包屑或题目），终止策略。")
                return
        except Exception as e:
            print(f"提取面包屑或题目容器时出错: {e}")
            return

        cache_write_needed = False
        answers_to_fill = []

        # 1. 一次性获取整个页面的缓存
        task_page_cache = self.cache_service.get_task_page_cache(breadcrumb_parts)
        
        use_cache = False
        if task_page_cache and task_page_cache.get('type') == self.strategy_type:
            print("在缓存中找到此页面的记录，正在校验...")
            cached_answers = task_page_cache.get('answers', [])
            if len(cached_answers) == len(original_question_locators):
                use_cache = True
                answers_to_fill = cached_answers
            else:
                print("缓存答案数量与当前页面题目数量不匹配，将调用AI。")

        # 2. 根据缓存情况决定下一步
        if use_cache:
            print("所有题目均在缓存中找到答案，直接填写。" )
        else:
            print("缓存未命中或不完整，将调用AI进行解答...")
            cache_write_needed = True

            # --- AI后备逻辑 ---
            article_text = await self._get_article_text()
            direction_text = await self._get_direction_text()
            
            question_texts = []
            for qw_locator in original_question_locators:
                question_texts.append(await self._get_full_question_text_for_ai(qw_locator))
            full_questions_and_options_text = "\n".join(question_texts)

            article_section = f"以下是文章内容:\n{article_text}\n\n" if article_text else ""
            prompt = (
                f"{prompts.MULTIPLE_CHOICE_PROMPT}\n" # 使用多选题的Prompt
                f"以下是题目的说明:\n{direction_text}\n\n"
                f"{article_section}"
                f"以下是题目和选项:\n{full_questions_and_options_text}"
            )
            
            print("按回车键继续以调用AI...")
            await asyncio.to_thread(input)
            
            json_data = self.ai_service.get_chat_completion(prompt)
            if not json_data or "questions" not in json_data:
                print("未能从AI获取有效答案，终止执行。" )
                return

            print(f"AI回答: {json_data}")
            # 对于多选题，AI应返回一个包含列表的列表，例如: [['A', 'C'], ['B']]
            answers_to_fill = [
                [str(char).upper() for char in item["answer"]] 
                for item in json_data.get("questions", []) if "answer" in item and isinstance(item["answer"], list)
            ]

        # 3. 统一执行填写和提交流程
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

    async def _fill_and_submit(self, answers: list[list[str]], cache_write_needed: bool, breadcrumb_parts: list[str]):
        """将答案填入网页并提交。在操作前执行严格的预验证。"""
        try:
            print("正在解析并预验证答案...")
            option_wraps_locators = await self.driver_service.page.locator(".option-wrap").all()

            if len(answers) != len(option_wraps_locators):
                print(f"错误：收到的答案数量 ({len(answers)}) 与页面题目数量 ({len(option_wraps_locators)}) 不匹配，为避免错位，已终止此题作答。")
                return

            is_valid = True
            for i, option_wrap_locator in enumerate(option_wraps_locators):
               current_q_answers = answers[i] # 可能是 ['A', 'C']
               options_count = await option_wrap_locator.locator(".option").count()
               
               for answer_char in current_q_answers:
                   answer_index = ord(answer_char) - ord("A")
                   if not (0 <= answer_index < options_count):
                       print(f"错误：第 {i+1} 题的答案 '{answer_char}' 无效（选项范围是 A-{chr(ord('A')+options_count-1)}），已终止此题作答。")
                       is_valid = False
                       break
               if not is_valid:
                   break

            if not is_valid:
               return

            print("预验证通过，开始填写答案...")
            for i, option_wrap_locator in enumerate(option_wraps_locators):
               current_q_answers = answers[i]
               for answer_char in current_q_answers:
                   answer_index = ord(answer_char) - ord("A")
                   print(f"第 {i+1} 题，选择选项: {answer_char}")
                   await option_wrap_locator.locator(".option").nth(answer_index).click()

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
        """导航到答案解析页面，提取正确答案，并作为一个简单的列表写入缓存。"""
        try:
            await self.driver_service._navigate_to_answer_analysis_page()
            extracted_analysis_answers = await self.driver_service.extract_all_correct_answers_from_analysis_page()

            if not extracted_analysis_answers:
                print("警告：未能从解析页面提取到任何答案，无法更新缓存。" )
                return

            # 对于多选题，需要存储一个包含列表的列表
            correct_answers_list = [item['correct_answer'] for item in extracted_analysis_answers]
            
            self.cache_service.save_task_page_answers(
                breadcrumb_parts,
                self.strategy_type,
                correct_answers_list
            )

        except Exception as e:
            print(f"写入缓存过程中发生错误: {e}")
