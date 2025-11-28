# src/services/driver_service.py
import asyncio
import re
import time
import os
from time import sleep
import base64 # 新增导入
import json # 新增导入
import urllib.parse # 新增导入
from playwright.async_api import async_playwright, Playwright, Browser, Page, expect, Error as PlaywrightError
from typing import List, Tuple

import src.config as config  # 导入我们的配置

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
        context = await self.browser.new_context()
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.page = await context.new_page()
        # self.page = await self.browser.new_page()
        self.page.set_default_timeout(30000) # 设置30秒默认超时
        print("Playwright浏览器和新页面已成功启动。")

    async def stop(self):
        """优雅地关闭浏览器和Playwright实例。"""
        print("正在关闭浏览器...")
        if self.page and self.page.context:
            print("正在保存Playwright追踪文件...")
            await self.page.context.tracing.stop(path="trace.zip")  # 保存追踪文件到项目根目录
            print("Playwright追踪文件已保存为 trace.zip。")
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
        await self.page.get_by_role("checkbox", name="我已阅读并同意").check()

        print("正在输入凭据...")
        await self.page.get_by_role("textbox", name="手机号/邮箱/用户名").fill(config.USERNAME)
        await self.page.get_by_role("textbox", name="密码").fill(config.PASSWORD)
        
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
            await self.page.locator(".course-name").first.wait_for() # 等待课程名称的父容器出现
            course_names = await self.page.locator(".course-name").all_text_contents()
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
            print(f"查找结果：{await media_locator.text_content()}")
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

    async def get_auth_info(self) -> dict:
        """
        通过拦截网络请求，从浏览器环境中获取动态的认证信息。
        """
        print("正在设置网络监听以捕获认证信息...")
        auth_info = {"Authorization": None, "userId": None, "auth_header": None}

        # 创建一个 Future 对象，用于在信息捕获后发出信号
        headers_found = asyncio.Future()

        def intercept_request(request):
            # 捕获 auth 头 (用于 soe/api)
            if "zt.unipus.cn/soe/api" in request.url and request.headers.get("auth"):
                if not auth_info["auth_header"]:
                    auth_info["auth_header"] = request.headers["auth"]
                    print("成功捕获 'auth' 头。")
            
            # 捕获 Authorization 头 (用于 ucontent.unipus.cn)
            if "ucontent.unipus.cn" in request.url and request.headers.get("authorization"):
                if not auth_info["Authorization"]:
                    auth_info["Authorization"] = request.headers["authorization"]
                    print("成功捕获 'Authorization' 头。")

            # 如果两个都找到了，就完成Future
            if auth_info["auth_header"] and auth_info["Authorization"] and not headers_found.done():
                headers_found.set_result(True)

        self.page.on("request", intercept_request)

        try:
            # 刷新页面以触发各种API请求，从而让我们的监听器捕获到所需信息
            print("将重新加载页面以触发网络请求...")
            await self.page.reload(wait_until="networkidle")
            
        except Exception as e:
            print(f"网络拦截或页面刷新时发生错误: {e}")
        
        self.page.remove_listener("request", intercept_request)

        # 尝试从Cookie中解析userId (优先级最高，因为用户确认了其可靠性)

        try:
            cookies = await self.page.context.cookies()
            for cookie in cookies:
                if cookie['name'] == 'sensorsdata2015jssdkcross':
                    # Cookie值是URL编码的JSON
                    decoded_cookie_value = urllib.parse.unquote(cookie['value'])
                    cookie_json = json.loads(decoded_cookie_value)
                    user_id_from_cookie = cookie_json.get("distinct_id") or cookie_json.get("$identity_login_id")
                    if user_id_from_cookie:
                        auth_info["userId"] = user_id_from_cookie
                        print("成功从sensorsdata2015jssdkcross Cookie中获取userId。")
                        break
        except Exception as e:
            print(f"从Cookie中解析userId时出错: {e}")

        # 如果仍然没有userId，尝试从localStorage获取作为最后的补充
        try:
            if not auth_info.get("userId"):
                user_id_from_ls = await self.page.evaluate("() => localStorage.getItem('openId') || (window.vuex_state && window.vuex_state.userId)")
                if user_id_from_ls:
                    auth_info["userId"] = user_id_from_ls
                    print("成功从localStorage获取userId。")
        except Exception:
            pass # 忽略错误

        print(f"获取到的认证信息: {auth_info}")
        if not all([auth_info["Authorization"], auth_info["auth_header"], auth_info["userId"]]):
             print("警告：未能获取到完整的认证信息，API调用可能会失败。")
             
        return auth_info

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
                if "tabActive" not in (await unit_locator.get_attribute("class")):
                    await unit_locator.scroll_into_view_if_needed()
                    await unit_locator.click()
                    await self.page.locator(f'[data-index="{unit_index}"][class*="tabActive"]').wait_for()

                active_area_locator = self.page.locator(config.ACTIVE_UNIT_AREA)
                await active_area_locator.locator(config.TASK_ITEM_CONTAINER).first.wait_for()
                task_locators = await active_area_locator.locator(config.TASK_ITEM_CONTAINER).all()

                for i, task_locator in enumerate(task_locators):
                    text_content = await task_locator.text_content()
                    # if "必修" in text_content and "已完成" not in text_content:
                    if True:
                        task_name = await task_locator.locator(config.TASK_ITEM_TYPE_NAME).text_content()
                        pending_tasks.append({
                            "unit_index": unit_index, "unit_name": unit_name,
                            "task_index": i, "task_name": task_name,
                            "course_url": current_course_url
                        })
            except Exception as e:
                print(f"处理单元 '{unit_name}' 时出错: {e}")
                if unit_name=='Unit 5':
                    raise
        print(f"待完成任务列表获取完毕，共 {len(pending_tasks)} 个任务。")
        return pending_tasks

    async def navigate_to_task(self, course_url: str, unit_index: str, task_index: int):
        """
        导航到指定单元和索引的任务页面，并在导航后处理常见弹窗。
        """
        print(f"正在导航到单元 {unit_index}，任务索引 {task_index}...")

        # 1. 重新回到课程主页，确保页面状态一致
        await self.page.goto(course_url)

        # 2. 定位并点击指定的单元
        try:
            unit_locator = self.page.locator(f'[data-index="{unit_index}"]')
            await unit_locator.scroll_into_view_if_needed()
            await unit_locator.click()
            # 兼容性：确保等待到正确的单元变为激活状态
            await self.page.locator(f'[data-index="{unit_index}"][class*="tabActive"]').wait_for()
            print(f"已确认单元 {unit_index} 已激活。")

        except PlaywrightError:
            print(f"错误：在导航到单元 {unit_index} 时超时，可能未找到单元或页面结构已更改。")
            raise
        except Exception as e:
            print(f"错误：在导航到单元 {unit_index} 时发生异常: {e}")
            raise

        # 3. 定位并点击指定的任务
        try:
            # 找到对应单元下的所有任务未在本页找到可用的音频或视频文件。项
            task_elements_locators = self.page.locator(f"{config.ACTIVE_UNIT_AREA} {config.TASK_ITEM_CONTAINER}")
            # 点击第 task_index 个任务
            await asyncio.sleep(0.3) # TODO:暂不明确应等待什么元素
            await task_elements_locators.nth(task_index).click()
            print(f"已进入任务索引 {task_index} 的任务页面。")

            # 等待题目加载标记，针对服务器不稳定，增加等待时间
            try:
                await self.page.wait_for_selector(config.QUESTION_LOADING_MARKER, timeout=20000)
            except PlaywrightError:
                print("警告: 任务页面加载后，未在20秒内找到题目加载标记。")

            # 调用通用的弹窗处理器
            await self.handle_common_popups()
        except Exception as e:
            print(f"错误：在进入任务索引 {task_index} 时失败: {e}")
            raise
    
    async def handle_common_popups(self):
        """处理进入任务后常见的弹窗，采用短超时优化。"""
        # 1. 快速处理“鼠标取词”引导 (如果存在)
        try:
            # 使用非常短的超时，如果弹窗在0.5秒内没出现，就立即跳过
            await self.page.locator(".iKnow").click(timeout=500)
            print("已关闭“鼠标取词”新手引导。")
        except PlaywrightError:
            pass  # 0.5秒内未找到，说明它不存在，直接继续

        # 2. 处理其他可能出现的、需要更长等待时间的弹窗
        try:
            await self.page.get_by_role("button", name="我知道了").click(timeout=3000)
            print("已关闭“任务信息”等弹窗。")
        except PlaywrightError:
            pass
			
            
    async def handle_submission_confirmation(self):
        """处理点击提交后的“最终确认”弹窗。"""
        try:
            await self.page.get_by_role("button", name="确定").click(timeout=500)
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
