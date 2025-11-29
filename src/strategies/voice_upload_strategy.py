import asyncio
import base64
import wave
from io import BytesIO

from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_strategy import BaseStrategy


class VoiceUploadStrategy(BaseStrategy):
   """
   处理语音上传题目的策略。
   采用无刷新JS注入方式，循环处理页面上所有语音题。
   """

   def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
       super().__init__(driver_service, ai_service, cache_service)
       self.strategy_type = "voice_upload"

   @staticmethod
   async def check(driver_service: DriverService) -> bool:
       """检查当前页面是否为语音上传题目。"""
       try:
           record_button_selector = ".button-record"
           # 使用 .first 来确保我们只检查第一个匹配的元素
           is_visible = await driver_service.page.locator(record_button_selector).first.is_visible(timeout=2000)
           if is_visible:
               print("检测到录音按钮，应用语音上传策略。")
               return True
       except Exception:
           return False
       return False

   async def execute(self) -> None:
       """
       循环处理页面上所有语音题，并实现带参数的自动重试机制。
       """
       print("=" * 20)
       print("开始执行语音上传策略 (自动重试模式)...")

       # 预设的重试参数列表
       RETRY_PARAMS = [
           {'length_scale': 1.0, 'noise_scale': 0.2, 'noise_w': 0.2, 'description': "正常语速，低噪声"},
           {'length_scale': 0.9, 'noise_scale': 0.33, 'noise_w': 0.4, 'description': "稍快语速，中等噪声"},
           {'length_scale': 1.1, 'noise_scale': 0.1, 'noise_w': 0.1, 'description': "稍慢语速，极低噪声"},
       ]

       question_containers_selector = ".oral-study-sentence"
       question_containers = await self.driver_service.page.locator(question_containers_selector).all()
       print(f"发现 {len(question_containers)} 个语音题容器。")

       should_abort_page = False

       for i, container in enumerate(question_containers):
           print(f"\n--- 开始处理第 {i + 1} 个语音题 ---")

           last_score = 0
           succeeded = False

           try:
               ref_text_locator = container.locator(".sentence-html-container")
               if not await ref_text_locator.is_visible(timeout=5000):
                   print("错误：在当前容器中找不到朗读文本元素，中止本页面所有语音题。")
                   should_abort_page = True
                   break
               ref_text = (await ref_text_locator.text_content()).strip()
               print(f"提取到待朗读文本: '{ref_text}'")

               # 开始重试循环
               for attempt, params in enumerate(RETRY_PARAMS):
                   print(f"   --- 第 {attempt + 1}/{len(RETRY_PARAMS)}次尝试 ---")

                   try:
                       audio_bytes = await self.ai_service.text_to_wav(ref_text, **{k:v for k,v in params.items() if k != 'description'})
                       if not audio_bytes:
                           print("警告：生成TTS音频失败，跳过本次尝试。")
                           continue

                       with wave.open(BytesIO(audio_bytes), 'rb') as wf:
                           frames = wf.getnframes()
                           rate = wf.getframerate()
                           duration = frames / float(rate)

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

                       if last_score >= 85:
                           print("✅ 分数 >= 85，判定为优秀，处理下一句。")
                           succeeded = True
                           break
                       if last_score < 60:
                           print("❌ 分数 < 60，判定为失败，中止整个页面。")
                           should_abort_page = True
                           break

                       print(f"   分数 {last_score} 在 60-84 之间，继续尝试以获得更高分数...")

                   except Exception as e:
                       print(f"   第 {attempt + 1} 次尝试时发生内部错误: {e}")
                       last_score = 0 # 发生错误时，分数记为0
                       await asyncio.sleep(1) # 稍作等待

               # 在所有重试结束后进行最终判断
               if should_abort_page: # 如果在循环内部已经决定中止
                   break

               if not succeeded and last_score < 80:
                   print(f"❌ 所有尝试结束后，最终分数 ({last_score}) 仍低于80，中止整个页面。")
                   should_abort_page = True
                   break
               elif not succeeded:
                    print(f"✅ 所有尝试结束后，最终分数 ({last_score}) 在 80-84 之间，判定为可接受，处理下一句。")

           except Exception as e:
               print(f"处理第 {i + 1} 个语音题时发生严重错误: {e}，中止本页面所有语音题。")
               should_abort_page = True
               break
           finally:
               await self._cleanup_injection()

       print("\n所有语音题处理完毕。")

       if should_abort_page:
           print("由于发生错误或分数不达标，已中止最终提交。")
           return

       confirm = await asyncio.to_thread(input, "所有语音题均已完成且分数达标。是否确认提交？[Y/n]: ")
       if confirm.strip().upper() in ["Y", ""]:
           await self.driver_service.page.click(".btn")
           print("答案已提交。正在处理最终确认弹窗...")
           await self.driver_service.handle_submission_confirmation()

   def _get_injection_script(self, audio_b64: str) -> str:
       """生成用于注入的JavaScript劫持脚本。"""
       # 使用占位符替换，避免Python f-string和JS模板字符串的冲突
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

   async def close(self):
       """关闭HTTP客户端（如果存在）。"""
       # API调用被移除，但保留close方法以符合基类接口
       pass