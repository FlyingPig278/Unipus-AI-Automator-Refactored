import src.config as config
from rich.console import Console

# 创建一个全局的rich Console实例，用于统一的、美观的终端输出
# highlight=False 可以防止rich自动高亮代码中的关键字，保持原始输出
_console = Console(highlight=False)

class Logger:
    """
    一个简单的日志记录器，根据全局配置决定是否打印信息。
    主要用于在“静默全自动模式”下抑制不必要的输出，以保证进度条的清爽。
    """
    def info(self, message: str):
        """打印普通信息。在静默自动模式下会被抑制。"""
        if not (hasattr(config, 'IS_AUTO_MODE') and config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
            _console.print(message)

    def warning(self, message: str):
        """打印警告信息。警告信息总是显示。"""
        _console.print(f"[yellow]警告：{message}[/yellow]")

    def error(self, message: str):
        """打印错误信息。错误信息总是显示。"""
        _console.print(f"[bold red]错误：{message}[/bold red]")
    
    def success(self, message: str):
        """打印成功信息。在静默自动模式下会被抑制。"""
        if not (hasattr(config, 'IS_AUTO_MODE') and config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
            _console.print(f"[green]{message}[/green]")

    def always_print(self, message: str):
        """无视所有条件，总是打印信息。用于用户提示、最终结果等。"""
        _console.print(message)

# 创建一个全局单例
logger = Logger()