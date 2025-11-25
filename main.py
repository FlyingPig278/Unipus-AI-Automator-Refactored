# main.py
from src.services.driver_service import DriverService
import src.config as config
import time

def run_automator():
    """
    运行U校园AI自动答题程序的主函数。
    负责初始化服务、执行登录、并编排后续的自动化任务。
    """
    
    # 首先，检查必要的配置是否存在
    if not all([config.USERNAME, config.PASSWORD, config.DEEPSEEK_API_KEY]):
        print("错误：请确保您已经从 .env.example 复制创建了 .env 文件，")
        print("并在其中填写了您的 U_USERNAME, U_PASSWORD, 和 DEEPSEEK_API_KEY。")
        return

    browser_service = None
    try:
        # 1. 初始化浏览器服务
        # 如果不想看到浏览器界面，可以设置 headless=True
        browser_service = DriverService(headless=False)
        
        # 2. 执行登录
        browser_service.login()

        # --- 未来的步骤将在这里添加 ---
        print("\n登录成功。程序现在已准备好执行自动化任务。")
        print("后续工作：实现任务发现和策略执行。")
        # 3. 发现待办任务
        # tasks = browser_service.get_pending_tasks()
        
        # 4. 循环处理任务并应用正确的策略
        # for task in tasks:
        #     strategy = find_strategy_for_task(task)
        #     strategy.execute()
        
        # 保持浏览器开启一段时间以便检查
        time.sleep(5)

    except Exception as e:
        print(f"\n程序运行期间发生意外错误: {e}")
        # 在实际场景中，您可能希望有更详细的日志或错误报告
    finally:
        if browser_service:
            input("按回车键关闭浏览器...")
            browser_service.quit()

if __name__ == "__main__":
    run_automator()
