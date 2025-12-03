import asyncio

from src import config
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_voice_strategy import BaseVoiceStrategy


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
            # 使用 .first 来确保我们只检查第一个匹配的元素
            is_visible = await driver_service.page.locator(record_button_selector).first.is_visible(timeout=2000)
            if is_visible:
                # 进一步确认是“文字朗读”而不是“语音回答”等
                sentence_container_selector = ".oral-study-sentence"
                if await driver_service.page.locator(sentence_container_selector).count() > 0:
                    print("检测到录音按钮和朗读句子容器，应用文字朗读策略。")
                    return True
        except Exception:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        """
        循环处理页面上所有文字朗读题。
        核心的重试和评分逻辑由 BaseVoiceStrategy._execute_single_voice_task 处理。
        """
        print("=" * 20)
        print("开始执行文字朗读策略...")

        question_containers_selector = ".oral-study-sentence"
        question_containers = await self.driver_service.page.locator(question_containers_selector).all()
        print(f"发现 {len(question_containers)} 个朗读题容器。")

        should_abort_page = False

        for i, container in enumerate(question_containers):
            print(f"\n--- 开始处理第 {i + 1} 个朗读题 ---")

            try:
                # 1. 提取待朗读文本（子类特定逻辑）
                ref_text_locator = container.locator(".sentence-html-container")
                if not await ref_text_locator.is_visible(timeout=5000):
                    print("错误：在当前容器中找不到朗读文本元素，中止本页面所有语音题。")
                    should_abort_page = True
                    break
                ref_text = (await ref_text_locator.text_content()).strip()
                print(f"提取到待朗读文本: '{ref_text}'")

                # 2. 调用基类的核心执行方法
                succeeded, should_abort_from_task = await self._execute_single_voice_task(
                    container=container,
                    ref_text=ref_text,
                    retry_params=self.RETRY_PARAMS
                )
                
                if should_abort_from_task:
                    should_abort_page = True
                    break

            except Exception as e:
                print(f"处理第 {i + 1} 个语音题时发生严重错误: {e}，中止本页面所有语音题。")
                should_abort_page = True
                break

        print("\n所有语音题处理完毕。")

        if should_abort_page:
            print("由于发生错误或分数不达标，已中止最终提交。")
            return False

        # 如果不是“题中题”的一部分，则执行提交流程
        if not is_chained_task:
            should_submit = True
            if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                confirm = await asyncio.to_thread(input, "所有语音题均已完成且分数达标。是否确认提交？[Y/n]: ")
                if confirm.strip().upper() not in ["Y", ""]:
                    should_submit = False

            if should_submit:
                await self.driver_service.page.click(".btn")
                print("答案已提交。正在处理最终确认弹窗...")
                await self.driver_service.handle_submission_confirmation()
            else:
                print("用户取消提交。")
                return False
        
        return True # 所有操作成功完成