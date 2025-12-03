# src/config.py
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# --- Credentials and API Keys ---
USERNAME = os.getenv("U_USERNAME")
PASSWORD = os.getenv("U_PASSWORD")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# --- URLs ---
LOGIN_URL = "https://ucloud.unipus.cn/home"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# --- AI Models ---
WHISPER_MODEL = "base"
DEEPSEEK_CHAT_MODEL = "deepseek-chat"

# ==============================================================================
# 运行时配置
# ==============================================================================
FORCE_AI = False  # 如果为True，即使有缓存，也强制使用AI重新回答
AUTO_MODE_NO_CONFIRM = True # 如果为True，在全自动模式下，程序将不会等待用户确认，自动发送Prompt并提交答案
PROCESS_ONLY_INCOMPLETE_TASKS = True # 如果为True，程序将只处理“必修”且“未完成”的任务；如果为False，将处理所有“必修”任务
IS_AUTO_MODE = False # 运行时状态变量，由main.py在进入不同模式时动态设置

# --- CSS Selectors ---
# Course Page
UNIT_TABS = "[data-index]"
ACTIVE_UNIT_AREA = '[class*="unipus-tabs_itemActive"]'     # 激活单元的区域
TASK_ITEM_CONTAINER = '[class*="courses-unit_taskItemContainer"]' # 任务项容器
TASK_ITEM_TYPE_NAME = '[class*="courses-unit_taskTypeName"]'   # 任务项的类型名称

# Question Page
MEDIA_SOURCE_ELEMENTS = ".audio-material-wrapper audio, .video-material-wrapper video, .component-htmlview audio, .component-htmlview video" # 精确匹配作为问题材料的音频或视频

# HTTP Headers for requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 Edge/108.0.1462.54'
}

QUESTION_LOADING_MARKER = ".question-wrap"
QUESTION_WRAP = ".question-common-abs-reply" # 每个独立题目（含题目、选项和解析）的容器

# Answer Summary & Analysis Page
SUMMARY_QUESTION_NUMBER = ".answer-info .item-right"
