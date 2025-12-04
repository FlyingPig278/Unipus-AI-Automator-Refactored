import asyncio
from playwright.async_api import Error as PlaywrightError, expect
from src import prompts, config
from src.strategies.base_strategy import BaseStrategy
from src.services.driver_service import DriverService
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.utils import logger

class DiscussionStrategy(BaseStrategy):
    """
    处理“讨论区”任务的策略。
    提取主标题和子问题，请求AI生成评论，然后填入并发布。
    """

    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "discussion"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        """检查当前页面是否为讨论区任务。"""
        try:
            is_visible = await driver_service.page.locator(".discussion-cloud-reply").first.is_visible(timeout=2000)
            if is_visible:
                logger.info("检测到讨论区，应用讨论题策略。")
                return True
        except PlaywrightError:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False, sub_task_index: int = -1) -> tuple[bool, bool]:
        logger.info("=" * 20)
        logger.info("开始执行讨论题策略...")

        try:
            main_title_selector = ".discussion-title p"
            main_title = await self.driver_service.page.locator(main_title_selector).first.text_content(timeout=5000)
            main_title = main_title.strip()

            sub_questions_selector = ".question-common-abs-material .component-htmlview p"
            sub_question_locators = await self.driver_service.page.locator(sub_questions_selector).all()
            sub_questions = [await loc.text_content() for loc in sub_question_locators if (await loc.text_content()).strip()]
            sub_questions_text = "\n".join([f"- {q.strip()}" for i, q in enumerate(sub_questions)])
            
            logger.info(f"提取到主标题: {main_title}")
            logger.info(f"提取到 {len(sub_questions)} 个子问题:\n{sub_questions_text}")
            
            prompt = prompts.DISCUSSION_PROMPT.format(
                main_title=main_title,
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

            logger.info("正在请求AI生成评论...")
            ai_response = self.ai_service.get_chat_completion(prompt)
            
            if not ai_response or "answers" not in ai_response or not isinstance(ai_response["answers"], list):
                logger.error("未能从AI获取有效的答案列表，终止执行。")
                return False, False
            
            ai_answers = ai_response["answers"]
            if len(ai_answers) != len(sub_questions):
                logger.warning(f"AI返回了 {len(ai_answers)} 个答案，但我们提取了 {len(sub_questions)} 个问题，终止执行。")
                return False, False
            
            final_comment = ""
            for i, answer in enumerate(ai_answers):
                final_comment += f"{i + 1}. {answer}\n"
            
            logger.info(f"AI已生成结构化回答，将格式化为:\n{final_comment}")

            textarea_selector = "textarea.ant-input"
            await self.driver_service.page.locator(textarea_selector).fill(final_comment.strip())
            logger.success("评论已填入文本框。")

            if not is_chained_task:
                publish_button = self.driver_service.page.get_by_role("button", name="发 布")
                await expect(publish_button).to_be_enabled(timeout=5000)
                logger.debug("发布按钮已变为可点击状态。")

                await publish_button.click()
                await self.driver_service.handle_rate_limit_modal()
                logger.success("评论已发布。")
                
                await asyncio.sleep(2)
            
            return True, False

        except Exception as e:
            logger.error(f"执行讨论题策略时发生错误: {e}")
            return False, False

    async def close(self):
        pass
