import asyncio
from src.strategies.base_strategy import BaseStrategy
from src.services.driver_service import DriverService
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.utils import logger

class CheckboxStrategy(BaseStrategy):
    """
    处理“Exit Ticket”自检打钩页面的策略。
    """

    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "checkbox_self_check"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        """检查当前页面是否为“Exit Ticket”自检页面。"""
        try:
            is_visible = await driver_service.page.locator(".ticket-view").first.is_visible(timeout=2000)
            if is_visible:
                logger.info("检测到 'Exit Ticket' 页面，应用自检打钩策略。")
                return True
        except Exception:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False, sub_task_index: int = -1) -> tuple[bool, bool]:
        logger.info("=" * 20)
        logger.info("开始执行自检打钩策略...")

        unchecked_boxes_selector = ".anticon [data-icon='border']"
        
        try:
            initial_count = await self.driver_service.page.locator(unchecked_boxes_selector).count()
            if initial_count == 0:
                logger.info("没有检测到未打钩的项，可能已经全部完成。")
                return True, False
            
            logger.info(f"发现 {initial_count} 个未打钩的项，正在逐一点击...")
            clicked_count = 0

            while await self.driver_service.page.locator(unchecked_boxes_selector).count() > 0:
                await self.driver_service.page.locator(unchecked_boxes_selector).first.click()
                clicked_count += 1
                logger.debug(f"已点击第 {clicked_count} 个未打钩项。")
                await asyncio.sleep(0.5)

            logger.success(f"所有 {clicked_count} 个未打钩项已全部点击完毕。")
            return True, False

        except Exception as e:
            logger.error(f"执行自检打钩策略时发生错误: {e}")
            return False, False
