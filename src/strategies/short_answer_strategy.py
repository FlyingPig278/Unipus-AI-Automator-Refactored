import asyncio

from playwright.async_api import Error as PlaywrightError

from src import prompts, config
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_strategy import BaseStrategy


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
                print("检测到简答题，应用简答题策略。")
                return True
        except PlaywrightError:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        """执行简答题的解题逻辑。"""
        print("="*20)
        print("开始执行简答题策略...")

        # 简答题不使用缓存，总是调用AI
        try:
            # 1. 使用 asyncio.gather 并发提取所有上下文信息
            print("正在并发提取文章、说明等信息...")
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
            
            # 检查是否为表格题型
            is_table_question = "|:---:" in additional_material

            if is_table_question:
                print("检测到表格题型，使用专用的表格Prompt。")
                prompt = prompts.TABLE_SHORT_ANSWER_PROMPT.format(
                    direction_text=direction_text,
                    article_text=full_context
                )
            else:
                print("使用标准简答题Prompt。")
                # 2. 提取所有子问题
                question_containers = await self.driver_service.page.locator(".question-inputbox").all()
                sub_questions = []
                for container in question_containers:
                    sub_q_text = await container.locator(".question-inputbox-header .component-htmlview").text_content()
                    sub_questions.append(sub_q_text.strip())
                
                sub_questions_text = "\n".join([f"{i+1}. {q}" for i, q in enumerate(sub_questions)])
                print(f"提取到 {len(sub_questions)} 个简答题:\n{sub_questions_text}")

                # 3. 构建Prompt
                article_section = f"以下是文章或听力原文内容:\n{full_context}\n\n" if full_context else ""
                prompt = prompts.SHORT_ANSWER_PROMPT.format(
                    direction_text=direction_text,
                    article_text=article_section,
                    sub_questions=sub_questions_text
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
            if not json_data or "answers" not in json_data or not isinstance(json_data["answers"], list):
                print("未能从AI获取有效的答案列表。")
                return False

            answers_to_fill = json_data["answers"]
            print(f"AI已生成 {len(answers_to_fill)} 个回答。")

            # 4. 填写并提交
            return await self._fill_and_submit(answers_to_fill, is_chained_task=is_chained_task)

        except Exception as e:
            print(f"执行简答题策略时发生错误: {e}")
            return False

    async def _get_article_text(self) -> str:
        """提取文章或听力原文。"""
        # (这个方法的实现可以和其它策略复用)
        try:
            media_url, media_type = await self.driver_service.get_media_source_and_type()
            if media_url:
                return self.ai_service.transcribe_media_from_url(media_url)
            
            article_locator = self.driver_service.page.locator(".comp-common-article-content")
            if await article_locator.is_visible():
                return await article_locator.text_content()
        except Exception:
            pass
        return ""

    async def _fill_and_submit(self, answers: list[str], is_chained_task: bool = False) -> bool:
        """将答案填入所有文本框并提交。"""
        try:
            textarea_locators = await self.driver_service.page.locator("textarea.question-inputbox-input").all()

            if len(answers) != len(textarea_locators):
                print(f"错误：AI返回的答案数量 ({len(answers)}) 与页面输入框数量 ({len(textarea_locators)}) 不匹配，终止作答。")
                return False

            print("开始填写答案...")
            for i, textarea_locator in enumerate(textarea_locators):
                answer_text = answers[i]
                print(f"第 {i+1} 题，填入: '{answer_text[:50]}...'")
                await textarea_locator.fill(answer_text)
                await asyncio.sleep(0.2)

            print("答案填写完毕。")

            # 如果不是“题中题”的一部分，则执行提交流程
            if not is_chained_task:
                should_submit = True
                if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                    confirm = await asyncio.to_thread(input, "AI已填写答案。是否确认提交？[Y/n]: ")
                    if confirm.strip().upper() not in ["Y", ""]:
                        should_submit = False
                
                if should_submit:
                    await self.driver_service.page.click(".btn")
                    print("答案已提交。正在处理最终确认弹窗...")
                    await self.driver_service.handle_submission_confirmation()
                    return True
                else:
                    print("用户取消提交。")
                    return False
            else:
                return True
        except Exception as e:
            print(f"填写或提交答案时出错: {e}")
            return False

    async def close(self) -> None:
        pass
