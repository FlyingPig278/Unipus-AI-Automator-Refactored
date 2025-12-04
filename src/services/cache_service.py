# src/services/cache_service.py
import json
import os
from src.utils import logger

class CacheService:
    """
    缓存服务类，用于管理AI答案的本地缓存。
    最终版：放弃哈希，直接按顺序存储答案数组，便于人工编辑。
    """
    def __init__(self, cache_file_path: str = "answer_cache.json"):
        self.cache_file_path = cache_file_path
        self.cache = self._load_cache()
        logger.info(f"缓存服务已初始化，使用文件: {self.cache_file_path}")

    def _load_cache(self) -> dict:
        """从文件加载缓存。"""
        if os.path.exists(self.cache_file_path):
            try:
                with open(self.cache_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content:
                        return {}
                    return json.loads(content)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"读取缓存文件 {self.cache_file_path} 时出错: {e}。将创建新的空缓存。")
                return {}
        return {}

    def _save_cache(self):
        """将缓存保存到文件。"""
        try:
            with open(self.cache_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"写入缓存文件 {self.cache_file_path} 时失败: {e}")

    def get_task_page_cache(self, breadcrumb_parts: list[str]) -> dict | None:
        """
        根据面包屑路径，获取整个任务页面的缓存数据。
        """
        current_level = self.cache
        for part in breadcrumb_parts:
            current_level = current_level.get(part)
            if current_level is None:
                return None
        return current_level

    def save_task_page_answers(self, breadcrumb_parts: list[str], strategy_type: str, answers_list: list[str]):
        """
        将一个任务页面的所有答案（一个字符串列表）作为一个整体存入缓存。

        Args:
            breadcrumb_parts (list[str]): 题目的面包屑路径。
            strategy_type (str): 该页面所有题目的类型。
            answers_list (list[str]): 包含所有答案字符串的列表。
        """
        current_level = self.cache
        for part in breadcrumb_parts:
            current_level = current_level.setdefault(part, {})
        
        # 构建新的、基于数组的缓存结构
        current_level['type'] = strategy_type
        current_level['answers'] = answers_list
        
        self._save_cache()
        logger.info(f"页面答案已按顺序整体保存到缓存路径: {' -> '.join(breadcrumb_parts)}")

    def clear_cache(self):
        """清除所有缓存。"""
        self.cache = {}
        self._save_cache()
        logger.info("缓存已清除。")