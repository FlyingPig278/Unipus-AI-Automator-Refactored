# src/services/driver_service.py
import asyncio
from playwright.async_api import async_playwright, Playwright, Browser, Page, Error as PlaywrightError
from typing import List, Tuple
import src.config as config

class DriverService:
    """服务类，用于封装所有Playwright浏览器操作。"""

    def __init__(self):
        """初始化DriverService，设置基本属性。"""
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        print("Playwright驱动服务已初始化（尚未启动）。")

    async def start(self, headless=False):
        """启动Playwright，并创建一个新的浏览器页面。"""
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

    async def login(self):
        """执行完整的登录流程，并导航到课程列表页面。"""
        print("正在导航到登录页面...")
        await self.page.goto(config.LOGIN_URL)
        
        print("正在勾选用户协议...")
        await self.page.get_by_text("我已阅读并同意").click()

        print("正在输入凭据...")
        await self.page.get_by_placeholder("请输入用户名").fill(config.USERNAME)
        await self.page.get_by_placeholder("请输入密码").fill(config.PASSWORD)
        
        print("正在点击登录按钮...")
        await self.page.get_by_role("button", name="登录").click()
        
        try:
            await self.page.get_by_role("button", name="知道了").click(timeout=3000)
            print("已点击“知道了”弹窗。")
        except PlaywrightError:
            print("未找到“知道了”弹窗，跳过。")

        print("等待主页面加载...")
        try:
            await self.page.get_by_text("我的课程").click()
            print("已点击“我的课程”。")
        except PlaywrightError:
            print("错误：登录后未找到“我的课程”按钮，无法继续。")
            raise
            
        print("登录流程完毕。")

    async def get_course_list(self) -> list[str]:
        """获取“我的课程”页面上的所有课程名称。"""
        print("正在获取课程列表...")
        try:
            await self.page.locator(".course-name p").first.wait_for()
            course_names = await self.page.locator(".course-name p").all_text_contents()
            return [name.strip() for name in course_names if name.strip()]
        except PlaywrightError:
            print("错误：未能找到课程列表。")
            return []

    async def select_course_by_index(self, index: int):
        """根据索引点击指定的课程卡片。"""
        try:
            course_card_locator = self.page.locator(".course-card-stu").nth(index)
            print(f"正在进入第 {index + 1} 门课程...")
            await course_card_locator.click()
            await self.page.locator(config.UNIT_TABS).first.wait_for()
            print("已成功进入课程页面。")
        except PlaywrightError:
            print("错误：点击课程后，未能等到课程单元加载。")
            raise

    async def get_media_source_and_type(self) -> tuple[str | None, str | None]:
        """尝试在当前页面查找<audio>或<video>元素。"""
        try:
            media_locator = self.page.locator(config.MEDIA_SOURCE_ELEMENTS).first
            await media_locator.wait_for(timeout=3000)
            url = await media_locator.get_attribute('src')
            tag_name = await media_locator.evaluate('element => element.tagName.toLowerCase()')
            return url, tag_name
        except PlaywrightError:
            return None, None

    async def get_breadcrumb_parts(self) -> list[str]:
        """从页面提取完整路径信息。"""
        try:
            js_script = """
                () => {
                    const paths = [];
                    document.querySelectorAll('.pc-break-crumb-text').forEach(e => paths.push(e.textContent.trim()));
                    const activeTab = document.querySelector('.pc-header-tab-activity .pc-tab-view-container');
                    if (activeTab) paths.push(activeTab.textContent.trim());
                    const activeTask = document.querySelector('.pc-header-task-activity');
                    if (activeTask) paths.push(activeTask.textContent.trim());
                    return paths;
                }
            """
            return await self.page.evaluate(js_script)
        except Exception as e:
            print(f"提取完整目录树时发生错误: {e}")
            return []

    async def get_pending_tasks(self) -> list:
        """获取当前课程页面中所有未完成的必修任务。"""
        print("正在获取待完成任务列表...")
        pending_tasks = []
        current_course_url = self.page.url
        try:
            await self.page.locator(config.UNIT_TABS).first.wait_for()
            units_locators = await self.page.locator(config.UNIT_TABS).all()
        except PlaywrightError:
            print("未能定位到课程单元列表，请确保当前页面是课程主页。")
            return []

        for unit_locator in units_locators:
            unit_name = (await unit_locator.text_content()).strip().split('\n')[0]
            if "Test" in unit_name:
                print(f"检测到测试单元 '{unit_name}'，已跳过。")
                continue
            
            print(f"正在检查单元: {unit_name}")
            try:
                unit_index = await unit_locator.get_attribute("data-index")
                if "tabActive" not in (await unit_locator.get_attribute("class')):
                    await unit_locator.scroll_into_view_if_needed()
                    await unit_locator.click()
                    await expect(self.page.locator(f'[data-index="{unit_index}"]')).to_have_class(config.ACTIVE_UNIT_AREA)

                active_area_locator = self.page.locator(config.ACTIVE_UNIT_AREA)
                await active_area_locator.locator(config.TASK_ITEM_CONTAINER).first.wait_for()
                task_locators = await active_area_locator.locator(config.TASK_ITEM_CONTAINER).all()

                for i, task_locator in enumerate(task_locators):
                    text_content = await task_locator.text_content()
                    if "必修" in text_content and "已完成" not in text_content:
                        task_name = await task_locator.locator(config.TASK_ITEM_TYPE_NAME).text_content()
                        pending_tasks.append({
                            "unit_index": unit_index, "unit_name": unit_name,
                            "task_index": i, "task_name": task_name,
                            "course_url": current_course_url
                        })
            except Exception as e:
                print(f"处理单元 '{unit_name}' 时出错: {e}")
        print(f"待完成任务列表获取完毕，共 {len(pending_tasks)} 个任务。")
        return pending_tasks

    async def navigate_to_task(self, course_url: str, unit_index: str, task_index: int):
        """导航到指定单元和索引的任务页面。"""
        print(f"正在导航到单元 {unit_index}，任务索引 {task_index}...")
        await self.page.goto(course_url)
        try:
            unit_locator = self.page.locator(f'[data-index="{unit_index}"]')
            await unit_locator.scroll_into_view_if_needed()
            await unit_locator.click()
            await expect(self.page.locator(f'[data-index="{unit_index}"]')).to_have_class(config.ACTIVE_UNIT_AREA)
            
            task_locator = self.page.locator(config.ACTIVE_UNIT_AREA).locator(config.TASK_ITEM_CONTAINER).nth(task_index)
            await task_locator.click()
            print(f"已进入任务索引 {task_index} 的任务页面。")
            await self.handle_common_popups()
        except Exception as e:
            print(f"错误：在进入任务索引 {task_index} 时失败: {e}")
            raise
    
    async def handle_common_popups(self):
        """处理进入任务后常见的“我知道了”等弹窗。"""
        try:
            await self.page.get_by_role("button", name="我知道了").click(timeout=3000)
            print("已关闭“任务信息”弹窗。")
        except PlaywrightError:
            pass
        try:
            await self.page.locator(config.IKNOW_BUTTON).click(timeout=3000)
            print("已关闭“鼠标取词”提示。")
        except PlaywrightError:
            pass
            
    async def handle_submission_confirmation(self):
        """处理点击提交后的“最终确认”弹窗。"""
        try:
            await self.page.locator(config.SUBMIT_CONFIRMATION_BUTTON).click(timeout=3000)
            print("已点击“最终确认提交”弹窗。")
        except PlaywrightError:
            pass

    async def _navigate_to_answer_analysis_page(self):
        """从“答题小结”页面进入“答案解析”页面。"""
        print("正在导航到答案解析页面...")
        try:
            await self.page.locator(config.SUMMARY_QUESTION_NUMBER).first.click()
            await self.page.locator(config.QUESTION_WRAP).first.wait_for()
            print("已进入答案解析页面。")
        except PlaywrightError:
            print("错误：未能进入答案解析页面。")
            raise

    async def extract_all_correct_answers_from_analysis_page(self) -> list[dict]:
        """从答案解析页面提取所有正确答案。"""
        print("正在提取所有题目的正确答案...")
        extracted_answers = []
        try:
            question_wraps = await self.page.locator(config.QUESTION_WRAP).all()
            for wrap_locator in question_wraps:
                # 提取用于缓存键的文本
                title_text = await wrap_locator.locator(config.ANALYSIS_QUESTION_TITLE).text_content()
                option_text = await wrap_locator.locator(config.QUESTION_OPTION_WRAP).text_content()
                full_text = (title_text + " " + option_text).replace('\n', ' ').strip()
                
                correct_answer = await wrap_locator.locator(config.ANALYSIS_CORRECT_ANSWER_VALUE).text_content()
                
                if full_text and correct_answer:
                    extracted_answers.append({
                        'question_text': full_text,
                        'correct_answer': correct_answer.strip()
                    })
        except Exception as e:
            print(f"提取正确答案时发生错误: {e}")
        print(f"已提取 {len(extracted_answers)} 个正确答案。")
        return extracted_answers
