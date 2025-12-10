# src/services/ai_service.py
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import uuid  # 新增导入
import zipfile
from pathlib import Path
import requests
import whisper
from openai import OpenAI
from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
from rich.progress import Progress, BarColumn, TextColumn, DownloadColumn, TransferSpeedColumn

import src.config as config
from src import prompts
from src.utils import logger
import warnings


class LocalTTSEngine:
    """
    使用Piper TTS的本地文本转语音引擎。
    负责模型管理和语音合成。
    """
    def __init__(self, model: str = "en_US-libritts_r-medium"):
        self.model_name = model
        # 将模型文件存放在项目根目录的.models文件夹中，方便管理
        self.models_dir = Path(".models")
        self.models_dir.mkdir(exist_ok=True)

        python_dir = Path(sys.prefix)
        self.piper_exe_path = python_dir / "Scripts" / "piper.exe"

        # 初始化模型路径
        self.model_path = self.models_dir / f"{self.model_name}.onnx"
        self.model_config_path = self.models_dir / f"{self.model_name}.onnx.json"

        # 设置安全的 espeak-ng-data 路径
        self.safe_espeak_path = self._setup_safe_espeak_data(python_dir)

    def _setup_safe_espeak_data(self, python_dir: Path) -> str | None:
        """
        解决中文路径问题的核心方法：
        将 espeak-ng-data 复制到系统的临时目录（通常是纯英文路径），
        避开 C++ 程序无法读取包含中文/特殊字符路径的问题。
        """
        try:
            # 1. 寻找原始的安装路径
            original_path = python_dir / "Lib" / "site-packages" / "piper" / "espeak-ng-data"
            
            # 如果找不到，尝试遍历 site-packages (针对不同环境)
            if not original_path.exists():
                import site
                for path in site.getsitepackages():
                    potential = Path(path) / "piper" / "espeak-ng-data"
                    if potential.exists():
                        original_path = potential
                        break
            
            if not original_path.exists():
                logger.warning("未找到原始 espeak-ng-data 目录，跳过配置。")
                return None

            # 2. 设定一个安全的临时目标路径 (在 %TEMP% 下)
            # 例如: C:\Users\flyin\AppData\Local\Temp\piper_espeak_safe_v1
            temp_root = Path(tempfile.gettempdir())
            safe_target = temp_root / "piper_espeak_safe_v1"

            # 3. 检查是否需要复制
            # 如果目标不存在，或者为空，则进行复制
            if not safe_target.exists() or not any(safe_target.iterdir()):
                logger.info(f"正在构建中文路径兼容环境...")
                logger.info(f"源路径: {original_path}")
                logger.info(f"目标安全路径: {safe_target}")
                
                # 如果存在残留但不完整，先清除
                if safe_target.exists():
                    shutil.rmtree(safe_target)
                
                # 复制文件夹
                shutil.copytree(original_path, safe_target)
                logger.success("已成功将 piper 数据文件迁移至安全路径。")
            else:
                logger.debug(f"安全数据路径已存在，直接使用: {safe_target}")

            return str(safe_target)

        except Exception as e:
            logger.error(f"构建安全数据环境失败: {e}")
            return None

    async def ensure_model_exists(self):
        """检查并自动下载所需的TTS模型。"""
        if not self.model_path.exists() or not self.model_config_path.exists():
            logger.info(f"📥 首次使用，需要下载Piper TTS模型: {self.model_name}")
            await self._download_model()

    async def _download_model(self):
        """
        使用requests库和rich进度条，以更安全的方式下载Piper语音模型。
        - 检查HTTP状态码。
        - 下载到.part临时文件，成功后再重命名。
        - 清理失败的下载。
        """
        try:
            parts = self.model_name.split('-')
            if len(parts) != 3:
                raise ValueError(f"模型名称 '{self.model_name}' 格式不正确，应为 'locale-voice-quality'。")
            
            locale, voice, quality = parts
            lang = locale.split('_')[0]

            base_url = f"https://hf-mirror.com/rhasspy/piper-voices/resolve/main/{lang}/{locale}/{voice}/{quality}/{self.model_name}"
            
            logger.info(f"根据模型名称动态构建下载URL: {base_url}")

            # 定义要下载的文件和它们的目标路径
            files_to_download = {
                f"{self.model_name}.onnx": self.model_path,
                f"{self.model_name}.onnx.json": self.model_config_path
            }

            # 使用 rich.progress 创建一个美观的进度条
            progress = Progress(
                TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
                BarColumn(bar_width=None),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                DownloadColumn(),
                "•",
                TransferSpeedColumn(),
            )

            def download_job(url, dest_path):
                dest_path_part = dest_path.with_suffix(dest_path.suffix + '.part')
                task_id = progress.add_task("download", filename=dest_path.name, start=False)
                
                try:
                    response = requests.get(url, stream=True, timeout=30)
                    response.raise_for_status()
                    
                    total_size = int(response.headers.get('content-length', 0))
                    progress.start_task(task_id)
                    progress.update(task_id, total=total_size)
                    
                    with open(dest_path_part, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                            progress.update(task_id, advance=len(chunk))

                    # 下载成功后重命名
                    dest_path_part.rename(dest_path)
                    logger.debug(f"文件 '{dest_path.name}' 下载成功。")

                except requests.RequestException as e:
                    # 如果发生网络错误，清理.part文件
                    if dest_path_part.exists():
                        dest_path_part.unlink()
                    # 将异常向上抛出，以便外层可以捕获
                    raise e
                finally:
                    progress.stop_task(task_id)
                    progress.update(task_id, visible=False)


            with progress:
                for filename, path in files_to_download.items():
                    url = f"{base_url}{'.onnx' if filename.endswith('.onnx') else '.onnx.json'}"
                    # 使用 to_thread 在异步函数中运行同步的下载代码
                    await asyncio.to_thread(download_job, url, path)

            # 最终校验文件是否存在
            if self.model_path.exists() and self.model_config_path.exists():
                logger.success("✅ 模型及配置文件下载完成。")
            else:
                raise FileNotFoundError("模型文件下载后校验失败，一个或多个文件不存在。")

        except Exception as e:
            logger.error(f"模型下载失败: {e}")
            # 再次确保清理
            for _, path in files_to_download.items():
                part_file = path.with_suffix(path.suffix + '.part')
                if part_file.exists():
                    part_file.unlink()
            raise


    @staticmethod
    def _clean_text_for_tts(text: str) -> str:
        """
        对文本进行净化，为纯英文TTS引擎准备兼容性良好的输入。
        """
        if not isinstance(text, str):
            return ""

        # 1. 使用 NFKC 规范化处理兼容性字符（例如全角到半角）
        normalized_text = unicodedata.normalize('NFKC', text)

        # 2. 定义一个更全面的特殊标点符号替换表
        replacements = {
            '—': '-',  # EM DASH
            '–': '-',  # EN DASH
            '…': '...',  # HORIZONTAL ELLIPSIS
            '「': '"',  # LEFT CORNER BRACKET
            '」': '"',  # RIGHT CORNER BRACKET
            '『': '"',  # LEFT WHITE CORNER BRACKET
            '』': '"',  # RIGHT WHITE CORNER BRACKET
            '《': '"',  # LEFT DOUBLE ANGLE BRACKET
            '》': '"',  # RIGHT DOUBLE ANGLE BRACKET
            '〈': "'",  # LEFT ANGLE BRACKET
            '〉': "'",  # RIGHT ANGLE BRACKET
            '“': '"',
            '”': '"',
            '‘': "'",
            '’': "'",
            '`': "'",  # 反引号
            '´': "'",  # 锐音符
            '′': "'",  # 分符号
            '″': '"',  # 秒符号
        }
        for old, new in replacements.items():
            normalized_text = normalized_text.replace(old, new)

        # 3. 白名单过滤：只保留英文、数字和指定的标点符号
        # 使用正则表达式移除所有不符合白名单的字符
        allowed_chars_pattern = r"[^a-zA-Z0-9\s.,?!'\"():;-]"
        clean_text = re.sub(allowed_chars_pattern, '', normalized_text)
        
        # 4. 去除多余的空白字符
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()

        return clean_text

    async def synthesize(self, text: str, length_scale: float = 1.0, noise_scale: float = 0.667, noise_w: float = 0.8) -> bytes | None:
        """
        使用Piper TTS将文本合成为语音，并返回WAV文件的字节数据。
        新增length_scale, noise_scale, noise_w参数以控制语速和发音风格。
        """
        # 步骤 1: 净化文本输入
        clean_text = self._clean_text_for_tts(text)
        if not clean_text:
            logger.warning(f"原始文本 '{text[:30]}...' 净化后为空，跳过TTS合成。")
            return None

        # 创建一个临时的WAV文件路径
        output_path = Path(tempfile.gettempdir()) / f"piper_output_{uuid.uuid4().hex}.wav"
        
        try:
            await self.ensure_model_exists()

            # 检查 piper.exe 是否存在于便携版Python的Scripts目录中
            if not self.piper_exe_path.exists():
                logger.error(f"TTS引擎 'piper.exe' 未在便携式环境的Scripts文件夹中找到。")
                logger.error(f"预期路径: {self.piper_exe_path}")
                logger.error("请确认 'piper-tts' 是否已通过 'run.bat' 脚本正确安装。")
                return None

            logger.debug(f"正在使用Piper TTS合成语音 (语速: {length_scale}, noise_scale: {noise_scale}, noise_w: {noise_w}): '{clean_text[:30]}...'")
            piper_command = [
                str(self.piper_exe_path),
                "--model", str(self.model_path),
                "--output_file", str(output_path),
                "--length_scale", str(length_scale),
                "--noise_scale", str(noise_scale),
                "--noise_w", str(noise_w)
            ]

            # 在Windows上，使用CREATE_NO_WINDOW标志来隐藏子进程的控制台窗口
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            
            # 注入指向安全路径的环境变量
            env = os.environ.copy()
            if self.safe_espeak_path:
                env["ESPEAK_DATA_PATH"] = self.safe_espeak_path
                logger.debug(f"已注入环境变量 ESPEAK_DATA_PATH: {self.safe_espeak_path}")

            process = await asyncio.create_subprocess_exec(
                *piper_command,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=creation_flags,
                env=env # 传入修改后的环境
            )
            
            _, stderr = await process.communicate(clean_text.encode('utf-8'))
            
            if process.returncode == 0 and output_path.exists():
                with open(output_path, "rb") as f:
                    audio_bytes = f.read()
                
                logger.debug(f"Piper TTS 语音合成成功，返回 {len(audio_bytes)} 字节数据。")
                return audio_bytes
            else:
                raise Exception(f"Piper执行失败: {stderr.decode('utf-8', errors='ignore')}")

        except FileNotFoundError:
             # 这个异常理论上不应该再被触发，因为我们已经提前检查了路径
             logger.error(f"命令执行失败，找不到文件: {self.piper_exe_path}")
             return None
        except Exception as e:
            logger.error(f"Piper TTS 合成失败: {e}")
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
        初始化AI服务。注意：这是一个同步构造函数，
        异步组件的初始化请通过调用'create'工厂方法来完成。
        """
        # 同步组件的初始化
        logger.info("正在加载Whisper模型...")
        warnings.filterwarnings("ignore", message="FP16 is not supported on CPU; using FP32 instead", category=UserWarning)
        self.whisper_model = whisper.load_model(config.WHISPER_MODEL)
        logger.info("Whisper模型加载完毕。")

        logger.info("正在配置DeepSeek客户端...")
        self.deepseek_client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
        logger.info("DeepSeek客户端配置完毕。")

        logger.info("正在初始化本地TTS引擎...")
        self.local_tts_engine = LocalTTSEngine()
        logger.info("本地TTS引擎初始化完毕。")

    @classmethod
    async def create(cls):
        """
        异步工厂方法，用于创建并完全初始化AIService实例。
        """
        instance = cls()
        # 调用异步的初始化部分
        await instance._check_and_configure_ffmpeg()
        return instance

    async def _check_and_configure_ffmpeg(self):
        """
        检查ffmpeg是否存在于当前Python环境中，如果不存在，则按需下载。
        此方法统一处理标准虚拟环境和便携式环境。
        """
        logger.info("正在检查并配置FFmpeg...")
        
        # 目标目录为当前Python环境下的'bin'文件夹，具有通用性
        # sys.prefix 在虚拟环境中指向 .venv 目录，在便携版中指向 python-embed 目录
        try:
            target_dir = Path(sys.prefix) / "bin"
            target_dir.mkdir(exist_ok=True)
            ffmpeg_exe_path = target_dir / "ffmpeg.exe"

            if not ffmpeg_exe_path.exists():
                logger.warning(f"在 '{target_dir}' 中未找到ffmpeg.exe，将尝试自动下载...")
                await self._download_ffmpeg(ffmpeg_exe_path)
            
            if ffmpeg_exe_path.exists():
                # 将ffmpeg所在的目录添加到PATH
                os.environ["PATH"] = str(target_dir.resolve()) + os.pathsep + os.environ["PATH"]
                # 最终验证
                creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True, creationflags=creation_flags)
                logger.success("FFmpeg 已为当前会话配置成功并通过验证。")
            else:
                raise FileNotFoundError("FFmpeg下载后校验失败，文件不存在。")

        except Exception as e:
            logger.error(f"FFmpeg 配置或下载过程中发生错误: {e}")
            logger.error("语音识别功能将无法处理视频文件！请检查网络或尝试手动下载ffmpeg.exe。")

    async def _download_ffmpeg(self, target_path: Path):
        """
        从国内友好的镜像源下载并解压ffmpeg.exe，包含中断安全机制。
        """
        # 使用gh-proxy.com作为GitHub的国内加速代理
        ffmpeg_zip_url = "https://gh-proxy.com/https://github.com/GyanD/codexffmpeg/releases/download/6.0/ffmpeg-6.0-essentials_build.zip"
        
        temp_dir = Path(tempfile.gettempdir()) / f"ffmpeg_dl_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        ffmpeg_zip_path = temp_dir / "ffmpeg.zip"

        try:
            progress = Progress(
                TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
                BarColumn(bar_width=None),
                "[progress.percentage]{task.percentage:>3.1f}%", "•",
                DownloadColumn(), "•", TransferSpeedColumn(),
            )
            
            def download_job():
                """下载任务，包含中断安全机制。"""
                zip_part_path = ffmpeg_zip_path.with_suffix('.zip.part')
                task_id = progress.add_task("download", filename="ffmpeg-essentials.zip", start=False)
                
                try:
                    response = requests.get(ffmpeg_zip_url, stream=True, timeout=120) # 增加超时时间
                    response.raise_for_status()
                    total_size = int(response.headers.get('content-length', 0))
                    progress.start_task(task_id)
                    progress.update(task_id, total=total_size)
                    
                    with open(zip_part_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                            progress.update(task_id, advance=len(chunk))
                    
                    zip_part_path.rename(ffmpeg_zip_path) # 下载成功后，将.part文件重命名为最终文件
                except requests.RequestException as e:
                    if zip_part_path.exists():
                        zip_part_path.unlink() # 如果发生网络错误，清理.part文件
                    raise e
                finally:
                    progress.stop_task(task_id)
                    progress.update(task_id, visible=False)

            with progress:
                logger.info(f"正在从国内镜像源下载 FFmpeg...")
                await asyncio.to_thread(download_job)

            logger.info("下载完成，正在解压以提取 ffmpeg.exe...")
            with zipfile.ZipFile(ffmpeg_zip_path, 'r') as zip_ref:
                ffmpeg_info = next((member for member in zip_ref.infolist() if member.filename.endswith('/bin/ffmpeg.exe')), None)
                
                if ffmpeg_info:
                    # 直接将找到的ffmpeg.exe解压到目标路径
                    with zip_ref.open(ffmpeg_info) as source, open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
                    logger.success(f"FFmpeg 已成功部署到: {target_path}")
                else:
                    raise FileNotFoundError("在下载的压缩包中未能找到 'bin/ffmpeg.exe'。")
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                logger.debug("已清理FFmpeg下载产生的临时文件。")

    async def text_to_wav(self, text: str, length_scale: float = 1.0, noise_scale: float = 0.667, noise_w: float = 0.8) -> str | None:
        """
        使用本地TTS引擎将文本转换为WAV格式的音频文件。
        """
        # 直接调用本地TTS引擎的synthesize方法，并传递语速和发音风格参数
        return await self.local_tts_engine.synthesize(text, length_scale, noise_scale, noise_w)
		
    def transcribe_media_from_url(self, url: str) -> str:
        """
        从URL下载媒体文件（音频或视频），转录为文字，然后删除临时文件。
        """
        temp_file_path = None
        try:
            logger.info(f"正在从URL下载媒体文件: {url}")
            response = requests.get(url, stream=True, headers=config.HEADERS, timeout=30)
            response.raise_for_status()

            # 创建一个自定义的临时文件夹
            temp_dir = Path(".temp_downloads")
            temp_dir.mkdir(parents=True, exist_ok=True)  # 如果文件夹不存在就创建

            # 去掉 URL 中的查询参数部分
            path_part = url.split('?')[0]  # 去掉查询参数
            path_part = path_part.split('#')[0]  # 去掉 URL 中的 fragment 部分（#后面的部分）

            # 提取文件后缀
            suffix = os.path.splitext(path_part)[1]

            if not suffix:
                # 如果没有后缀，通过 MIME 类型来推断
                content_type = response.headers.get('Content-Type')
                if 'video' in content_type:
                    suffix = '.mp4'
                elif 'audio' in content_type:
                    suffix = '.mp3'
                else:
                    suffix = '.tmp'  # 默认后缀

            # 保存文件到指定目录并给文件添加正确的后缀
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=temp_dir) as temp_file:
                temp_file_path = temp_file.name
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)

            logger.info(f"媒体文件已临时保存至: {temp_file_path}")
            return self.transcribe_media_file(temp_file_path)

        except requests.RequestException as e:
            logger.error(f"下载媒体文件时发生错误: {e}")
            return ""
        except Exception as e:
            logger.error(f"处理媒体文件URL时发生未知错误: {e}")
            return ""
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                logger.info(f"已清理临时文件: {temp_file_path}")

    def transcribe_media_file(self, file_path: str) -> str:
        """
        使用Whisper模型将指定的媒体文件（音频或视频）转换为文字。
        """
        logger.info(f"正在进行语音识别: {file_path}")
        try:
            result = self.whisper_model.transcribe(file_path)
            text = result.get("text", "")
            logger.info("语音识别完成。")
            return text
        except Exception as e:
            logger.error(f"语音识别过程中发生错误: {e}")
            return ""

    def get_chat_completion(self, prompt: str) -> dict | None:
        """
        调用DeepSeek聊天模型获取答案，并解析返回的JSON。
        """
        logger.info("正在请求DeepSeek AI获取答案 (JSON模式)...")
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
            logger.info("已收到DeepSeek的回复。")

            try:
                json_data = json.loads(answer_content)
                logger.info("成功解析AI的答案。")
                return json_data
            except json.JSONDecodeError as e:
                logger.error(f"解析AI返回的JSON时失败: {e}")
                logger.error(f"尝试解析的字符串: {answer_content}")
                return None

        except Exception as e:
            logger.error(f"调用DeepSeek API时发生错误: {e}")
            return None
			

