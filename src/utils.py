import logging
import os

from rich.console import Console
from rich.logging import RichHandler

# 定义日志目录和文件名
LOG_DIR = ".logs"
os.makedirs(LOG_DIR, exist_ok=True) # 确保日志目录存在

DEBUG_LOG_FILE = os.path.join(LOG_DIR, "app_debug.log")
INFO_LOG_FILE = os.path.join(LOG_DIR, "app_info.log")


# 1. 创建一个 console 实例，并强制启用终端模式，以确保在 PyCharm 等环境中颜色正常显示。
#    这个 console 对象也会被 main.py 中的进度条使用，以确保它们在同一个输出上同步。
console = Console(highlight=False, force_terminal=True)

# 2. 配置 RichHandler，使其使用我们创建的 console。
#    - rich_tracebacks=True 能够在出现异常时打印带语法高亮的美观回溯信息。
# - show_path=False 可以让日志消息更简洁，不显示文件路径。
# - markup=True 允许日志消息中的 [color]...[/color] 标记被解析为颜色。
rich_handler = RichHandler(
    console=console,
    rich_tracebacks=True,
    show_path=False,
    markup=True
)
rich_handler.setLevel(logging.INFO)

# 3. 配置 FileHandler for DEBUG level
debug_file_handler = logging.FileHandler(DEBUG_LOG_FILE, encoding='utf-8')
debug_file_handler.setLevel(logging.DEBUG)
debug_file_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
debug_file_handler.setFormatter(debug_file_formatter)

# 4. 配置 FileHandler for INFO level
info_file_handler = logging.FileHandler(INFO_LOG_FILE, encoding='utf-8')
info_file_handler.setLevel(logging.INFO)
info_file_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
info_file_handler.setFormatter(info_file_formatter)

# 5. 获取根记录器并添加所有处理程序
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG) # 设置根记录器级别为DEBUG，以捕获所有消息

# 清除basicConfig可能添加的默认handler，以避免重复
if root_logger.handlers:
    for handler_to_remove in root_logger.handlers[:]:
        root_logger.removeHandler(handler_to_remove)

root_logger.addHandler(rich_handler)
root_logger.addHandler(debug_file_handler)
root_logger.addHandler(info_file_handler)

# 6. 获取一个名为当前模块的 logger 实例
_logger = logging.getLogger(__name__)

# 7. 创建一个适配器类，以保持与旧的自定义 Logger 类的方法签名和行为兼容。
#    这避免了在所有策略文件中重构 logger 调用的需要。
class LoggerAdapter:
    def debug(self, message: str):
        """记录调试信息。"""
        _logger.debug(message)

    def info(self, message: str):
        """记录普通信息。"""
        # 移除旧的条件检查，因为 RichHandler 会自动处理与进度条的冲突。
        _logger.info(message)

    def warning(self, message: str):
        """记录警告信息。RichHandler 会自动将其着色为黄色。"""
        _logger.warning(f"警告：{message}")

    def error(self, message: str):
        """记录错误信息。RichHandler 会自动将其着色为红色。"""
        _logger.error(f"错误：{message}")
    
    def success(self, message: str):
        """记录成功信息，使用 rich 的标记语法实现绿色文本。"""
        _logger.info(f"[green]{message}[/green]")

    def always_print(self, message: str):
        """
        在新的配置下，所有 INFO 级别的日志都会被 RichHandler 正确处理，
        所以这个方法现在等同于 info()。
        """
        _logger.info(message)

# 8. 创建一个全局的 logger 单例，供整个应用程序导入和使用。
logger = LoggerAdapter()