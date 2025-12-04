from abc import ABC, abstractmethod
from src.services.driver_service import DriverService
from src.services.ai_service import AIService
from src.utils import logger

class BaseStrategy(ABC):
    """
    策略模式的抽象基类。
    所有具体的题型处理策略都应继承此类，并实现其抽象方法。
    这确保了所有策略类都具有统一的接口，便于主程序调用。
    """

    @staticmethod
    @abstractmethod
    def check(driver_service: DriverService) -> bool:
        """
        检查当前页面是否适用于本策略。
        这是一个静态方法，因为它不需要策略实例即可被调用。

        Args:
            driver_service (DriverService): 封装了浏览器操作的服务实例。

        Returns:
            bool: 如果当前页面是此策略可以处理的题型，则返回True，否则返回False。
        """
        pass

    @abstractmethod
    def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        """
        执行本策略的核心逻辑。
        返回 True 表示成功完成（不包括提交，如果is_chained_task为True），
        返回 False 表示因故提前终止（如用户取消，内部错误等）。
        """
        pass

    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service):
        """
        初始化策略实例。

        Args:
            driver_service (DriverService): 浏览器服务实例。
            ai_service (AIService): AI服务实例。
            cache_service (CacheService): 缓存服务实例。
        """
        self.driver_service = driver_service
        self.ai_service = ai_service
        self.cache_service = cache_service

    async def _get_direction_text(self) -> str:
        """提取题目说明文字，使用短超时以避免不必要的等待。"""
        try:
            locator = self.driver_service.page.locator(".abs-direction")
            # 使用短暂超时，因为“说明”并非总是存在。
            if await locator.is_visible(timeout=1000):
                return await locator.text_content()
        except Exception:
            # 捕获超时或其他错误，静默处理
            pass
        logger.info("未找到题目说明（Direction）。")
        return ""
