from src.strategies.base_strategy import BaseStrategy
from src.services.driver_service import DriverService
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from playwright.async_api import Error as PlaywrightError
from src.utils import logger

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
                logger.warning("检测到图片依赖型题目（如词云），此题目无法由AI解答。") # Changed to warning
                return True
        except PlaywrightError:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False, sub_task_index: int = -1) -> tuple[bool, bool]:
        logger.always_print("=" * 20)
        logger.always_print("执行“跳过图片题”策略...")
        logger.always_print("AI无法处理基于图片的题目，将中止当前任务以跳过。")
        logger.always_print("=" * 20)
        return False, False
