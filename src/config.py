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
# Login Page
LOGIN_USERNAME_INPUT = "input[name='username']"
LOGIN_PASSWORD_INPUT = "input[name='password']"
LOGIN_BUTTON = "button#login"
LOGIN_SUCCESS_POPUP_BUTTON = ".layui-layer-btn0"
LOGIN_COURSE_ENTRY_BUTTON = ".ucm-ant-btn.ucm-ant-btn-round.ucm-ant-btn-primary"

# Anti-cheat popup
ANTI_CHEAT_POPUP_BUTTON = ".pop-up_pop-up-modal-cheat-notice-content-botton__iS8oJ"

# Course Page
UNIT_TABS = "[data-index]"
ACTIVE_UNIT_AREA = ".unipus-tabs_itemActive__x0WVI"
TASK_ITEM_CONTAINER = ".courses-unit_taskItemContainer__gkVix"
TASK_ITEM_TYPE_NAME = ".courses-unit_taskTypeName__99BXj"

# Question Page
QUESTION_LOADING_MARKER = ".abs-direction"
IKNOW_POPUP_BUTTON = ".iKnow"
CONFIRM_POPUP_BUTTON = ".ant-btn.ant-btn-primary"
SUBMIT_BUTTON = ".btn"
SUBMIT_CONFIRM_BUTTON = ".ant-btn-primary"
REPLY_AREA_CONTAINER = ".layout-reply-container"
VIDEO_PLAYER_BOX = ".video-box"
