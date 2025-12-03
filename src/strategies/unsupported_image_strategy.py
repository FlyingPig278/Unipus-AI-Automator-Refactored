from src.strategies.base_strategy import BaseStrategy
from src.services.driver_service import DriverService
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from playwright.async_api import Error as PlaywrightError

class UnsupportedImageStrategy(BaseStrategy):
    """
    一个特殊的“防御性”策略，用于识别并跳过那些严重依赖图片信息、
    当前AI模型无法解答的题目（例如词云、图表分析等）。
    它的优先级应该最高，以确保在其他策略尝试解答之前拦截这些题目。
    """

    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "unsupported_image_question"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        """
        通过查找特定的图片容器元素来检查当前页面是否为图片依赖性题目。
        """
        try:
            # 使用用户提供的选择器来定位图片容器
            image_container_locator = driver_service.page.locator("div.html_image_list[data-type='options_images_tmls']")
            if await image_container_locator.count() > 0:
                print("检测到图片依赖型题目（如词云），此题目无法由AI解答。")
                return True
        except PlaywrightError:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        """
        执行跳过逻辑：打印通知并返回False，以中止当前任务。
        """
        print("=" * 20)
        print("执行“跳过图片题”策略...")
        print("AI无法处理基于图片的题目，将中止当前任务以跳过。")
        print("=" * 20)
        # 返回False，向主循环表明此任务不应继续或提交。
        return False
