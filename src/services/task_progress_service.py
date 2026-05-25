import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils import logger


class TaskProgressService:
    """Persist per-account, per-course task queues for resume support."""

    def __init__(self, cache_file_path: str = ".runtime/task_queues.json"):
        self.cache_file_path = Path(cache_file_path)
        self.cache_file_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache = self._load_cache()

    def get_course_id(self, username: str | None, course_name: str) -> str:
        raw_key = f"{username or 'unknown'}::{course_name}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, raw_key))

    def get_course_record(self, username: str | None, course_name: str) -> dict[str, Any] | None:
        course_id = self.get_course_id(username, course_name)
        return self.cache.get("courses", {}).get(course_id)

    def save_queue(self, username: str | None, course_name: str, tasks: list[dict[str, Any]]):
        course_id = self.get_course_id(username, course_name)
        courses = self.cache.setdefault("courses", {})
        existing = courses.get(course_id, {})
        now = datetime.now().isoformat(timespec="seconds")

        courses[course_id] = {
            **existing,
            "course_id": course_id,
            "course_name": course_name,
            "queue": tasks,
            "updated_at": now,
            "created_at": existing.get("created_at", now),
        }
        self._save_cache()
        logger.info(f"已保存课程任务队列缓存：{course_name}，剩余 {len(tasks)} 个任务。")

    def refresh_course_url(self, tasks: list[dict[str, Any]], course_url: str) -> list[dict[str, Any]]:
        refreshed = []
        for task in tasks:
            updated_task = dict(task)
            updated_task["course_url"] = course_url
            refreshed.append(updated_task)
        return refreshed

    def mark_task_finished(self, username: str | None, course_name: str, finished_task: dict[str, Any]):
        record = self.get_course_record(username, course_name)
        if not record:
            return

        original_queue = record.get("queue", [])
        new_queue = [
            task for task in original_queue
            if not self._same_task(task, finished_task)
        ]
        self.save_queue(username, course_name, new_queue)

    def _same_task(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        keys = ("unit_index", "task_index", "task_name")
        return all(str(left.get(key)) == str(right.get(key)) for key in keys)

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_file_path.exists():
            return {"courses": {}}
        try:
            with open(self.cache_file_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    loaded.setdefault("courses", {})
                    return loaded
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"读取任务队列缓存失败，将重新创建：{e}")
        return {"courses": {}}

    def _save_cache(self):
        try:
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"写入任务队列缓存失败: {e}")
