# src/strategies/base_strategy.py
from abc import ABC, abstractmethod
from src.services.driver_service import DriverService
from src.services.ai_service import AIService

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
    def execute(self) -> None:
        """
        执行本策略的核心逻辑，包括：
        1. 从页面提取题目信息。
        2. 构建并发送Prompt给AI服务。
        3. 解析AI返回的答案。
        4. 将答案填入网页并提交。
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
