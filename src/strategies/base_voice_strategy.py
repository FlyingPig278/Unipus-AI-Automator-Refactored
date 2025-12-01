import asyncio
import base64
import wave
from abc import ABC, abstractmethod
from io import BytesIO
from typing import List, Dict, Any, Tuple

from playwright.async_api import Locator

from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_strategy import BaseStrategy


class BaseVoiceStrategy(BaseStrategy, ABC):
    """
    处理所有语音上传类题目的抽象基类。

    包含了WebSocket劫持、音频注入、重试和分数判断等通用逻辑。
    子类需要实现如何识别题目（check）、如何提取待处理内容等特定逻辑。
    """

    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "base_voice"  # 子类应覆盖此属性

    @staticmethod
    @abstractmethod
    async def check(driver_service: DriverService) -> bool:
        """检查当前页面是否为本策略应处理的语音题目。"""
        raise NotImplementedError

    @abstractmethod
    def execute(self, shared_context: str = "", is_chained_task: bool = False) -> None:
        """执行策略的入口。"""
        raise NotImplementedError

    async def _execute_single_voice_task(self, container: Locator, ref_text: str, retry_params: List[Dict[str, Any]]) -> Tuple[bool, bool]:
        """
        执行单个语音任务，包含完整的重试、注入、评分逻辑。

        :param container: 当前语音题的Playwright Locator容器。
        :param ref_text: 待通过TTS朗读的文本。
        :param retry_params: 用于重试的TTS参数列表。
        :return: 一个元组 (succeeded, should_abort_page)。
        """
        last_score = 0
        succeeded = False

        for attempt, params in enumerate(retry_params):
            print(f"   --- 第 {attempt + 1}/{len(retry_params)}次尝试 ---")
            try:
                # 1. 生成音频
                audio_bytes = await self.ai_service.text_to_wav(ref_text, **{k:v for k,v in params.items() if k != 'description'})
                if not audio_bytes:
                    print("警告：生成TTS音频失败，跳过本次尝试。")
                    continue

                with wave.open(BytesIO(audio_bytes), 'rb') as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    duration = frames / float(rate)

                # 2. 注入并模拟操作
                audio_b64 = base64.b64encode(audio_bytes).decode('ascii')
                injection_script = self._get_injection_script(audio_b64)
                await self._cleanup_injection()
                await self.driver_service.page.evaluate(injection_script)

                record_button_locator = container.locator(".button-record")
                await record_button_locator.click()

                recording_state_selector = ".button-record svg path[d*='M645.744']"
                await container.locator(recording_state_selector).wait_for(timeout=5000)

                await asyncio.sleep(duration + 0.5)
                await record_button_locator.click()

                # 3. 等待并解析分数
                score_element = container.locator("span.score_layout")
                await score_element.wait_for(state='visible', timeout=10000)
                await self.driver_service.page.wait_for_function(
                    """(el) => el && el.textContent && /^\d+$/.test(el.textContent.trim())""",
                    arg=await score_element.element_handle(),
                    timeout=20000
                )
                score_str = await score_element.text_content()
                last_score = int(score_str)
                print(f"   尝试 {attempt + 1} 得分: {last_score} (使用参数: {params['description']})")

                # 4. 根据分数判断
                if last_score >= 85:
                    print("✅ 分数 >= 85，判定为优秀。")
                    succeeded = True
                    return True, False
                if last_score < 60:
                    print("❌ 分数 < 60，判定为失败，将中止整个页面。")
                    return False, True

                print(f"   分数 {last_score} 在 60-84 之间，继续尝试以获得更高分数...")

            except Exception as e:
                print(f"   第 {attempt + 1} 次尝试时发生内部错误: {e}")
                last_score = 0  # 发生错误时，分数记为0
                await asyncio.sleep(1)
            finally:
                await self._cleanup_injection()
        
        # 在所有重试结束后进行最终判断
        if not succeeded and last_score < 80:
            print(f"❌ 所有尝试结束后，最终分数 ({last_score}) 仍低于80，将中止整个页面。")
            return False, True
        
        print(f"✅ 所有尝试结束后，最终分数 ({last_score}) 在 80-84 之间，判定为可接受。")
        return True, False


    def _get_injection_script(self, audio_b64: str) -> str:
        """生成用于注入的JavaScript劫持脚本。"""
        script_template = """
        (() => {
            console.log('>>> 执行劫持脚本...');
            // 如果旧的劫持脚本存在，先移除
            if (window.originalWebSocket) {
                window.WebSocket = window.originalWebSocket;
            }
            window.injectedAudioB64 = 'AUDIO_B64_PLACEHOLDER';
            window.ttsAudioSent = false;
            window.originalWebSocket = window.WebSocket; // 保存原始WebSocket

            window.WebSocket = function(url, protocols) {
                const ws = new window.originalWebSocket(url, protocols);
                if (url.includes('speech.unipus.cn')) {
                    console.log('>>> 成功劫持语音评测WebSocket!');
                    const originalSend = ws.send;
                    ws.send = function(data) {
                        if (data.buffer instanceof ArrayBuffer) {
                            if (!window.ttsAudioSent) {
                                window.ttsAudioSent = true;
                                console.log('>>> 拦截到第一块原始音频数据，准备替换...');
                                const byteCharacters = atob(window.injectedAudioB64);
                                const byteNumbers = new Array(byteCharacters.length);
                                for (let i = 0; i < byteCharacters.length; i++) {
                                    byteNumbers[i] = byteCharacters.charCodeAt(i);
                                }
                                const byteArray = new Uint8Array(byteNumbers);
                                console.log('>>> 发送已替换的高质量TTS音频数据，大小: ' + byteArray.byteLength + ' 字节');
                                originalSend.call(this, byteArray.buffer);
                            } else {
                                console.log('>>> 已发送过TTS音频，忽略此原始音频块。');
                            }
                        } else {
                            console.log('>>> 放行文本消息:', data);
                            originalSend.call(this, data);
                        }
                    };
                }
                return ws;
            };
        })();
        """
        return script_template.replace('AUDIO_B64_PLACEHOLDER', audio_b64)

    async def _cleanup_injection(self):
        """清理注入的脚本和全局变量，恢复原始WebSocket。"""
        try:
            await self.driver_service.page.evaluate("""
                if (window.originalWebSocket) {
                    window.WebSocket = window.originalWebSocket;
                    delete window.originalWebSocket;
                    delete window.injectedAudioB64;
                    delete window.ttsAudioSent;
                    console.log('>>> 劫持脚本已清理。');
                }
            """)
        except Exception as e:
            print(f"清理劫持脚本时发生错误: {e}")
