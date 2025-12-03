# src/config.py
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# --- Credentials and API Keys ---
USERNAME = os.getenv("U_USERNAME")
PASSWORD = os.getenv("U_PASSWORD")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# --- Paths ---
MANUAL_DRIVER_PATH = "./msedgedriver.exe"

# --- URLs ---
LOGIN_URL = "https://ucloud.unipus.cn/home"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# --- AI Models ---
WHISPER_MODEL = "base"
DEEPSEEK_CHAT_MODEL = "deepseek-chat"

# --- Debugging ---
# 如果设置为True，程序将忽略所有缓存，强制调用AI进行解答，方便调试Prompt。
FORCE_AI = True

# --- CSS Selectors ---
# Course Page
UNIT_TABS = "[data-index]"
ACTIVE_UNIT_AREA = '[class*="unipus-tabs_itemActive"]'     # 激活单元的区域
TASK_ITEM_CONTAINER = '[class*="courses-unit_taskItemContainer"]' # 任务项容器
TASK_ITEM_TYPE_NAME = '[class*="courses-unit_taskTypeName"]'   # 任务项的类型名称

# Question Page
BREADCRUMB_TEXT_ELEMENTS = ".pc-break-crumb .pc-break-crumb-text"
MEDIA_SOURCE_ELEMENTS = ".audio-material-wrapper audio, .video-material-wrapper video, .component-htmlview audio, .component-htmlview video" # 精确匹配作为问题材料的音频或视频

# HTTP Headers for requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 Edge/108.0.1462.54'
}

QUESTION_LOADING_MARKER = ".question-wrap"
SUBMIT_BUTTON = ".btn"
QUESTION_WRAP = ".question-common-abs-reply" # 每个独立题目（含题目、选项和解析）的容器

# Answer Summary & Analysis Page
SUMMARY_QUESTION_NUMBER = ".answer-info .item-right"
ANALYSIS_QUESTION_TITLE = ".ques-title"
QUESTION_OPTION_WRAP = ".option-wrap"
ANALYSIS_CORRECT_ANSWER_VALUE = ".analysis-item:has(.analysis-item-title:has-text('正确答案：')) .component-htmlview"
