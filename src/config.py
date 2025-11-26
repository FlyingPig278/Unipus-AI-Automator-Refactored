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

# --- CSS Selectors ---
# Login Page & Main Navigation
AGREEMENT_CHECKBOX = ".help-block input[type='checkbox']"
LOGIN_USERNAME_INPUT = "input[name='username']"
LOGIN_PASSWORD_INPUT = "input[name='password']"
LOGIN_BUTTON = "button#login"
LOGIN_SUCCESS_POPUP_BUTTON = ".layui-layer-btn0"
MY_COURSES_BUTTON = "#root > section > aside > div > div > div:nth-child(2)" # “我的课程”按钮，使用精确路径
COURSE_CARD_CONTAINER = ".ant-card" # 课程卡片容器
COURSE_NAME_IN_CARD = ".course-name p"       # 课程卡片内的课程名称

# Anti-cheat popup (Removed, as per user feedback)
# A new "Got It" popup is handled instead
GOT_IT_POPUP_BUTTON = ".pop-up_pop-up-never-pop__sCWeI button"

# Course Page
UNIT_TABS = "[data-index]"
ACTIVE_UNIT_AREA = '[class*="unipus-tabs_itemActive"]'     # 激活单元的区域
TASK_ITEM_CONTAINER = '[class*="courses-unit_taskItemContainer"]' # 任务项容器
TASK_ITEM_TYPE_NAME = '[class*="courses-unit_taskTypeName"]'   # 任务项的类型名称

# Question Page
BREADCRUMB_TEXT_ELEMENTS = ".pc-break-crumb .pc-break-crumb-text"
AUDIO_SOURCE_ELEMENT = "audio"
VIDEO_SOURCE_ELEMENT = "video"
MEDIA_SOURCE_ELEMENTS = "audio, video" # 组合选择器，用于同时查找音频和视频

# HTTP Headers for requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 Edge/108.0.1462.54'
}

IKNOW_BUTTON = ".iKnow"  # 通用的“我知道了”按钮
SYSTEM_OK_BUTTON = ".system-info-cloud-ok-button" # antd风格弹窗的“OK”按钮
SUBMIT_CONFIRMATION_BUTTON = ".system-info-cloud-ok-button" # 提交确认弹窗的“确定”按钮，是上面SYSTEM_OK_BUTTON的一个别名
QUESTION_LOADING_MARKER = ".question-wrap"
SUBMIT_BUTTON = ".btn"
PRIMARY_ANT_BUTTON = ".ant-btn.ant-btn-primary" # 通用的 antd 主要按钮
REPLY_AREA_CONTAINER = ".layout-reply-container"
QUESTION_WRAP = ".question-common-abs-reply" # 每个独立题目（含题目、选项和解析）的容器
VIDEO_PLAYER_BOX = ".video-box"

# Answer Summary & Analysis Page
SUMMARY_QUESTION_NUMBER = ".answer-info .item-right"
ANALYSIS_QUESTION_TITLE = ".ques-title"
QUESTION_OPTION_WRAP = ".option-wrap"
ANALYSIS_CORRECT_ANSWER_VALUE = ".analysis-item-title + .analysis-item-content .component-htmlview"
