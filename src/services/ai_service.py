# src/services/ai_service.py
import whisper
import re
import json
import requests
import tempfile
import os
import asyncio
import subprocess
from pathlib import Path
import uuid # 新增导入
from openai import OpenAI
from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
import src.config as config
from src import prompts

class LocalTTSEngine:
    """
    使用Piper TTS的本地文本转语音引擎。
    负责模型管理和语音合成。
    """
    def __init__(self, model: str = "en_US-lessac-medium"):
        self.model_name = model
        # 将模型文件存放在项目根目录的.models文件夹中，方便管理
        self.models_dir = Path(".models")
        self.models_dir.mkdir(exist_ok=True)
        self.model_path = self.models_dir / f"{self.model_name}.onnx"
        self.model_config_path = self.models_dir / f"{self.model_name}.onnx.json"

    async def ensure_model_exists(self):
        """检查并自动下载所需的TTS模型。"""
        if not self.model_path.exists() or not self.model_config_path.exists():
            print(f"📥 首次使用，需要下载Piper TTS模型: {self.model_name}")
            await self._download_model()

    async def _download_model(self):
        """从HuggingFace下载Piper语音模型和配置文件。"""
        base_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/{self.model_name}"
        
        # 下载模型文件
        try:
            print(f"正在下载模型: {self.model_name}.onnx...")
            process = await asyncio.create_subprocess_shell(
                f'curl -L -o "{self.model_path}" "{base_url}.onnx"'
            )
            await process.wait()
            
            print(f"正在下载模型配置文件: {self.model_name}.onnx.json...")
            process = await asyncio.create_subprocess_shell(
                f'curl -L -o "{self.model_config_path}" "{base_url}.onnx.json"'
            )
            await process.wait()
            
            if self.model_path.exists() and self.model_config_path.exists():
                print("✅ 模型下载完成。")
            else:
                raise FileNotFoundError("模型文件下载后未找到。")
                
        except Exception as e:
            print(f"❌ 模型下载失败: {e}")
            raise

    async def synthesize(self, text: str) -> bytes | None:
        """
        使用Piper TTS将文本合成为语音，并返回WAV文件的字节数据。
        """
        # 创建一个临时的WAV文件路径
        output_path = Path(tempfile.gettempdir()) / f"piper_output_{uuid.uuid4().hex}.wav"
        
        try:
            await self.ensure_model_exists()

            print(f"正在使用Piper TTS合成语音: '{text[:30]}...'")
            piper_command = [
                "piper", 
                "--model", str(self.model_path),
                "--output_file", str(output_path)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *piper_command,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            
            _, stderr = await process.communicate(text.encode('utf-8'))
            
            if process.returncode == 0 and output_path.exists():
                with open(output_path, "rb") as f:
                    audio_bytes = f.read()
                
                print(f"Piper TTS 语音合成成功，返回 {len(audio_bytes)} 字节数据。")
                return audio_bytes
            else:
                raise Exception(f"Piper执行失败: {stderr.decode('utf-8', errors='ignore')}")

        except FileNotFoundError:
             print("错误：找不到 'piper' 命令。请确保您已经通过 'pip install piper-tts' 安装了它，并且它在系统的PATH中。")
             return None
        except Exception as e:
            print(f"❌ Piper TTS 合成失败: {e}")
            return None
        finally:
            # 确保临时文件被删除
            if output_path.exists():
                output_path.unlink()
			


class AIService:
    """
    AI服务类，封装了所有与AI模型（Whisper, DeepSeek, 本地TTS）的交互。
    """
    def __init__(self):
        """
        初始化AI服务，加载Whisper模型、配置DeepSeek客户端和本地TTS引擎。
        """
        print("正在加载Whisper模型...")
        self.whisper_model = whisper.load_model(config.WHISPER_MODEL)
        print("Whisper模型加载完毕。")

        print("正在配置DeepSeek客户端...")
        self.deepseek_client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
        print("DeepSeek客户端配置完毕。")

        print("正在初始化本地TTS引擎...")
        self.local_tts_engine = LocalTTSEngine()
        print("本地TTS引擎初始化完毕。")

    async def text_to_wav(self, text: str) -> str | None:
        """
        使用本地TTS引擎将文本转换为WAV格式的音频文件。
        """
        # 直接调用本地TTS引擎的synthesize方法
        return await self.local_tts_engine.synthesize(text)
		
    def transcribe_media_from_url(self, url: str) -> str:
        """
        从URL下载媒体文件（音频或视频），转录为文字，然后删除临时文件。
        """
        temp_file_path = None
        try:
            print(f"正在从URL下载媒体文件: {url}")
            response = requests.get(url, stream=True, headers=config.HEADERS, timeout=30)
            response.raise_for_status()

            path_part = url.split('?')[0]
            suffix = os.path.splitext(path_part)[1] or '.tmp'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file_path = temp_file.name
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
            
            print(f"媒体文件已临时保存至: {temp_file_path}")
            return self.transcribe_media_file(temp_file_path)

        except requests.RequestException as e:
            print(f"下载媒体文件时发生错误: {e}")
            return ""
        except Exception as e:
            print(f"处理媒体文件URL时发生未知错误: {e}")
            return ""
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                print(f"已清理临时文件: {temp_file_path}")

    def transcribe_media_file(self, file_path: str) -> str:
        """
        使用Whisper模型将指定的媒体文件（音频或视频）转换为文字。
        """
        print(f"正在进行语音识别: {file_path}")
        try:
            result = self.whisper_model.transcribe(file_path)
            text = result.get("text", "")
            print("语音识别完成。")
            return text
        except Exception as e:
            print(f"语音识别过程中发生错误: {e}")
            return ""

    def get_chat_completion(self, prompt: str) -> dict | None:
        """
        调用DeepSeek聊天模型获取答案，并解析返回的JSON。
        """
        print("正在请求DeepSeek AI获取答案 (JSON模式)...")
        try:
            messages = [
                ChatCompletionSystemMessageParam(role="system", content=prompts.SYSTEM_PROMPT),
                ChatCompletionUserMessageParam(role="user", content=prompt),
            ]
            
            ai_response = self.deepseek_client.chat.completions.create(
                model=config.DEEPSEEK_CHAT_MODEL,
                messages=messages,
                temperature=0.2,
                response_format={'type': 'json_object'}
            )
            
            answer_content = ai_response.choices[0].message.content
            print("已收到DeepSeek的回复。")

            try:
                json_data = json.loads(answer_content)
                print("成功解析AI的答案。")
                return json_data
            except json.JSONDecodeError as e:
                print(f"错误：解析AI返回的JSON时失败: {e}")
                print(f"尝试解析的字符串: {answer_content}")
                return None

        except Exception as e:
            print(f"调用DeepSeek API时发生错误: {e}")
            return None
			

