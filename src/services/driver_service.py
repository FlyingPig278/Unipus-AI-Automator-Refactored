# src/services/driver_service.py
import time
import os
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

import src.config as config  # 导入我们的配置

class DriverService:
    """服务类，用于封装所有Selenium浏览器操作。"""

    def __init__(self, headless=False):
        """
        初始化Edge浏览器和WebDriverWait。
        采用“本地优先”策略加载驱动，提高在网络不佳环境下的启动速度和稳定性。
        """
        print("正在初始化浏览器驱动...")
        options = webdriver.EdgeOptions()
        if headless:
            options.add_argument("--headless")
        # 抑制过多的日志输出
        options.add_argument("--disable-logging")
        options.add_argument("--log-level=3")
        
        service = None
        # 步骤 1: 优先检查本地是否存在驱动文件
        print(f"正在检查本地驱动路径: {config.MANUAL_DRIVER_PATH}")
        if os.path.exists(config.MANUAL_DRIVER_PATH):
            print("检测到本地驱动文件，将直接使用。")
            service = EdgeService(executable_path=config.MANUAL_DRIVER_PATH, log_output=os.devnull)
        else:
            # 步骤 2: 如果本地没有，则尝试从网络下载
            print("未找到本地驱动，尝试从网络自动下载...")
            try:
                service = EdgeService(EdgeChromiumDriverManager().install(), log_output=os.devnull)
                print("驱动自动下载并配置成功。")
            except Exception as e:
                # 步骤 3: 如果网络下载也失败，则提示用户手动操作
                print("\n--- 自动下载驱动失败 ---")
                print(f"错误信息: {e}")
                print("\n请按以下步骤手动配置:")
                print("1. 查看您的Edge浏览器版本 (在地址栏输入: edge://settings/help)。")
                print("2. 访问 https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/ 下载对应的驱动版本。")
                print(f"3. 将下载的 'msedgedriver.exe' 文件放置在项目根目录下的这个位置: {config.MANUAL_DRIVER_PATH}")
                print("配置完成后，请重新运行本程序。")
                raise  # 终止程序运行，因为没有可用的驱动

        self.driver = webdriver.Edge(service=service, options=options)
        self.wait = WebDriverWait(self.driver, 10)
        self.short_wait = WebDriverWait(self.driver, 3)
        print("浏览器驱动初始化完毕。")

    def _click(self, by, value, wait_condition=EC.element_to_be_clickable):
        """辅助方法：等待并点击一个元素。"""
        element = self.wait.until(wait_condition((by, value)))
        element.click()

    def _send_keys(self, by, value, keys):
        """辅助方法：等待并向一个元素发送按键。"""
        element = self.wait.until(EC.visibility_of_element_located((by, value)))
        element.send_keys(keys)
        
    def login(self):
        """执行完整的登录流程。"""
        print("正在导航到登录页面...")
        self.driver.get(config.LOGIN_URL)
        
        print("正在输入凭据...")
        self._send_keys(By.CSS_SELECTOR, config.LOGIN_USERNAME_INPUT, config.USERNAME)
        self._send_keys(By.CSS_SELECTOR, config.LOGIN_PASSWORD_INPUT, config.PASSWORD)
        
        print("正在点击登录按钮...")
        self._click(By.CSS_SELECTOR, config.LOGIN_BUTTON)
        
        # 处理登录后的弹窗和导航
        try:
            self._click(By.CSS_SELECTOR, config.LOGIN_SUCCESS_POPUP_BUTTON)
            self._click(By.CSS_SELECTOR, config.LOGIN_COURSE_ENTRY_BUTTON)
        except TimeoutException:
            print("未能找到标准的登录后弹窗，可能已登录或页面结构已更改。")
            # 在这里优雅地失败或等待下一个页面标记是更好的选择
            
        # 处理可选的反作弊弹窗
        try:
            # 对可选元素使用较短的等待时间
            anti_cheat_button = self.short_wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, config.ANTI_CHEAT_POPUP_BUTTON)))
            anti_cheat_button.click()
            print("已关闭反作弊提示。")
        except TimeoutException:
            print("未找到反作弊提示，跳过。")
            
        print("登录流程完毕。")

    def quit(self):
        """退出浏览器。"""
        print("正在关闭浏览器。")
        self.driver.quit()
