# src/services/driver_service.py
import asyncio
import html
import json  # 新增导入
import urllib.parse  # 新增导入

from playwright.async_api import async_playwright, Playwright, Browser, Page, Locator, Error as PlaywrightError

import src.config as config  # 导入我们的配置
from src.utils import logger


class RateLimitException(Exception):
    """自定义异常，在检测到服务器速率限制时抛出。"""
    pass


class InvalidCredentialsException(Exception):
    """自定义异常，在检测到用户名或密码错误时抛出。"""
    pass


class DriverService:
    """服务类，用于封装所有Playwright浏览器操作。"""

    def __init__(self):
        """初始化DriverService，设置基本属性。"""
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        logger.info("Playwright驱动服务已初始化（尚未启动）。")

    async def start(self, headless=False):
        """启动Playwright，并创建一个新的浏览器页面。"""
        logger.info("正在启动Playwright浏览器...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=headless)
        # 在创建上下文时直接授予麦克风权限
        context = await self.browser.new_context(permissions=['microphone'])
        # await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.page = await context.new_page()
        # self.page = await self.browser.new_page()
        self.page.set_default_timeout(30000) # 设置30秒默认超时
        logger.info("Playwright浏览器和新页面已成功启动。")

    async def stop(self):
        """优雅地关闭浏览器和Playwright实例。"""
        logger.info("正在关闭浏览器...")
        # if self.page and self.page.context:
        #     logger.info("正在保存Playwright追踪文件...")
        #     await self.page.context.tracing.stop(path="trace.zip")  # 保存追踪文件到项目根目录
        #     logger.info("Playwright追踪文件已保存为 trace.zip。")
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("浏览器已关闭。")

    async def login(self):
        """
        执行完整的登录流程，处理凭据、验证码和各种登录后状态。
        """
        logger.info("正在开始登录流程...")
        await self._navigate_and_fill_form()
        
        # 首次点击登录
        await self.page.get_by_role("button", name="登录").click()
        logger.info("已点击登录，正在判断响应结果...")

        await self._handle_initial_login_response()
        logger.info("登录流程成功结束。")

    async def _navigate_and_fill_form(self):
        """导航到登录页并填写表单。"""
        logger.info("正在导航到登录页面...")
        await self.page.goto(config.LOGIN_URL, timeout=60000)
        
        logger.info("正在勾选用户协议...")
        await self.page.get_by_role("checkbox", name="我已阅读并同意").check()

        logger.info("正在输入凭据...")
        await self.page.get_by_role("textbox", name="手机号/邮箱/用户名").fill(config.USERNAME)
        await self.page.get_by_role("textbox", name="密码").fill(config.PASSWORD)

    async def _handle_initial_login_response(self):
        """
        处理首次登录点击后的响应，通过并行等待任务来区分验证码、成功或失败。
        这种方法可以避免 Playwright 的 strict mode violation。
        """
        logger.info("正在等待登录响应 (验证码、成功或失败)...")

        # 为每个可能的结果创建一个独立的等待任务
        tasks = [
            asyncio.create_task(self.page.locator("#pw-captchaCode").wait_for(state="visible", timeout=20000), name="captcha"),
            asyncio.create_task(self.page.locator("a:has-text('我的课程')").wait_for(state="visible", timeout=20000), name="success_page"),
            asyncio.create_task(self.page.get_by_role("button", name="知道了").wait_for(state="visible", timeout=20000), name="success_popup"),
            asyncio.create_task(self.page.locator(".layui-layer-dialog .layui-layer-content:has-text('用户名或者密码错误')").wait_for(state="visible", timeout=20000), name="failure")
        ]

        try:
            # 等待第一个任务完成
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            # 无论结果如何，取消所有仍在运行的任务，避免后台继续执行
            for task in tasks:
                if not task.done():
                    task.cancel()

        # 检查完成的任务并处理结果
        for task in done:
            task_name = task.get_name()
            # 检查任务是否因异常（如超时）而结束
            if task.exception():
                # 如果是超时，Playwright 会抛出 TimeoutError。我们将在最后统一处理。
                logger.debug(f"任务 '{task_name}' 因异常而结束: {task.exception()}")
                continue

            # 根据成功完成的任务名称来决定下一步
            if task_name == "captcha":
                await self._handle_captcha_flow()
                return
            elif task_name == "failure":
                logger.error("登录失败：用户名或密码错误。")
                raise InvalidCredentialsException("用户名或密码错误")
            elif task_name in ["success_page", "success_popup"]:
                logger.info("直接登录成功。")
                await self._finalize_login()
                return

        # 如果所有完成的任务都以异常结束（通常是超时），则认为登录超时
        logger.error("登录超时：20秒内未收到服务器的初始响应（成功、失败或验证码）。")
        raise PlaywrightError("登录超时：20秒内未收到服务器的初始响应。")

    async def _handle_captcha_flow(self):
        """处理检测到验证码后的手动登录流程。"""
        logger.always_print("="*50)
        logger.always_print("检测到登录验证码！")
        logger.always_print("请在浏览器中手动输入验证码，并点击【登录】按钮。")
        logger.always_print("程序将等待您手动登录的结果（5分钟超时）...")
        logger.always_print("="*50)

        # 定义手动登录后的成功与失败状态
        success_indicator = self.page.get_by_role("button", name="知道了")
        failure_indicator = self.page.locator(".layui-layer-dialog .layui-layer-content:has-text('用户名或者密码错误')")
        
        final_outcome_locator = success_indicator.or_(failure_indicator)

        try:
            await final_outcome_locator.wait_for(state="visible", timeout=300000)
        except PlaywrightError:
            logger.error("登录超时：5分钟内未检测到您手动登录后的成功或失败结果。")
            raise

        if await failure_indicator.is_visible():
            logger.error("手动登录失败：用户名或密码错误。")
            raise InvalidCredentialsException("用户名或密码错误")
        else:  # 成功
            logger.info("手动登录成功。")
            await self._finalize_login()

    async def _finalize_login(self):
        """统一处理登录成功后的收尾工作，如关闭弹窗和页面导航。"""
        try:
            # 尝试点击“知道了”弹窗
            await self.page.get_by_role("button", name="知道了").click(timeout=5000)
            logger.info("已关闭“知道了”弹窗。")
        except PlaywrightError:
            logger.info("未找到“知道了”弹窗，跳过。")

        try:
            await self.page.get_by_text("我的课程").click()
            logger.info("已点击“我的课程”。")
        except PlaywrightError:
            logger.error("登录后未找到“我的课程”按钮，无法继续。")
            raise

    async def get_course_list(self) -> list[str]:
        """获取“我的课程”页面上的所有课程名称。"""
        logger.info("正在获取课程列表...")
        try:
            await self.page.locator(".course-name").first.wait_for() # 等待课程名称的父容器出现
            course_names = await self.page.locator(".course-name").all_text_contents()
            return [name.strip() for name in course_names if name.strip()]
        except PlaywrightError:
            logger.error("未能找到课程列表。")
            return []

    async def select_course_by_index(self, index: int):
        """根据索引点击指定的课程卡片。"""
        try:
            course_card_locator = self.page.locator(".course-card-stu").nth(index)
            logger.info(f"正在进入第 {index + 1} 门课程...")
            await course_card_locator.click()
            await self.page.locator(config.UNIT_TABS).first.wait_for()
            logger.info("已成功进入课程页面。")
        except PlaywrightError:
            logger.error("点击课程后，未能等到课程单元加载。")
            raise

    async def get_media_source_and_type(self, search_scope: Locator | Page | None = None) -> tuple[str | None, str | None]:
        """
        尝试在指定范围内查找<audio>或<video>元素，使用短暂超时以避免卡顿。
        如果未提供search_scope，则在整个页面中查找。
        """
        scope = search_scope if search_scope else self.page
        try:
            media_locator = scope.locator(config.MEDIA_SOURCE_ELEMENTS).first
            # 等待元素附加到DOM中即可，无需等待其可见，这会更快。超时设为1秒。
            await media_locator.wait_for(state="attached", timeout=1000)
            url = await media_locator.get_attribute('src')
            tag_name = await media_locator.evaluate('element => element.tagName.toLowerCase()')
            return url, tag_name
        except Exception: # 捕获超时等错误
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
            logger.error(f"提取完整目录树时发生错误: {e}")
            return []

    async def get_auth_info(self) -> dict:
        """
        通过拦截网络请求，从浏览器环境中获取动态的认证信息。
        """
        logger.info("正在设置网络监听以捕获认证信息...")
        auth_info = {"Authorization": None, "userId": None, "auth_header": None}

        # 创建一个 Future 对象，用于在信息捕获后发出信号
        headers_found = asyncio.Future()

        def intercept_request(request):
            # 捕获 auth 头 (用于 soe/api)
            if "zt.unipus.cn/soe/api" in request.url and request.headers.get("auth"):
                if not auth_info["auth_header"]:
                    auth_info["auth_header"] = request.headers["auth"]
                    logger.info("成功捕获 'auth' 头。")
            
            # 捕获 Authorization 头 (用于 ucontent.unipus.cn)
            if "ucontent.unipus.cn" in request.url and request.headers.get("authorization"):
                if not auth_info["Authorization"]:
                    auth_info["Authorization"] = request.headers["authorization"]
                    logger.info("成功捕获 'Authorization' 头。")

            # 如果两个都找到了，就完成Future
            if auth_info["auth_header"] and auth_info["Authorization"] and not headers_found.done():
                headers_found.set_result(True)

        self.page.on("request", intercept_request)

        try:
            # 刷新页面以触发各种API请求，从而让我们的监听器捕获到所需信息
            logger.info("将重新加载页面以触发网络请求...")
            await self.page.reload(wait_until="networkidle")
            
        except Exception as e:
            logger.error(f"网络拦截或页面刷新时发生错误: {e}")
        
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
                        logger.info("成功从sensorsdata2015jssdkcross Cookie中获取userId。")
                        break
        except Exception as e:
            logger.error(f"从Cookie中解析userId时出错: {e}")

        # 如果仍然没有userId，尝试从localStorage获取作为最后的补充
        try:
            if not auth_info.get("userId"):
                user_id_from_ls = await self.page.evaluate("() => localStorage.getItem('openId') || (window.vuex_state && window.vuex_state.userId)")
                if user_id_from_ls:
                    auth_info["userId"] = user_id_from_ls
                    logger.info("成功从localStorage获取userId。")
        except Exception:
            pass # 忽略错误

        logger.info(f"获取到的认证信息: {auth_info}")
        if not all([auth_info["Authorization"], auth_info["auth_header"], auth_info["userId"]]):
             logger.warning("未能获取到完整的认证信息，API调用可能会失败。")
             
        return auth_info

    async def get_pending_tasks(self) -> list:
        """获取当前课程页面中所有未完成的必修任务。"""
        logger.info("正在获取待完成任务列表...")
        pending_tasks = []
        current_course_url = self.page.url
        try:
            await self.page.locator(config.UNIT_TABS).first.wait_for()
            # 只获取 data-index 属性，避免过早与元素交互
            units_with_indices = []
            all_unit_locators = await self.page.locator(config.UNIT_TABS).all()
            for locator in all_unit_locators:
                index = await locator.get_attribute("data-index")
                name = (await locator.text_content() or "").strip().split('\n')[0]
                if index is not None:
                    units_with_indices.append({"index": index, "name": name})
    
        except PlaywrightError:
            logger.error("未能定位到课程单元列表，请确保当前页面是课程主页。")
            return []
    
        for unit_info in units_with_indices:
            unit_index = unit_info["index"]
            unit_name = unit_info["name"]
            logger.info(f"正在检查单元: {unit_name}")
            try:
                # 使用重构后的健壮的点击方法
                await self._click_unit_tab(unit_index)
                await asyncio.sleep(0.5)  # 等待任务列表加载
    
                active_area_locator = self.page.locator(config.ACTIVE_UNIT_AREA)
                await active_area_locator.locator(config.TASK_ITEM_CONTAINER).first.wait_for()
                task_locators = await active_area_locator.locator(config.TASK_ITEM_CONTAINER).all()
    
                for i, task_locator in enumerate(task_locators):
                    text_content = await task_locator.text_content()
                    
                    should_process = False
                    # 根据配置决定是否处理该任务
                    if config.PROCESS_ONLY_INCOMPLETE_TASKS:
                        # 模式一：只处理“必修”且“未完成”的
                        if "必修" in text_content and "已完成" not in text_content:
                            should_process = True
                    else:
                        # 模式二：处理所有“必修”的，无论是否完成
                        if "必修" in text_content:
                            should_process = True
                    
                    if should_process:
                        task_name = await task_locator.locator(config.TASK_ITEM_TYPE_NAME).text_content()
                        pending_tasks.append({
                            "unit_index": unit_index, "unit_name": unit_name,
                            "task_index": i, "task_name": task_name,
                            "course_url": current_course_url
                        })
            except Exception as e:
                logger.error(f"处理单元 '{unit_name}' 时出错: {e}")
                # 在开发/调试时，如果特定单元出错，可能希望抛出异常以停止程序
                # if unit_name == 'Unit 5': raise

        logger.info(f"待完成任务列表获取完毕，共 {len(pending_tasks)} 个任务。")
        return pending_tasks

    async def _click_unit_tab(self, unit_index: str):
        """
        一个健壮的私有方法，用于点击指定的单元Tab。
        它会先将滚动条重置到最左边，然后向右滚动直到找到目标，最后点击。
        """
        try:
            unit_locator = self.page.locator(f'[data-index="{unit_index}"]')
            current_class = await unit_locator.get_attribute("class") or ""
            
            # 如果目标单元已激活，则无需任何操作
            if "tabActive" in current_class:
                logger.info(f"单元 {unit_index} 已是激活状态，无需点击。")
                return

            # 仅在目标不可见时才执行重置和滚动，以提高效率
            if not await unit_locator.is_visible(timeout=1000):
                logger.info(f"单元 {unit_index} 不可见，开始智能滚动查找...")
                
                # 策略：先滚动到最左边，再向右查找
                prev_button_locator = self.page.locator("class*=[unipus-tabs_tabPre]")
                for _ in range(20): # 安全循环
                    if not (await prev_button_locator.is_visible(timeout=500) and await prev_button_locator.is_enabled()):
                        break # 按钮不见或禁用，说明已到最左
                    await prev_button_locator.click()
                    await self.page.wait_for_timeout(300)
                logger.info("滚动条已重置到最左侧。")

                # 如果此时目标仍不可见，则开始向右滚动查找
                if not await unit_locator.is_visible():
                    next_button_locator = self.page.locator("class*=[unipus-tabs_tabNext]")
                    for _ in range(20): # 安全循环
                        if await unit_locator.is_visible(): break # 找到了
                        if not (await next_button_locator.is_visible(timeout=500) and await next_button_locator.is_enabled()):
                            raise PlaywrightError(f"已滚动到最右端，但仍未找到单元 {unit_index}")
                        await next_button_locator.click()
                        await self.page.wait_for_timeout(500)
                    
                    if not await unit_locator.is_visible():
                        raise PlaywrightError(f"向右滚动20次后，仍无法找到单元 {unit_index}")
            
            logger.info(f"成功定位到单元 {unit_index}，准备点击。")
            # 使用 dispatch_event 来避免 click() 方法自带的、可能出错的滚动行为
            await unit_locator.dispatch_event('click')
            
            await self.page.locator(f'[data-index="{unit_index}"][class*="tabActive"]').wait_for()
            logger.info(f"已确认单元 {unit_index} 已激活。")

        except PlaywrightError as e:
            logger.error(f"点击单元Tab {unit_index} 时发生Playwright错误: {e}")
            raise
        except Exception as e:
            logger.error(f"点击单元Tab {unit_index} 时发生未知异常: {e}")
            raise

    async def navigate_to_task(self, course_url: str, unit_index: str, task_index: int):
        """
        导航到指定单元和索引的任务页面，并在导航后处理常见弹窗。
        """
        logger.info(f"正在导航到单元 {unit_index}，任务索引 {task_index}...")

        # 1. 重新回到课程主页，确保页面状态一致
        if self.page.url != course_url:
            await self.page.goto(course_url)
            await self.page.wait_for_load_state('networkidle')


        # 2. 使用重构后的健壮方法点击指定的单元
        await self._click_unit_tab(unit_index)

        # 3. 定位并点击指定的任务
        try:
            # 找到对应单元下的所有任务未在本页找到可用的音频或视频文件。项
            task_elements_locators = self.page.locator(f"{config.ACTIVE_UNIT_AREA} {config.TASK_ITEM_CONTAINER}")
            # 点击第 task_index 个任务
            await asyncio.sleep(0.5) # TODO:暂不明确应等待什么元素
            await task_elements_locators.nth(task_index).click()
            logger.info(f"已进入任务索引 {task_index} 的任务页面。")

            # 等待题目加载标记，针对服务器不稳定，增加等待时间
            try:
                await self.page.wait_for_selector(config.QUESTION_LOADING_MARKER, timeout=30000)
            except PlaywrightError:
                logger.warning("任务页面加载后，未在30秒内找到题目加载标记。")

            # 调用通用的弹窗处理器
            await self.handle_common_popups()
        except Exception as e:
            logger.error(f"在进入任务索引 {task_index} 时失败: {e}")
            raise
    
    async def handle_common_popups(self):
        """处理进入任务后常见的弹窗，采用短超时优化。"""
        # 1. 快速处理“鼠标取词”引导 (如果存在)
        try:
            # 使用非常短的超时，如果弹窗在0.5秒内没出现，就立即跳过
            await self.page.locator(".iKnow").click(timeout=500)
            logger.info("已关闭“鼠标取词”新手引导。")
        except PlaywrightError:
            pass  # 0.5秒内未找到，说明它不存在，直接继续

        # 2. 处理其他可能出现的、需要更长等待时间的弹窗
        try:
            await self.page.get_by_role("button", name="我知道了").click(timeout=3000)
            logger.info("已关闭“任务信息”等弹窗。")
        except PlaywrightError:
            pass
			
            
    async def handle_submission_confirmation(self):
        """处理点击提交后的“最终确认”弹窗。"""
        try:
            await self.page.get_by_role("button", name="确 定").click(timeout=1500)
            logger.info("已点击“最终确认提交”弹窗。")
        except PlaywrightError:
            pass

    async def _navigate_to_answer_analysis_page(self):
        """从“答题小结”页面进入“答案解析”页面。"""
        logger.info("正在导航到答案解析页面...")
        try:
            await self.page.locator(config.SUMMARY_QUESTION_NUMBER).first.click()
            await self.page.locator(config.QUESTION_WRAP).first.wait_for()
            logger.info("已进入答案解析页面。")
        except PlaywrightError:
            logger.error("未能进入答案解析页面。")
            raise

    async def extract_all_correct_answers_from_analysis_page(self) -> list[str]:
        """
        从答案解析页面提取所有正确答案，并将它们平铺到一个列表中。
        适用于单选题（一页多题）和多选题/拖拽题（一页一题）的场景。
        """
        logger.info("正在提取所有题目的正确答案...")
        all_answers = []
        try:
            # 找到页面上所有包含答案解析的区块
            analysis_wraps = await self.page.locator(".component-analysis").all()
            
            if not analysis_wraps:
                logger.info("未找到任何 .component-analysis 区块，跳过答案提取。")
                return []

            for i, analysis_locator in enumerate(analysis_wraps):
                # 在每个 .component-analysis 区块内，找到正确答案
                correct_answer_locator = analysis_locator.locator(".analysis-item:has(.analysis-item-title:has-text('正确答案：')) .component-htmlview")
                
                await correct_answer_locator.wait_for(state='visible', timeout=10000)
                correct_answer_text = (await correct_answer_locator.text_content()).strip()
                
                # 分割字符串（例如 "A B C" -> ['A', 'B', 'C']），并将其展平到最终列表中
                answers = correct_answer_text.split()
                if answers:
                    all_answers.extend(answers)
            
            logger.info(f"已提取到所有正确答案: {all_answers}")
            
        except Exception as e:
            logger.error(f"提取正确答案时发生错误: {e}")
            
        return all_answers

    async def extract_fill_in_the_blank_answers_from_analysis_page(self) -> list[str]:
        """
        [新增] 从答案解析页面为“填空题”提取所有正确答案。
        该方法能智能处理答对和答错两种情况下，正确答案在DOM中的不同位置。
        """
        logger.info("正在为填空题从解析页面提取所有正确答案...")
        all_answers = []
        
        # 定位到所有填空的容器
        blank_containers = await self.page.locator(".fe-scoop").all()
        
        if not blank_containers:
            logger.warning("在解析页面未找到任何填空题容器 (.fe-scoop)。")
            return []

        for i, container in enumerate(blank_containers):
            correct_answer = ""
            try:
                # 方案一：优先查找“答错时”出现的正确答案提示（最可靠）
                reference_answer_locator = container.locator("span.reference")
                if await reference_answer_locator.count() > 0:
                    correct_answer = (await reference_answer_locator.first.text_content()).strip()
                else:
                    # 方案二：如果没找到，说明“答对了”，直接从 input 的 value 获取
                    input_locator = container.locator("input")
                    # 确保 input 存在且有 value 属性
                    input_value = await input_locator.get_attribute("value")
                    correct_answer = (input_value or "").strip()
                
                all_answers.append(correct_answer)
                logger.info(f"  - 填空 {i+1}: 找到答案 '{correct_answer}'")

            except Exception as e:
                logger.error(f"  - 提取第 {i+1} 个填空题答案时出错: {e}")
                all_answers.append("") # 出错时添加空字符串以保持顺序

        logger.info(f"已提取到所有填空题答案: {all_answers}")
        return all_answers

    async def _extract_additional_material_for_ai(self) -> str:
        """
        从页面中提取所有额外材料（纯文本或表格），用于补充给AI的Prompt。
        此版本经过重构，可以处理单个材料容器中的多个表格，并为隐式空白生成编号。
        """
        all_extracted_materials = []
        blank_counter = 1  # 为页面上所有隐式空白提供一个统一的计数器
        
        material_containers = await self.page.locator(
            ".layout-material-container .question-common-abs-material .text-material-wrapper .component-htmlview"
        ).all()
    
        if not material_containers:
            return ""
    
        for i, material_container in enumerate(material_containers):
            try:
                if not await material_container.is_visible(timeout=500):
                    continue
    
                # 在容器内查找所有表格
                table_locators = await material_container.locator("table.unipus-table").all()
    
                if table_locators:
                    logger.info(f"检测到第 {i+1} 个材料容器包含 {len(table_locators)} 个表格，开始解析...")
                    for table_locator in table_locators:
                        markdown_table, blank_counter = await self._parse_table_to_markdown(table_locator, blank_counter)
                        if markdown_table.strip():
                           all_extracted_materials.append("以下是表格内容：" + markdown_table)
                else:
                    # 如果没有找到表格，则作为纯文本处理
                    logger.info(f"检测到第 {i+1} 个材料容器包含纯文本文本，开始提取...")
                    paragraphs = await material_container.locator("p").all()
                    full_text = ""
                    if not paragraphs:
                        full_text = html.unescape(await material_container.text_content() or "").strip()
                    else:
                        lines = [html.unescape(await p.text_content() or "").strip() for p in paragraphs]
                        full_text = "\n".join(filter(None, lines))
                    
                    if full_text:
                        all_extracted_materials.append("以下是额外文本材料：\n" + full_text)
    
            except Exception as e:
                logger.warning(f"提取第 {i+1} 个额外材料时发生错误: {e}")
                
        return "\n\n".join(all_extracted_materials)

    async def _parse_table_to_markdown(self, table_locator: Locator, blank_start_index: int) -> tuple[str, int]:
        """将单个表格的Locator解析为Markdown格式，智能处理表头，并为数据行中的空白生成编号。"""
        markdown_table = "\n\n"
        blank_counter = blank_start_index
        
        all_rows = await table_locator.locator("tr").all()
        if not all_rows:
            return "", blank_counter

        headers = []
        data_rows = []

        # --- 完整的智能表头检测逻辑 (保留用户要求) ---
        thead_rows = await table_locator.locator("thead tr").all()
        if thead_rows and any([html.unescape(await cell.text_content() or "").strip() for cell in await thead_rows[0].locator("th, td").all()]):
            header_row_loc = thead_rows[0]
            data_rows = await table_locator.locator("tbody tr").all()
        else:
            tbody_rows = await table_locator.locator("tbody tr").all()
            if tbody_rows and any([html.unescape(await cell.text_content() or "").strip() for cell in await tbody_rows[0].locator("th, td").all()]):
                header_row_loc = tbody_rows[0]
                data_rows = tbody_rows[1:]
            elif all_rows:
                header_row_loc = all_rows[0]
                data_rows = all_rows[1:]
            else: # 表格为空
                return "", blank_counter
        
        header_cells = await header_row_loc.locator("th, td").all()
        headers = [(html.unescape(await cell.text_content() or "").strip()) for cell in header_cells]
        # --- 智能表头检测结束 ---

        # 构建Markdown表头 (不对表头应用[Blank]逻辑)
        markdown_table += f"| {' | '.join(h if h and h != '&nbsp;' else ' ' for h in headers)} |\n"
        markdown_table += f"|{'|'.join([':---:'] * len(headers))}|\n"
        
        # 处理数据行 (只在此处应用[Blank]逻辑)
        for row in data_rows:
            row_data = []
            cells = await row.locator("td, th").all()
            for cell in cells:
                placeholder = cell.locator("span._placeHolder_")
                if await placeholder.count() > 0:
                    data_index = await placeholder.first.get_attribute("data-index")
                    row_data.append(f"[Blank {data_index}]")
                else:
                    text = html.unescape(await cell.text_content() or "").strip()
                    if not text or text == "&nbsp;":
                        row_data.append(f"[Blank {blank_counter}]")
                        blank_counter += 1
                    else:
                        row_data.append(text)
            markdown_table += f"| {' | '.join(row_data)} |\n"
            
        return markdown_table, blank_counter

    async def click_next_on_analysis_page(self):
        """在答案解析页面点击“下一题”。"""
        try:
            # 答案解析页面的“下一题”按钮选择器可能与答题时不同，这里使用一个较为通用的
            next_btn_locator = self.page.locator(".btn:has-text('下一题')")
            if await next_btn_locator.is_visible():
                await next_btn_locator.click()
                # 等待页面内容更新，例如等待题目编号变化
                await asyncio.sleep(1) # 使用短暂等待，具体等待目标可后续优化
                logger.info("已在解析页面点击“下一题”。")
            else:
                raise Exception("在解析页面未找到“下一题”按钮。")
        except Exception as e:
            logger.error(f"在解析页面点击“下一题”时出错: {e}")
            raise
			
    async def handle_rate_limit_modal(self):
        """
        检查并处理“操作过于频繁”的弹窗。如果检测到，则抛出RateLimitException。
        """
        try:
            modal_content_locator = self.page.locator('div.ant-modal-confirm-content:has-text("您的操作过于频繁")')
            # 使用短暂超时，因为此弹窗不是每次都出现
            if await modal_content_locator.is_visible(timeout=2000):
                logger.error("检测到“操作过于频繁”弹窗。服务器已暂时拒绝请求。")
                await self.page.locator("button:has-text('我知道了')").click()
                raise RateLimitException("服务器速率限制")
        except PlaywrightError:
            # 超时意味着弹窗没有出现，这是正常情况，直接忽略即可
            pass
        except Exception as e:
            # 捕获其他意想不到的错误
            logger.error(f"处理速率限制弹窗时发生未知错误: {e}")