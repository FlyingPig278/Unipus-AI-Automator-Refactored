# src/services/driver_service.py
import time
import os
from time import sleep
from playwright.async_api import async_playwright, Playwright, Browser, Page, expect
from typing import List, Tuple

# Playwright有自己的异常类，不再需要Selenium的
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError # Playwright的TimeoutError，用作PlaywrightTimeoutError

import src.config as config  # 导入我们的配置

class DriverService:
    """服务类，用于封装所有Selenium浏览器操作。"""

    def __init__(self):
        """初始化DriverService，设置基本属性。"""
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        print("Playwright驱动服务已初始化（尚未启动）。")

    async def start(self, headless=False):
        """
        启动Playwright，并创建一个新的浏览器页面。
        """
        print("正在启动Playwright浏览器...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=headless)
        self.page = await self.browser.new_page()
        self.page.set_default_timeout(30000) # 设置30秒默认超时
        print("Playwright浏览器和新页面已成功启动。")

    async def stop(self):
        """优雅地关闭浏览器和Playwright实例。"""
        print("正在关闭浏览器...")
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("浏览器已关闭。")

    async def _click(self, selector: str):
        """辅助方法：点击一个元素。"""
        await self.page.click(selector)

    async def _send_keys(self, selector: str, keys: str):
        """辅助方法：向一个元素发送按键。"""
        await self.page.fill(selector, keys)
        
    async def login(self):
        """执行完整的登录流程，并导航到课程列表页面。"""
        print("正在导航到登录页面...")
        await self.page.goto(config.LOGIN_URL)
        
        print("正在勾选用户协议...")
        await self._click(config.AGREEMENT_CHECKBOX)

        print("正在输入凭据...")
        await self._send_keys(config.LOGIN_USERNAME_INPUT, config.USERNAME)
        await self._send_keys(config.LOGIN_PASSWORD_INPUT, config.PASSWORD)
        
        print("正在点击登录按钮...")
        await self._click(config.LOGIN_BUTTON)
        
        # 处理“知道了”弹窗，这个弹窗会拦截后续的点击
        try:
            await self.page.click(config.GOT_IT_POPUP_BUTTON, timeout=3000) # Playwright的click方法会自动等待，timeout直接传给click
            print("已点击“知道了”弹窗。")
        except PlaywrightTimeoutError:
            print("未找到“知道了”弹窗，跳过。")

        # 这里我们不再依赖固定的弹窗，而是等待“我的课程”按钮出现
        print("等待主页面加载...")
        try:
            # Playwright会自动等待元素出现
            await self.page.click(config.MY_COURSES_BUTTON)
            print("已点击“我的课程”。")
        except PlaywrightTimeoutError:
            print("错误：登录后未找到“我的课程”按钮，无法继续。请检查页面或选择器。")
            raise
            
        print("登录流程完毕。")

    def get_course_list(self) -> list[str]:
        """
        获取“我的课程”页面上的所有课程名称。

        Returns:
            list[str]: 包含所有课程名称字符串的列表。
        """
        print("正在获取课程列表...")
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, config.COURSE_CARD_CONTAINER)))
            course_elements = self.driver.find_elements(By.CSS_SELECTOR, config.COURSE_NAME_IN_CARD)
            course_names = [elem.text for elem in course_elements if elem.text]
            print(f"成功获取到 {len(course_names)} 门课程。")
            return course_names
        except TimeoutException:
            print("错误：未能找到课程列表容器，请检查选择器或确保已在正确的页面。")
            return []

    def select_course_by_index(self, index: int):
        """
        根据索引点击指定的课程卡片。

        Args:
            index (int): 用户选择的课程索引（从0开始）。
        """
        try:
            course_cards = self.driver.find_elements(By.CSS_SELECTOR, config.COURSE_CARD_CONTAINER)
            if 0 <= index < len(course_cards):
                print(f"正在进入第 {index + 1} 门课程...")
                # 使用JS点击，以应对点击被拦截等疑难杂症
                self.driver.execute_script("arguments[0].click();", course_cards[index])
                # 等待课程页面加载完成
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, config.UNIT_TABS)))
                print("已成功进入课程页面。")
            else:
                print(f"错误：选择的课程索引 {index} 无效。")
                raise IndexError("课程选择索引超出范围")
        except TimeoutException:
            print("错误：点击课程后，未能等到课程单元加载。页面可能已更改。")
            raise

    def get_media_source_and_type(self) -> tuple[str | None, str | None]:
        """
        尝试在当前页面查找<audio>或<video>元素，并返回其源URL和标签类型。
        这是一个非阻塞方法，如果找不到元素则返回(None, None)。
        """
        try:
            media_element = self.short_wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, config.MEDIA_SOURCE_ELEMENTS))
            )
            url = media_element.get_attribute('src')
            tag_name = media_element.tag_name # "audio" or "video"
            return url, tag_name
        except TimeoutException:
            return None, None

    async def get_element_text(self, selector: str) -> str:
        """辅助方法：获取一个元素的文本内容。"""
        return await self.page.text_content(selector)
    
    def get_breadcrumb_parts(self) -> list[str]:
        """
        从页面提取完整路径信息：面包屑 -> 激活的Tab -> 激活的Task。

        Returns:
            list[str]: 包含各级导航文本的列表。
            例如: ["大学英语听说教程...", "College life...", "8-5...", "Conversation 1", "Conversation 1-1"]
        """
        try:
            # 我们在一个 JS 执行中完成所有提取，减少与浏览器的交互次数，提高效率
            js_script = """
                const paths = [];

                // 1. 获取顶部的标准面包屑
                // 根据你的HTML，类名为 .pc-break-crumb-text
                const breadcrumbElems = document.querySelectorAll('.pc-break-crumb-text');
                breadcrumbElems.forEach(elem => {
                    if (elem.textContent) {
                        paths.push(elem.textContent.trim());
                    }
                });

                // 2. 获取激活的 Tab (Conversation 1 等)
                // 选择器定位到具有 'pc-header-tab-activity' 类的父元素，再找里面的文字容器
                const activeTab = document.querySelector('.pc-header-tab-activity .pc-tab-view-container');
                if (activeTab && activeTab.textContent) {
                    paths.push(activeTab.textContent.trim());
                }

                // 3. 获取激活的 Task (Conversation 1-1 等)
                // 选择器定位到具有 'pc-header-task-activity' 类的元素
                const activeTask = document.querySelector('.pc-header-task-activity');
                if (activeTask && activeTask.textContent) {
                    paths.push(activeTask.textContent.trim());
                }

                return paths;
            """

            full_path = self.driver.execute_script(js_script)
            return full_path

        except Exception as e:
            print(f"提取完整目录树时发生错误: {e}")
            return []

    def get_pending_tasks(self) -> list:
        """
        获取当前课程页面中所有未完成的必修任务。
        融合了用户建议的改进版：
        1. 使用JS点击和获取文本，解决窄屏/滚动条导致元素不可见的问题。
        2. 每次循环重新查找元素，防止 DOM 刷新导致的 StaleElementReferenceException。
        3. 检查单元是否已激活，避免不必要的点击。
        """
        print("正在获取待完成任务列表...")
        pending_tasks = []
        current_course_url = self.driver.current_url

        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, config.UNIT_TABS)))
            units_count = len(self.driver.find_elements(By.CSS_SELECTOR, config.UNIT_TABS))
        except TimeoutException:
            print("未能定位到课程单元列表，请确保当前页面是课程主页。")
            return []
        except Exception as e:
            print(f"获取单元数量时出错: {e}")
            return []

        for i in range(units_count):
            unit_name = ""  # 在循环开始时初始化
            try:
                # 【关键】每次循环重新获取最新的元素列表
                current_units = self.driver.find_elements(By.CSS_SELECTOR, config.UNIT_TABS)
                if i >= len(current_units):
                    print(f"警告：单元列表在循环中发生变化，提前结束。")
                    break
                
                unit_element = current_units[i]
                unit_index = unit_element.get_attribute("data-index")

                # 【关键】使用 JS 获取文本
                unit_name = self.driver.execute_script("return arguments[0].textContent;", unit_element).strip().split('\n')[0]

                if "Test" in unit_name:
                    print(f"检测到测试单元 '{unit_name}'，已跳过。")
                    continue
                
                print(f"正在检查单元: {unit_name}")

                # 检查单元是否已激活
                is_already_active = "tabActive" in unit_element.get_attribute("class")

                if not is_already_active:
                    # 【关键】使用 JS 强制点击
                    self.driver.execute_script("arguments[0].click();", unit_element)
                    # 使用精确等待代替固定 sleep
                    self.wait.until(
                        EC.text_to_be_present_in_element_attribute(
                            (By.CSS_SELECTOR, f'[data-index="{unit_index}"]'), 'class', 'tabActive'
                        )
                    )
                else:
                    print(f"单元 '{unit_name}' 当前已激活，无需点击切换。")

                # --- 抓取任务的逻辑 (采用更精确的等待策略) ---
                try:
                    # 1. 定义第一个任务项的选择器
                    first_task_locator = (By.CSS_SELECTOR, f"{config.ACTIVE_UNIT_AREA} {config.TASK_ITEM_CONTAINER}")
                    
                    # 2. 等待第一个任务项的容器出现
                    self.wait.until(EC.presence_of_element_located(first_task_locator))

                    # 3. 【关键】等待第一个任务项的文本内容被完整渲染（以出现“必修”为标志）
                    self.wait.until(EC.text_to_be_present_in_element(first_task_locator, "必修"))
                    
                    # 4. 现在可以安全地获取所有任务
                    task_elements = self.driver.find_elements(By.CSS_SELECTOR, f"{config.ACTIVE_UNIT_AREA} {config.TASK_ITEM_CONTAINER}")
                    
                    # 5. 使用最终获取的 task_elements 列表进行处理
                    for index, task_element in enumerate(task_elements):
                        text_content = task_element.text
                        if "必修" in text_content and "已完成" not in text_content:
                            try:
                                task_name = task_element.find_element(By.CSS_SELECTOR, config.TASK_ITEM_TYPE_NAME).text
                                pending_tasks.append({
                                    "unit_index": unit_index,
                                    "unit_name": unit_name,
                                    "task_index": index, 
                                    "task_name": task_name,
                                    "course_url": current_course_url
                                })
                            except NoSuchElementException:
                                print(f"警告: 单元 '{unit_name}' 的任务 {index} 未能找到任务名称。")
                except TimeoutException:
                    print(f"单元 '{unit_name}' 内容区域已加载，但未在规定时间内发现任何任务项或任务状态文本。")
                    continue

            except StaleElementReferenceException:
                print(f"警告: 处理单元 '{unit_name}' (索引 {i}) 时页面元素已刷新，跳过本轮...")
                continue
            except Exception as e:
                print(f"错误: 在处理单元 '{unit_name}' (索引 {i}) 时发生异常: {e}")
                continue

        print(f"待完成任务列表获取完毕，共 {len(pending_tasks)} 个任务。")
        return pending_tasks

    def _navigate_to_answer_analysis_page(self):
        """
        从“答题小结”页面点击第一个题号，进入“答案解析”页面。
        """
        print("正在导航到答案解析页面...")
        try:
            # 等待答题小结页面加载
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, config.SUMMARY_QUESTION_NUMBER)))
            
            # 点击第一个题号即可显示所有题的解析
            first_question_number = self.driver.find_element(By.CSS_SELECTOR, config.SUMMARY_QUESTION_NUMBER)
            self.driver.execute_script("arguments[0].click();", first_question_number)
            
            # 等待答案解析页面加载完成（例如等待第一个题目解析的出现）
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, config.QUESTION_WRAP)))
            print("已进入答案解析页面。")
        except TimeoutException:
            print("错误：未能进入答案解析页面，可能未找到题号或页面结构已改变。")
        except Exception as e:
            print(f"导航到答案解析页面时发生错误: {e}")

    def extract_all_correct_answers_from_analysis_page(self) -> list[dict]:
        """
        从当前“答案解析”页面提取所有题目的文本和正确答案。
        
        Returns:
            list[dict]: 包含每个题目的字典列表，例如：
                        [{'question_text': '...', 'correct_answer': 'A'}, ...]
        """
        print("正在提取所有题目的正确答案...")
        extracted_answers = []
        try:
            # 获取所有题目解析的容器
            question_analysis_wraps = self.driver.find_elements(By.CSS_SELECTOR, config.QUESTION_WRAP)
            
            for wrap_element in question_analysis_wraps:
                # 使用新的辅助方法精确提取题目标题和选项文本，用于缓存键
                question_text_for_cache = self._get_full_question_text_for_caching(wrap_element)
                
                # 在当前区块内找到正确答案
                correct_answer_elem = wrap_element.find_element(By.CSS_SELECTOR, config.ANALYSIS_CORRECT_ANSWER_VALUE)
                correct_answer = correct_answer_elem.text.strip()

                if question_text_for_cache and correct_answer:
                    extracted_answers.append({
                        'question_text': question_text_for_cache,
                        'correct_answer': correct_answer
                    })
        except Exception as e:
            print(f"提取正确答案时发生错误: {e}")
        
        print(f"已提取 {len(extracted_answers)} 个正确答案。")
        return extracted_answers

    def handle_common_popups(self):
        """处理进入任务后常见的“我知道了”等弹窗。"""
        try:
            self.short_wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
                                                              config.IKNOW_BUTTON))).click()
            print("已关闭“我知道了”提示。")
        except TimeoutException:
            pass  # 找不到就算了

        try:
            self.short_wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, config.SYSTEM_OK_BUTTON))).click()
            print("已关闭“系统信息”弹窗。")
        except TimeoutException:
            pass  # 找不到就算了

    def handle_submission_confirmation(self):
        """处理点击提交后的“最终确认”弹窗。"""
        try:
            self.short_wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, config.SUBMIT_CONFIRMATION_BUTTON))
            ).click()
            print("已点击“最终确认提交”弹窗。")
        except TimeoutException:
            pass # 找不到就算了

    def navigate_to_task(self, course_url: str, unit_index: str, task_index: int):
        """
        导航到指定单元和索引的任务页面，并在导航后处理常见弹窗。
        采用JS点击，确保导航的健壮性。
        """
        print(f"正在导航到单元 {unit_index}，任务索引 {task_index}...")

        # 1. 重新回到课程主页，确保页面状态一致
        self.driver.get(course_url)

        # 2. 定位并点击指定的单元
        try:
            # 等待所有单元标签加载
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, config.UNIT_TABS)))
            
            # 精确找到需要点击的单元
            unit_to_click = self.driver.find_element(By.CSS_SELECTOR, f'[data-index="{unit_index}"]')
            
            # 滚动到视图并用JS点击
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", unit_to_click)
            time.sleep(0.3)
            self.driver.execute_script("arguments[0].click();", unit_to_click)

            # 【关键修复】精确等待被点击的单元高亮
            self.wait.until(
                EC.text_to_be_present_in_element_attribute(
                    (By.CSS_SELECTOR, f'[data-index="{unit_index}"]'), 'class', 'tabActive'
                )
            )
            print(f"已确认单元 {unit_index} 已激活。")

        except Exception as e:
            print(f"错误：在导航到单元 {unit_index} 时失败: {e}")
            raise

        # 3. 定位并点击指定的任务
        try:
            active_unit_area = self.driver.find_element(By.CSS_SELECTOR, config.ACTIVE_UNIT_AREA)
            task_elements = active_unit_area.find_elements(By.CSS_SELECTOR, config.TASK_ITEM_CONTAINER)

            if task_index < len(task_elements):
                task_to_click = task_elements[task_index]
                
                # 【关键修复】在点击前，明确等待目标任务元素变为可点击状态
                self.wait.until(EC.element_to_be_clickable(task_to_click))
                
                # 使用JS点击任务，确保稳定
                sleep(0.3)
                self.driver.execute_script("arguments[0].click();", task_to_click)
                print(f"已进入任务索引 {task_index} 的任务页面。")

                # 等待题目加载标记，针对服务器不稳定，增加等待时间
                try:
                    WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, config.QUESTION_LOADING_MARKER)))
                except TimeoutException:
                    print("警告: 任务页面加载后，未在20秒内找到题目加载标记。")

                # 调用通用的弹窗处理器
                self.handle_common_popups()
            else:
                raise ValueError(f"任务索引 {task_index} 超出单元 {unit_index} 的任务范围。")
        except Exception as e:
            print(f"错误：在进入任务索引 {task_index} 时失败: {e}")
            raise
        
    def quit(self):
        """退出浏览器。"""
        print("正在关闭浏览器。")
        self.driver.quit()
