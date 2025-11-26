# src/services/cache_service.py
import json
import os
import hashlib

class CacheService:
    """
    缓存服务类，用于管理AI答案的本地缓存。
    使用“精简后”的哈希值作为键，以优化存储和可读性。
    """
    def __init__(self, cache_file_path: str = "answer_cache.json"):
        self.cache_file_path = cache_file_path
        self.cache = self._load_cache()
        print(f"缓存服务已初始化，使用文件: {self.cache_file_path}")

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
                print(f"警告：读取缓存文件 {self.cache_file_path} 时出错: {e}。将创建新的空缓存。")
                return {}
        return {}

    def _save_cache(self):
        """将缓存保存到文件。"""
        try:
            with open(self.cache_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"错误：写入缓存文件 {self.cache_file_path} 时失败: {e}")

    def _generate_question_hash(self, question_text: str) -> str:
        """
        为题目文本生成一个精简的SHA256哈希值（前16位）。
        """
        full_hash = hashlib.sha256(question_text.encode('utf-8')).hexdigest()
        return full_hash[:16] # 截取前16位作为精简哈希

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

    def save_task_page_answers(self, breadcrumb_parts: list[str], strategy_type: str, answers_data: list[dict]):
        """
        将一个任务页面的所有答案作为一个整体存入缓存。

        Args:
            breadcrumb_parts (list[str]): 题目的面包屑路径。
            strategy_type (str): 该页面所有题目的类型。
            answers_data (list[dict]): 一个字典列表，每个字典包含 'question_text' 和 'correct_answer'。
        """
        current_level = self.cache
        for part in breadcrumb_parts:
            current_level = current_level.setdefault(part, {})
        
        # 构建 questions 节点
        questions_node = {}
        for item in answers_data:
            question_text = item['question_text']
            correct_answer = item['correct_answer']
            
            # 使用精简哈希作为键
            question_hash = self._generate_question_hash(question_text)
            questions_node[question_hash] = {"answer": correct_answer}
            
        # 构建新的缓存结构
        current_level['type'] = strategy_type
        current_level.setdefault('questions', {}).update(questions_node)
        
        self._save_cache()
        print(f"页面答案已整体保存到缓存路径: {' -> '.join(breadcrumb_parts)}")

    def clear_cache(self):
        """清除所有缓存。"""
        self.cache = {}
        self._save_cache()
        print("缓存已清除。")
