import asyncio
import wave
from io import BytesIO
from typing import List, Dict, Any

from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_voice_strategy import BaseVoiceStrategy
from src.utils import logger


class RolePlayStrategy(BaseVoiceStrategy):
    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.my_turns: List[Dict[str, Any]] = []
        self.audio_cache: Dict[str, bytes] = {}

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        """
        检查当前页面是否为 Role-Play 题型。
        """
        try:
            await driver_service.page.locator(".question-role-play").wait_for(timeout=3000)
            logger.info("检测到 Role-Play 题型。")
            return True
        except Exception:
            return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        logger.info("开始执行 Role-Play 策略...")
        await self._install_persistent_hijack()

        max_retries = 2
        score_threshold = 85.0
        current_retry = 0

        while current_retry <= max_retries:
            await self._prepare_turns()

            if not self.my_turns:
                logger.error("未能识别出任何需要朗读的句子。")
                return False

            average_score = await self._execute_and_evaluate_turns()

            if average_score >= score_threshold:
                logger.success(f"平均分 {average_score:.2f} 达到阈值 {score_threshold}，任务成功。")
                if not is_chained_task:
                    submit_button_locator = self.driver_service.page.locator(".btn:has-text('提交'), .btn:has-text('提 交')").first
                    await submit_button_locator.click()
                    logger.info("已点击提交按钮。")
                    await self.driver_service.handle_submission_confirmation()
                return True
            else:
                current_retry += 1
                if current_retry <= max_retries:
                    logger.info(f"平均分 {average_score:.2f} 未达到阈值。准备进行第 {current_retry} 次重试...")
                    await self.driver_service.page.locator(".record-seat").click()
                    logger.info("已点击“开始”按钮以重试。")
                else:
                    logger.error("已达到最大重试次数，任务失败。")
                    # if not is_chained_task:
                    #     try:
                    #         submit_button_locator = self.driver_service.page.locator(".btn:has-text('提交'), .btn:has-text('提 交')").first
                    #         await submit_button_locator.click()
                    #         logger.info("已点击提交按钮（最后尝试）。")
                    #         await self.driver_service.handle_submission_confirmation()
                    #     except Exception as e:
                    #         logger.error(f"最后尝试提交时出错: {e}")
                    return False
        return False

    async def _prepare_turns(self):
        logger.info("进入准备阶段...")
        await self.driver_service.page.locator(".role-list .role").first.click()
        logger.info("已选择第一个角色。")

        list_box = self.driver_service.page.locator(".role-play-quiz .list-box")
        await list_box.wait_for(timeout=5000)
        logger.info("对话列表已加载。")

        self.my_turns = []
        all_items = await list_box.locator(".list-item-review").all()
        logger.info(f"发现 {len(all_items)} 个对话项，开始筛选我方回合...")

        for item in all_items:
            score_div = item.locator(".score")
            is_hidden = await score_div.evaluate("el => el.classList.contains('hide')")
            
            if not is_hidden:
                text_locator = item.locator(".component-htmlview p")
                try:
                    text = await text_locator.text_content(timeout=1000)
                    if text:
                        self.my_turns.append({"text": text.strip(), "locator": item})
                        logger.info(f"找到我方回合: {text.strip()}")
                except Exception:
                    continue
        
        logger.info(f"共找到 {len(self.my_turns)} 个我方回合。")

        self.audio_cache = {}
        logger.info("开始预生成音频...")
        for turn in self.my_turns:
            text = turn["text"]
            if text not in self.audio_cache:
                audio_bytes = await self.ai_service.text_to_wav(text)
                self.audio_cache[text] = audio_bytes
        logger.info(f"已为 {len(self.audio_cache)} 句唯一文本生成音频。")

    async def _execute_and_evaluate_turns(self) -> float:
        logger.info("进入执行与评估阶段...")
        turn_scores = []

        await self.driver_service.page.locator(".record-seat").click()
        logger.info("已点击总的“开始”按钮，对话流程开始。")

        for i, turn in enumerate(self.my_turns):
            logger.info(f"--- 开始执行第 {i + 1}/{len(self.my_turns)} 回合 ---")
            text = turn["text"]
            stable_turn_locator = turn["locator"]
            audio_bytes = self.audio_cache[text]

            duration = 0
            with wave.open(BytesIO(audio_bytes), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration = frames / float(rate) if rate > 0 else 0

            try:
                active_turn_locator = self.driver_service.page.locator(".list-item-review.active").filter(has_text=text)
                await active_turn_locator.wait_for(timeout=30000)

                pause_icon_selector = "svg.pause-circle-player path[d^='M464.54']"
                await active_turn_locator.locator(pause_icon_selector).wait_for(timeout=5000)
                logger.info(f"检测到我方回合“{text}”已开始（出现暂停图标）。")

                await self._set_persistent_audio_payload(audio_bytes)

                wait_time = duration + 0.5
                logger.info(f"音频时长 {duration:.2f}s，等待 {wait_time:.2f}s 模拟录音...")
                await self.driver_service.page.wait_for_timeout(wait_time * 1000)
                
                await active_turn_locator.locator("svg.pause-circle-player.active").click()
                logger.info("已点击结束当前回合。")

                logger.info("正在等待分数更新...")
                score = await self._wait_for_and_get_score(stable_turn_locator)
                turn_scores.append(score)
                logger.info(f"第 {i + 1} 回合得分: {score}")

            except Exception as e:
                logger.error(f"执行第 {i+1} 回合时发生错误: {e}")
                turn_scores.append(0)
            finally:
                await self._clear_persistent_audio_payload()

        logger.info("我方回合已全部完成，正在等待对话结束和最终按钮的出现...")
        # 直接等待最终按钮出现，并将超时增加到30秒，以覆盖AI最后一句的播放时间。
        final_button_locator = self.driver_service.page.locator(".btn:has-text('提交'), .btn:has-text('提 交'), .btn:has-text('下一题')").first
        await final_button_locator.wait_for(timeout=30000)
        logger.info("检测到最终按钮（提交/下一题），本轮流程结束。")

        if not turn_scores:
            return 0.0

        average_score = sum(turn_scores) / len(turn_scores)
        return average_score
