import wave
from io import BytesIO
from typing import List, Dict, Any

from playwright.async_api import Locator

from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_voice_strategy import BaseVoiceStrategy


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
            # 等待题型标识出现，超时时间设短一些，避免在不相关页面上浪费时间
            await driver_service.page.locator(".question-role-play").wait_for(timeout=3000)
            print("检测到 Role-Play 题型。")
            return True
        except Exception:
            return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        """
        执行 Role-Play 题型的自动化策略。
        """
        print("开始执行 Role-Play 策略...")

        # 一次性安装持久化劫持脚本
        await self._install_persistent_hijack()

        # 定义重试和分数阈值
        max_retries = 2
        score_threshold = 85.0
        current_retry = 0

        while current_retry <= max_retries:
            # 准备阶段
            await self._prepare_turns()

            # 如果没有需要回答的回合，提前退出
            if not self.my_turns:
                print("错误：未能识别出任何需要朗读的句子。")
                return False

            # 执行和评估阶段
            average_score = await self._execute_and_evaluate_turns()

            if average_score >= score_threshold:
                print(f"平均分 {average_score:.2f} 达到阈值 {score_threshold}，任务成功。")
                # 如果不是题中题的一部分，点击最终的提交按钮
                if not is_chained_task:
                    await self.driver_service.page.locator(".btn:has-text('提 交')").click()
                    print("已点击提交按钮。")
                return True
            else:
                current_retry += 1
                if current_retry <= max_retries:
                    print(f"平均分 {average_score:.2f} 未达到阈值。准备进行第 {current_retry} 次重试...")
                    # 重试前点击“开始”按钮以重置状态
                    await self.driver_service.page.locator(".record-seat").click()
                    print("已点击“开始”按钮以重试。")
                else:
                    print("已达到最大重试次数，任务失败。")
                    # 即使失败，如果不是题中题，也尝试点击提交按钮以结束任务
                    if not is_chained_task:
                        try:
                            await self.driver_service.page.locator(".btn:has-text('提 交')").click()
                            print("已点击提交按钮（最后尝试）。")
                        except Exception as e:
                            print(f"最后尝试提交时出错: {e}")
                    return False

        return False

    async def _prepare_turns(self):
        """
        准备阶段：选择角色、搜集我方回合、预生成音频。
        """
        print("进入准备阶段...")
        # 1. 选择第一个角色
        await self.driver_service.page.locator(".role-list .role").first.click()
        print("已选择第一个角色。")

        # 等待对话列表加载
        list_box = self.driver_service.page.locator(".role-play-quiz .list-box")
        await list_box.wait_for(timeout=5000)
        print("对话列表已加载。")

        # 2. 搜集所有需要我方朗读的句子
        self.my_turns = []
        all_items = await list_box.locator(".list-item-review").all()
        print(f"发现 {len(all_items)} 个对话项，开始筛选我方回合...")

        for item in all_items:
            # 检查 .score div 是否不含 .hide class
            score_div = item.locator(".score")
            is_hidden = await score_div.evaluate("el => el.classList.contains('hide')")
            
            if not is_hidden:
                text_locator = item.locator(".component-htmlview p")
                try:
                    text = await text_locator.text_content(timeout=1000)
                    if text:
                        self.my_turns.append({"text": text.strip(), "locator": item})
                        print(f"找到我方回合: {text.strip()}")
                except Exception:
                    # 忽略那些可能没有文本的或已失效的locator
                    continue
        
        print(f"共找到 {len(self.my_turns)} 个我方回合。")

        # 3. 预生成所有音频
        self.audio_cache = {}
        print("开始预生成音频...")
        for turn in self.my_turns:
            text = turn["text"]
            if text not in self.audio_cache:
                audio_bytes = await self.ai_service.text_to_wav(text)
                self.audio_cache[text] = audio_bytes
        print(f"已为 {len(self.audio_cache)} 句唯一文本生成音频。")

    async def _execute_and_evaluate_turns(self) -> float:
        """
        执行所有回合，并在结束后评估分数。
        返回平均分。
        """
        print("进入执行与评估阶段...")
        turn_scores = []

        # 点击总的开始按钮
        await self.driver_service.page.locator(".record-seat").click()
        print("已点击总的“开始”按钮，对话流程开始。")

        for i, turn in enumerate(self.my_turns):
            print(f"--- 开始执行第 {i + 1}/{len(self.my_turns)} 回合 ---")
            text = turn["text"]
            stable_turn_locator = turn["locator"]  # 获取我们预存的稳定locator
            audio_bytes = self.audio_cache[text]

            # 计算音频时长
            duration = 0
            with wave.open(BytesIO(audio_bytes), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration = frames / float(rate) if rate > 0 else 0

            try:
                # a. 使用临时的 active locator 等待回合开始
                active_turn_locator = self.driver_service.page.locator(".list-item-review.active").filter(has_text=text)
                await active_turn_locator.wait_for(timeout=30000)

                pause_icon_selector = "svg.pause-circle-player path[d^='M464.54']"
                await active_turn_locator.locator(pause_icon_selector).wait_for(timeout=5000)
                print(f"检测到我方回合“{text}”已开始（出现暂停图标）。")

                # b. 注入并交互
                await self._set_persistent_audio_payload(audio_bytes)

                # c. 等待音频时长 + 0.5s 缓冲，模拟真实录音时间
                wait_time = duration + 0.5
                print(f"音频时长 {duration:.2f}s，等待 {wait_time:.2f}s 模拟录音...")
                await self.driver_service.page.wait_for_timeout(wait_time * 1000)
                
                # d. 使用 active locator 点击结束按钮
                await active_turn_locator.locator("svg.pause-circle-player.active").click()
                print("已点击结束当前回合。")

                # e. 使用稳定的 locator 等待并获取分数
                print("正在等待分数更新...")
                score = await self._wait_for_and_get_score(stable_turn_locator)
                turn_scores.append(score)
                print(f"第 {i + 1} 回合得分: {score}")

            except Exception as e:
                print(f"执行第 {i+1} 回合时发生错误: {e}")
                turn_scores.append(0) # 出错则记0分
            finally:
                # f. 清理注入的脚本，为下一回合做准备
                await self._clear_persistent_audio_payload()

        # 等待最后的“提交”或“下一题”按钮出现
        final_button_locator = self.driver_service.page.locator(".btn:has-text('提 交'), .btn:has-text('下一题')").first
        await final_button_locator.wait_for(timeout=10000)
        print("检测到最终按钮（提交/下一题），本轮流程结束。")

        if not turn_scores:
            return 0.0

        average_score = sum(turn_scores) / len(turn_scores)
        return average_score
