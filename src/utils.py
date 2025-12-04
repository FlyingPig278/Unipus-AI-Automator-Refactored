import logging

from rich.console import Console
from rich.logging import RichHandler

# 1. 创建一个 console 实例，并强制启用终端模式，以确保在 PyCharm 等环境中颜色正常显示。
#    这个 console 对象也会被 main.py 中的进度条使用，以确保它们在同一个输出上同步。
console = Console(highlight=False, force_terminal=True)

# 2. 配置 RichHandler，使其使用我们创建的 console。
#    - rich_tracebacks=True 能够在出现异常时打印带语法高亮的美观回溯信息。
# - show_path=False 可以让日志消息更简洁，不显示文件路径。
# - markup=True 允许日志消息中的 [color]...[/color] 标记被解析为颜色。
handler = RichHandler(
    console=console,
    rich_tracebacks=True,
    show_path=False,
    markup=True
)

# 3. 为Python的根记录器（root logger）进行基础配置。
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",  # RichHandler 会使用自己的时间格式，这里是为其他可能的 handler 准备的
    handlers=[handler]
)

# 4. 获取一个名为 "rich" 的 logger 实例，应用程序的其他部分将通过它来记录日志。
_logger = logging.getLogger("rich")

# 5. 创建一个适配器类，以保持与旧的自定义 Logger 类的方法签名和行为兼容。
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
        _logger.warning(f"警告：{message}"
                        f"")

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

# 6. 创建一个全局的 logger 单例，供整个应用程序导入和使用。
logger = LoggerAdapter()