# src/services/ai_service.py
import whisper
import re
import json
import requests
import tempfile
import os
from openai import OpenAI
from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
import src.config as config
from src import prompts # 导入新的prompts模块

class AIService:
    """
    AI服务类，封装了所有与AI模型（Whisper, DeepSeek）的交互。
    """
    def __init__(self):
        """
        初始化AI服务，加载Whisper模型并配置DeepSeek客户端。
        """
        print("正在加载Whisper模型...")
        # 加载Whisper模型，模型大小在config中定义
        self.whisper_model = whisper.load_model(config.WHISPER_MODEL)
        print("Whisper模型加载完毕。")

        print("正在配置DeepSeek客户端...")
        # 配置DeepSeek API客户端
        self.deepseek_client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
        print("DeepSeek客户端配置完毕。")

    def transcribe_media_from_url(self, url: str) -> str:
        """
        从URL下载媒体文件（音频或视频），转录为文字，然后删除临时文件。
        """
        temp_file_path = None
        try:
            print(f"正在从URL下载媒体文件: {url}")
            # 添加headers和timeout参数，模拟浏览器请求，增加健壮性
            response = requests.get(url, stream=True, headers=config.HEADERS, timeout=30) # 增加下载超时时间
            response.raise_for_status() # 如果下载失败则抛出异常

            # 创建一个带正确扩展名的临时文件
            # 从URL中提取路径部分，避免查询参数的干扰
            path_part = url.split('?')[0]
            suffix = os.path.splitext(path_part)[1] or '.tmp'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file_path = temp_file.name
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
            
            print(f"媒体文件已临时保存至: {temp_file_path}")
            # 调用转录方法
            return self.transcribe_media_file(temp_file_path)

        except requests.RequestException as e:
            print(f"下载媒体文件时发生错误: {e}")
            return ""
        except Exception as e:
            print(f"处理媒体文件URL时发生未知错误: {e}")
            return ""
        finally:
            # 确保临时文件在操作结束后被删除
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                print(f"已清理临时文件: {temp_file_path}")

    def transcribe_media_file(self, file_path: str) -> str:
        """
        使用Whisper模型将指定的媒体文件（音频或视频）转换为文字。
        Whisper会自动处理视频文件中的音轨。

        Args:
            file_path (str): 媒体文件的本地路径。

        Returns:
            str: 识别出的文本内容。
        """
        print(f"正在进行语音识别: {file_path}")
        try:
            result = self.whisper_model.transcribe(file_path)
            text = result.get("text", "")
            print("语音识别完成。")
            return text
        except Exception as e:
            print(f"语音识别过程中发生错误: {e}")
            return "" # 返回空字符串表示失败

    def get_chat_completion(self, prompt: str) -> dict | None:
        """
        调用DeepSeek聊天模型获取答案，并解析返回的JSON。
        利用了DeepSeek的JSON Output模式，确保返回格式正确。
        """
        print("正在请求DeepSeek AI获取答案 (JSON模式)...")
        try:
            messages = [
                ChatCompletionSystemMessageParam(
                    role="system",
                    content=prompts.SYSTEM_PROMPT, # 使用集中的系统指令
                ),
                ChatCompletionUserMessageParam(role="user", content=prompt),
            ]
            
            ai_response = self.deepseek_client.chat.completions.create(
                model=config.DEEPSEEK_CHAT_MODEL,
                messages=messages,
                temperature=0.2,
                response_format={'type': 'json_object'} # 启用JSON输出模式
            )
            
            answer_content = ai_response.choices[0].message.content
            print("已收到DeepSeek的回复。")

            # 由于启用了JSON模式，可以直接解析，不再需要正则表达式
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
