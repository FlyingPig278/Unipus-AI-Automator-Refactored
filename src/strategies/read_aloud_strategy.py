import asyncio
import unicodedata

from src import config
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_voice_strategy import BaseVoiceStrategy
from src.utils import logger


class ReadAloudStrategy(BaseVoiceStrategy):
    """
    处理文字朗读类语音题的策略。
    """

    # 预设的重试参数列表，特定于朗读长句
    RETRY_PARAMS = [
        {'length_scale': 1.0, 'noise_scale': 0.2, 'noise_w': 0.2, 'description': "正常语速，低噪声"},
        {'length_scale': 0.9, 'noise_scale': 0.33, 'noise_w': 0.4, 'description': "稍快语速，中等噪声"},
        {'length_scale': 1.1, 'noise_scale': 0.1, 'noise_w': 0.1, 'description': "稍慢语速，极低噪声"},
    ]

    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "read_aloud"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        """检查当前页面是否为文字朗读题目。"""
        try:
            record_button_selector = ".button-record"
            is_visible = await driver_service.page.locator(record_button_selector).first.is_visible(timeout=2000)
            if is_visible:
                sentence_container_selector = ".oral-study-sentence"
                if await driver_service.page.locator(sentence_container_selector).count() > 0:
                    logger.info("检测到录音按钮和朗读句子容器，应用文字朗读策略。")
                    return True
        except Exception:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        logger.info("=" * 20)
        logger.info("开始执行文字朗读策略...")

        question_containers_selector = ".oral-study-sentence"
        question_containers = await self.driver_service.page.locator(question_containers_selector).all()
        logger.info(f"发现 {len(question_containers)} 个朗读题容器。")

        should_abort_page = False

        for i, container in enumerate(question_containers):
            logger.info(f"\n--- 开始处理第 {i + 1} 个朗读题 ---")

            try:
                ref_text_locator = container.locator(".sentence-html-container")
                if not await ref_text_locator.is_visible(timeout=5000):
                    logger.error("错误：在当前容器中找不到朗读文本元素，中止本页面所有语音题。")
                    should_abort_page = True
                    break
                
                # 1. 提取原始文本
                raw_text = (await ref_text_locator.text_content()).strip()
                
                # 2. 清洗和标准化文本，去除可能导致TTS引擎崩溃的不可见字符或非标准字符
                normalized_text = unicodedata.normalize('NFKC', raw_text)
                
                # 3. 额外将特殊的标点符号替换为基础的ASCII等价物，提高兼容性
                ref_text = normalized_text.replace('—', '-') \
                                          .replace('…', '...') \
                                          .replace('“', '"') \
                                          .replace('”', '"') \
                                          .replace('‘', "'") \
                                          .replace('’', "'")
                
                logger.info(f"提取并清洗待朗读文本: '{ref_text}'")

                succeeded, should_abort_from_task = await self._execute_single_voice_task(
                    container=container,
                    ref_text=ref_text,
                    retry_params=self.RETRY_PARAMS
                )
                
                if should_abort_from_task:
                    should_abort_page = True
                    break

            except Exception as e:
                logger.error(f"处理第 {i + 1} 个语音题时发生严重错误: {e}，中止本页面所有语音题。")
                should_abort_page = True
                break

        logger.info("所有语音题处理完毕。")

        if should_abort_page:
            logger.warning("由于发生错误或分数不达标，已中止最终提交。")
            return False

        if not is_chained_task:
            should_submit = True
            if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                confirm = await asyncio.to_thread(input, "所有语音题均已完成且分数达标。是否确认提交？[Y/n]: ")
                if confirm.strip().upper() not in ["Y", ""]:
                    should_submit = False

            if should_submit:
                await self.driver_service.page.click(".btn")
                await self.driver_service.handle_rate_limit_modal()
                logger.info("答案已提交。正在处理最终确认弹窗...")
                await self.driver_service.handle_submission_confirmation()
            else:
                logger.warning("用户取消提交。")
                return False
        
        return True