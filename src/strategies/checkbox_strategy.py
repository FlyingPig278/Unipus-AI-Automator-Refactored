import asyncio
from src.strategies.base_strategy import BaseStrategy
from src.services.driver_service import DriverService
from src.services.ai_service import AIService
from src.services.cache_service import CacheService

class CheckboxStrategy(BaseStrategy):
    """
    处理“Exit Ticket”自检打钩页面的策略。
    """

    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "checkbox_self_check"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        """
        检查当前页面是否为“Exit Ticket”自检页面。
        通过查找核心容器 .ticket-view 来判断。
        """
        try:
            is_visible = await driver_service.page.locator(".ticket-view").first.is_visible(timeout=2000)
            if is_visible:
                print("检测到 'Exit Ticket' 页面，应用自检打钩策略。")
                return True
        except Exception:
            return False
        return False

    async def execute(self) -> None:
        """
        执行自检打钩逻辑：循环查找第一个未打钩的项并点击，直到全部完成。
        """
        print("=" * 20)
        print("开始执行自检打钩策略...")

        unchecked_boxes_selector = ".anticon [data-icon='border']"
        
        try:
            # 首先计算总共有多少个未勾选的项，用于日志记录
            initial_count = await self.driver_service.page.locator(unchecked_boxes_selector).count()
            if initial_count == 0:
                print("没有检测到未打钩的项，可能已经全部完成。")
                return
            
            print(f"发现 {initial_count} 个未打钩的项，正在逐一点击...")
            clicked_count = 0

            # 使用while循环和.first定位器来处理动态变化的元素列表
            while await self.driver_service.page.locator(unchecked_boxes_selector).count() > 0:
                # 每次循环都定位到当前第一个未勾选的框
                await self.driver_service.page.locator(unchecked_boxes_selector).first.click()
                clicked_count += 1
                print(f"已点击第 {clicked_count} 个未打钩项。")
                # 等待一个短暂的间隔，让页面有时间反应
                await asyncio.sleep(0.5)

            print(f"✅ 所有 {clicked_count} 个未打钩项已全部点击完毕。")

        except Exception as e:
            print(f"执行自检打钩策略时发生错误: {e}")
