import json
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import src.config as config
from src.utils import logger


class DiagnosticService:
    """Capture page state when automation fails."""

    @staticmethod
    async def capture_page_failure(
        driver_service,
        reason: str,
        error: BaseException | None = None,
        context: dict[str, Any] | None = None,
    ) -> Path | None:
        if not getattr(config, "DIAGNOSTICS_ENABLED", True):
            return None

        page = getattr(driver_service, "page", None)
        if page is None:
            logger.warning("诊断快照跳过：当前没有可用页面。")
            return None

        diagnostics_root = Path(getattr(config, "DIAGNOSTICS_DIR", ".diagnostics"))
        case_dir = diagnostics_root / DiagnosticService._case_name(reason)
        case_dir.mkdir(parents=True, exist_ok=True)

        metadata: dict[str, Any] = {
            "reason": reason,
            "context": context or {},
            "captured_at": datetime.now().isoformat(timespec="seconds"),
        }

        try:
            metadata["url"] = page.url
        except Exception:
            metadata["url"] = ""

        try:
            metadata["title"] = await page.title()
        except Exception as e:
            metadata["title_error"] = str(e)

        try:
            if hasattr(driver_service, "get_breadcrumb_parts"):
                metadata["breadcrumb"] = await driver_service.get_breadcrumb_parts()
        except Exception as e:
            metadata["breadcrumb_error"] = str(e)

        if error:
            metadata["error_type"] = error.__class__.__name__
            metadata["error"] = str(error)
            metadata["traceback"] = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )

        try:
            html = await page.content()
            (case_dir / "page.html").write_text(html, encoding="utf-8")
        except Exception as e:
            metadata["html_error"] = str(e)

        try:
            await page.screenshot(path=str(case_dir / "screenshot.png"), full_page=True)
        except Exception as e:
            metadata["screenshot_error"] = str(e)

        (case_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.warning(f"已保存诊断快照: {case_dir}")
        return case_dir

    @staticmethod
    def _case_name(reason: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_reason = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff-]+", "_", reason).strip("_")
        if not safe_reason:
            safe_reason = "failure"
        return f"{timestamp}_{safe_reason[:60]}"
