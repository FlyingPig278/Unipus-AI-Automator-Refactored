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
       循环处理页面上所有语音题。
       对每个题目执行：生成TTS -> JS注入 -> 模拟点击 -> 等待结果。
       """
       print("=" * 20)
       print("开始执行语音上传策略 (循环处理 + 无刷新注入模式)...")

       # 找到页面上所有语音题的容器
       question_containers_selector = ".oral-study-sentence" # 这是根据用户HTML分析出的通用容器
       question_containers = await self.driver_service.page.locator(question_containers_selector).all()
       print(f"发现 {len(question_containers)} 个语音题容器。")

       for i, container in enumerate(question_containers):
           print(f"\n--- 开始处理第 {i + 1} 个语音题 ---")

           # 为每个题目独立执行劫持和点击流程
           try:
               # 1. 在当前题目容器内提取需要朗读的文本
               ref_text_locator = container.locator(".sentence-html-container")
               if not await ref_text_locator.is_visible(timeout=5000):
                   print("警告：在当前容器中找不到朗读文本元素，跳过此题。")
                   continue
               ref_text = (await ref_text_locator.text_content()).strip()
               print(f"提取到待朗读文本: '{ref_text}'")

               # 2. 调用AIService生成高质量的WAV音频字节
               audio_bytes = await self.ai_service.text_to_wav(ref_text)
               if not audio_bytes:
                   raise Exception("生成TTS音频失败。")

               # 3. 计算音频时长
               with wave.open(BytesIO(audio_bytes), 'rb') as wf:
                   frames = wf.getnframes()
                   rate = wf.getframerate()
                   duration = frames / float(rate)
               print(f"生成的音频时长为: {duration:.2f}秒")

               # 4. 准备注入的JavaScript劫持脚本
               audio_b64 = base64.b64encode(audio_bytes).decode('ascii')
               injection_script = self._get_injection_script(audio_b64)

               # 5. 执行无刷新注入
               print("正在执行无刷新JS注入...")
               # 每次注入前，先清理一下可能存在的旧劫持
               await self.driver_service.page.evaluate("""
                   if (window.originalWebSocket) {
                       window.WebSocket = window.originalWebSocket;
                       delete window.originalWebSocket;
                       delete window.injectedAudioB64;
                       delete window.ttsAudioSent;
                       console.log('>>> 历史劫持状态已清理。');
                   }
               """)
               await self.driver_service.page.evaluate(injection_script)


               # 6. 在当前题目容器内执行UI模拟
               record_button_locator = container.locator(".button-record")
               recording_state_selector = ".button-record svg path[d*='M645.744']" # 停止按钮(方块)的SVG路径
               score_selector = "span.score_layout"

               print("点击录音按钮...")
               await record_button_locator.click()

               # 确认进入录音状态
               await container.locator(recording_state_selector).wait_for(timeout=5000)
               print(f"录音开始，等待{duration:.2f}秒...")
               await asyncio.sleep(duration + 0.5) # TODO:暂不明确具体应等待多久，只有0.5s可能不够，目前先以duration + 0.5代替

               print("点击停止按钮...")
               await record_button_locator.click()

               print("等待评分结果出现并填充...")
               score_element = container.locator(score_selector)

               # 首先等待元素可见，确保它在DOM中
               await score_element.wait_for(state='visible', timeout=5000)

               # 使用 wait_for_function 等待元素的文本内容被填充为数字
               # 我们将元素句柄传递给JS函数，确保是当前题目容器内的分数元素
               await self.driver_service.page.wait_for_function(
                   """(el) => {
                       // 确保元素可见且文本内容非空，并且是纯数字
                       return el && el.textContent && /^\d+$/.test(el.textContent.trim());
                   }""",
                   arg=await score_element.element_handle(),  # 将元素句柄传递给JS函数
                   timeout=20000
               )

               score = await score_element.text_content()
               print(f"✅ 第 {i + 1} 个语音题完成，页面显示得分: {score}")

           except Exception as e:
               print(f"处理第 {i + 1} 个语音题时发生错误: {e}")
           finally:
               # 每次循环后都清理一下注入的全局变量，避免互相干扰
               await self._cleanup_injection()

       print("\n所有语音题处理完毕。")

       confirm = await asyncio.to_thread(input, "AI已选择答案。是否确认提交？[Y/n]: ")
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