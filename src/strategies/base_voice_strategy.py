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
    def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        """执行策略的入口。"""
        raise NotImplementedError

    async def _install_persistent_hijack(self):
        """
        安装一个持久化的WebSocket劫持脚本。
        该脚本会一直存在，通过一个全局变量来接收要发送的音频。
        """
        print("[AI-DEBUG] 正在安装持久化WebSocket劫持器...")
        persistent_script = """
        (() => {
            if (window.isAiWebSocketHijackInstalled) {
                console.log('[AI-DEBUG] 持久化劫持器已经安装，无需重复操作。');
                return;
            }
            console.log('[AI-DEBUG] 首次安装持久化劫持器...');

            window.originalWebSocket = window.WebSocket;

            window.WebSocket = function(url, protocols) {
                console.log(`[AI-DEBUG] [持久化] 新的WebSocket连接: ${url}`);
                const ws = new window.originalWebSocket(url, protocols);

                if (url.includes('speech.unipus.cn')) {
                    console.log('[AI-DEBUG] [持久化] >>> 成功劫持到语音服务器的WebSocket! <<<');
                    const originalSend = ws.send;
                    ws.send = function(data) {
                        const dataType = Object.prototype.toString.call(data);
                        const isBinary = data instanceof Blob || data instanceof ArrayBuffer || ArrayBuffer.isView(data);
                        
                        if (window.ai_audio_payload && isBinary) {
                            console.log(`[AI-DEBUG] [持久化] 检测到二进制数据流 (${dataType})，且AI音频已准备就绪。`);
                            const payload = window.ai_audio_payload;
                            delete window.ai_audio_payload; // 确保只使用一次

                            try {
                                const byteCharacters = atob(payload);
                                const byteNumbers = new Array(byteCharacters.length);
                                for (let i = 0; i < byteCharacters.length; i++) {
                                    byteNumbers[i] = byteCharacters.charCodeAt(i);
                                }
                                const byteArray = new Uint8Array(byteNumbers);
                                console.log(`[AI-DEBUG] [持久化] >>> 正在发送AI音频，大小: ${byteArray.byteLength}字节。`);
                                originalSend.call(this, byteArray.buffer);// TODO: 未来可在此处实现分块发送，模拟真实流式传输行为
                                console.log('[AI-DEBUG] [持久化] >>> AI音频发送完毕。');
                            } catch (e) {
                                console.error('[AI-DEBUG] [持久化] 音频替换过程中发生错误:', e);
                            }
                        } else if (isBinary) {
                            console.log(`[AI-DEBUG] [持久化] 检测到二进制数据流 (${dataType})，但AI音频未准备好。已阻止原始音频发送。`);
                            // 什么都不做，即阻止原始音频发送
                        } else {
                            console.log('[AI-DEBUG] [持久化] 检测到非音频数据，直接放行。', data);
                            originalSend.call(this, data);
                        }
                    };
                }
                return ws;
            };

            window.isAiWebSocketHijackInstalled = true;
            console.log('[AI-DEBUG] 持久化劫持器已激活。');
        })();
        """
        await self.driver_service.page.evaluate(persistent_script)

    async def _execute_single_voice_task(self, container: Locator, ref_text: str, retry_params: List[Dict[str, Any]]) -> Tuple[bool, bool]:
        """
        执行单个语音任务，包含完整的重试、注入、评分逻辑（使用一次性劫持）。

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

                # 2. 准备并注入一次性劫持脚本
                injection_script = self._prepare_one_shot_injection(audio_bytes)
                await self.driver_service.page.evaluate(injection_script)

                record_button_locator = container.locator(".button-record")
                await record_button_locator.click()

                recording_state_selector = ".button-record svg path[d*='M645.744']"
                await container.locator(recording_state_selector).wait_for(timeout=5000)

                await asyncio.sleep(duration + 0.5)
                await record_button_locator.click()

                last_score = await self._wait_for_and_get_score(container)
                print(f"   尝试 {attempt + 1} 得分: {last_score} (使用参数: {params['description']})")

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
                last_score = 0
                await asyncio.sleep(1)
            finally:
                await self._cleanup_one_shot_injection() # 清理一次性劫持

        if not succeeded and last_score < 80:
            print(f"❌ 所有尝试结束后，最终分数 ({last_score}) 仍低于80，将中止整个页面。")
            return False, True
        
        print(f"✅ 所有尝试结束后，最终分数 ({last_score}) 在 80-84 之间，判定为可接受。")
        return True, False

    # 新增：用于持久化劫持模式下，设置要发送的AI音频载荷
    async def _set_persistent_audio_payload(self, audio_bytes: bytes):
        """
        通过设置一个全局变量来提供预生成的音频数据，供持久化劫持脚本使用。
        """
        audio_b64 = base64.b64encode(audio_bytes).decode('ascii')
        print("   ...正在设置AI音频“信使”变量。")
        await self.driver_service.page.evaluate(f"window.ai_audio_payload = '{audio_b64}';")

    # 新增：用于一次性劫持模式下，生成自包含的劫持脚本
    def _prepare_one_shot_injection(self, audio_bytes: bytes) -> str:
        """生成用于注入的、自包含的JavaScript劫持脚本（一次性）。"""
        audio_b64 = base64.b64encode(audio_bytes).decode('ascii')
        script_template = """
        (() => {
            console.log('[AI-DEBUG] [一次性] 执行一次性劫持脚本...');
            if (window.originalWebSocketOneShot) { // 使用不同的变量名防止冲突
                window.WebSocket = window.originalWebSocketOneShot;
                console.log('[AI-DEBUG] [一次性] 已恢复原始WebSocket (一次性)。');
            }
            window.injectedAudioB64OneShot = 'AUDIO_B64_PLACEHOLDER';
            window.ttsAudioSentOneShot = false;
            window.originalWebSocketOneShot = window.WebSocket;

            window.WebSocket = function(url, protocols) {
                console.log(`[AI-DEBUG] [一次性] WebSocket连接: ${url}`);
                const ws = new window.originalWebSocketOneShot(url, protocols);
                if (url.includes('speech.unipus.cn')) {
                    console.log('[AI-DEBUG] [一次性] >>> 劫持到语音WebSocket! <<<');
                    const originalSend = ws.send;
                    ws.send = function(data) {
                        const isBinary = data instanceof Blob || data instanceof ArrayBuffer || ArrayBuffer.isView(data);
                        if (isBinary) {
                            if (!window.ttsAudioSentOneShot) {
                                window.ttsAudioSentOneShot = true;
                                console.log('[AI-DEBUG] [一次性] 拦截到第一块原始音频数据，准备替换...');
                                try {
                                    const byteCharacters = atob(window.injectedAudioB64OneShot);
                                    const byteNumbers = new Array(byteCharacters.length);
                                    for (let i = 0; i < byteCharacters.length; i++) {
                                        byteNumbers[i] = byteCharacters.charCodeAt(i);
                                    }
                                    const byteArray = new Uint8Array(byteNumbers);
                                    console.log(`[AI-DEBUG] [一次性] 发送AI音频，大小: ${byteArray.byteLength}字节。`);
                                    originalSend.call(this, byteArray.buffer);
                                    console.log('[AI-DEBUG] [一次性] AI音频发送完毕。');
                                } catch (e) {
                                    console.error('[AI-DEBUG] [一次性] 音频替换错误:', e);
                                }
                            } else {
                                console.log('[AI-DEBUG] [一次性] 后续音频块被阻止。');
                            }
                        } else {
                            originalSend.call(this, data);
                        }
                    };
                }
                return ws;
            };
            console.log('[AI-DEBUG] [一次性] 劫持已激活。');
        })();
        """
        return script_template.replace('AUDIO_B64_PLACEHOLDER', audio_b64)


    async def _wait_for_and_get_score(self, container: Locator, timeout: int = 20000) -> int:
        """
        在指定的容器内等待分数出现，并解析返回。
        """
        score_element = container.locator("span.score_layout, .score")
        try:
            await self.driver_service.page.wait_for_function(
                """(el) => {
                    if (!el || !el.textContent) return false;
                    const isVisible = el.offsetParent !== null;
                    const hasNumber = /^\d+$/.test(el.textContent.trim());
                    return isVisible && hasNumber;
                }""",
                arg=await score_element.element_handle(),
                timeout=timeout
            )
            score_str = await score_element.text_content()
            return int(score_str)
        except Exception as e:
            print(f"   等待或解析分数时出错: {e}")
            return 0

    # 用于清理一次性劫持的旧方法
    async def _cleanup_one_shot_injection(self):
        """
        清理一次性注入的脚本和全局变量，恢复原始WebSocket。
        """
        try:
            await self.driver_service.page.evaluate("""
                if (window.originalWebSocketOneShot) {
                    window.WebSocket = window.originalWebSocketOneShot;
                    delete window.originalWebSocketOneShot;
                    delete window.injectedAudioB64OneShot;
                    delete window.ttsAudioSentOneShot;
                    console.log('[AI-DEBUG] [一次性] 劫持脚本已清理。');
                }
            """)
        except Exception as e:
            print(f"清理一次性劫持脚本时发生错误: {e}")

    # 用于清理持久化劫持的“信使”变量
    async def _clear_persistent_audio_payload(self):
        """
        清理注入的“信使”变量，为下一回合做准备。
        """
        try:
            await self.driver_service.page.evaluate("delete window.ai_audio_payload;")
        except Exception as e:
            print(f"清理“信使”变量时发生错误: {e}")

