import asyncio
import os
import sys
import time
from pathlib import Path
sys.path.append(str(Path(__file__).parent))
import src.config as config
from src.credentials_handler import handle_credentials
from src.services.driver_service import DriverService, RateLimitException, InvalidCredentialsException
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.diagnostic_service import DiagnosticService
from src.services.listening_export_service import ListeningExportService
from src.services.task_progress_service import TaskProgressService
from src.strategy_registry import filter_available_strategies
from src.utils import logger, console
from src.strategies.checkbox_strategy import CheckboxStrategy
from src.strategies.single_choice import SingleChoiceStrategy
from src.strategies.read_aloud_strategy import ReadAloudStrategy
from src.strategies.multiple_choice_strategy import MultipleChoiceStrategy
from src.strategies.discussion_strategy import DiscussionStrategy
from src.strategies.drag_and_drop_strategy import DragAndDropStrategy
from src.strategies.fill_in_the_blank_strategy import FillInTheBlankStrategy
from src.strategies.dropdown_selection_strategy import DropdownSelectionStrategy
from src.strategies.role_play_strategy import RolePlayStrategy
from src.strategies.short_answer_strategy import ShortAnswerStrategy
from src.strategies.qa_voice_strategy import QAVoiceStrategy
from src.strategies.unsupported_image_strategy import UnsupportedImageStrategy
from src.strategies.no_reply_strategy import NoReplyStrategy
from rich.progress import Progress, TextColumn, BarColumn, TimeElapsedColumn, MofNCompleteColumn

# ==============================================================================
# 全局可用策略列表
# ==============================================================================
AVAILABLE_STRATEGIES = [
    # 策略的顺序很重要，防御性的策略应该放在最前面
    UnsupportedImageStrategy,
    # 需要特殊处理的复合型或无按钮任务
    RolePlayStrategy,
    DiscussionStrategy,
    # 语音策略
    ReadAloudStrategy,
    QAVoiceStrategy,
    # 常规选择、填空、拖拽题
    CheckboxStrategy,
    DragAndDropStrategy,
    DropdownSelectionStrategy,
    FillInTheBlankStrategy,
    ShortAnswerStrategy,
    MultipleChoiceStrategy,
    SingleChoiceStrategy,
    # 保底策略，处理纯听/看任务
    NoReplyStrategy
]


async def _cache_chained_answers(
    browser_service: DriverService,
    cache_service: CacheService,
    tasks_to_cache: list,
    base_breadcrumb_parts: list[str]
):
    """
    在“题中题”全部完成后，统一回写需要缓存的答案。
    """
    if not tasks_to_cache:
        return

    logger.info("=" * 20)
    logger.info("检测到“题中题”中有AI作答的题目，开始统一回写缓存...")

    try:
        await browser_service._navigate_to_answer_analysis_page()
        
        # 按索引排序，确保我们按顺序点击“下一题”
        tasks_to_cache.sort(key=lambda x: x['index'])
        
        current_analysis_index = 0
        for task in tasks_to_cache:
            target_index = task['index']
            strategy_type = task['type']
            
            # 点击“下一题”直到我们到达目标子题的解析页面
            clicks_needed = target_index - current_analysis_index
            if clicks_needed > 0:
                logger.info(f"正在从解析页 {current_analysis_index} 跳转到 {target_index}...")
                for _ in range(clicks_needed):
                    await browser_service.click_next_on_analysis_page()
            
            current_analysis_index = target_index
            
            # 构建当前子题的缓存Key
            sub_task_breadcrumb = base_breadcrumb_parts + [str(target_index)]
            
            # 根据策略类型决定调用哪个答案提取方法
            logger.info(f"正在为子题 {target_index} ({strategy_type}) 提取答案...")
            answers = []
            if strategy_type == "fill_in_the_blank":
                answers = await browser_service.extract_fill_in_the_blank_answers_from_analysis_page()
            elif strategy_type == "dropdown_selection":
                answers = await browser_service.extract_dropdown_selection_answers_from_analysis_page()
            elif strategy_type in ["single_choice", "multiple_choice", "drag_and_drop_js_injection"]:
                answers = await browser_service.extract_all_correct_answers_from_analysis_page()
            
            if answers:
                cache_service.save_task_page_answers(sub_task_breadcrumb, strategy_type, answers)
            else:
                logger.warning(f"未能为子题 {target_index} 提取到答案，跳过缓存。")

        logger.success("“题中题”缓存回写完成。")

    except Exception as e:
        logger.error(f"“题中题”缓存回写过程中发生严重错误: {e}")


async def run_strategy_on_current_page(browser_service: DriverService, ai_service: AIService, cache_service: CacheService):
    """
    分析当前页面，并根据页面特征（如“提交”或“下一题”按钮）选择并执行最合适的策略。
    新增了对“快速缓存模式”的支持。
    """
    # 定义可缓存的策略白名单
    cacheable_strategies = [
        SingleChoiceStrategy,
        MultipleChoiceStrategy,
        FillInTheBlankStrategy,
        DragAndDropStrategy,
        DropdownSelectionStrategy,
    ]
    
    # 创建一个本次运行要使用的策略列表副本
    strategies_to_run = filter_available_strategies(
        AVAILABLE_STRATEGIES,
        config.SKIP_SHORT_ANSWER_QUESTIONS,
    )
    if config.SKIP_SHORT_ANSWER_QUESTIONS:
        logger.info("已启用跳过简答题配置：文本简答题和语音简答题不会自动作答。")

    # 快速缓存模式的核心逻辑
    if config.FAST_CACHE_MODE:
        base_breadcrumb_parts_for_cache_check = await browser_service.get_breadcrumb_parts()
        
        # 对于“题中题”模式，基础面包屑不足以判断，但对于单页题很有效
        # 我们在这里做一个初步检查，如果基础路径有缓存，很可能已经做过
        task_page_cache = cache_service.get_task_page_cache(base_breadcrumb_parts_for_cache_check)
        if task_page_cache and task_page_cache.get('answers'):
            logger.info(f"快速缓存模式：检测到页面 {'>'.join(base_breadcrumb_parts_for_cache_check)} 已有缓存，跳过。")
            return

        # 过滤策略，只保留白名单中的可缓存策略
        logger.info("快速缓存模式：已启动，仅运行客观题策略以生成缓存。")
        strategies_to_run = [s for s in strategies_to_run if s in cacheable_strategies]

    try:
        base_breadcrumb_parts = await browser_service.get_breadcrumb_parts()
        btn_text = ""
        try:
            action_btn = browser_service.page.locator(".btn:has-text('下一题'), .btn:has-text('下一页'), .btn:has-text('提 交'), .btn:has-text('提交')").first
            await action_btn.wait_for(state="visible", timeout=3000)
            btn_text = await action_btn.text_content()
        except Exception:
            logger.info("在页面上未找到‘提交’或‘下一题’/‘下一页’按钮。")

        if "提 交" in btn_text or "提交" in btn_text:
            logger.info("检测到“提交”按钮，执行单页策略...")
            current_strategy = None
            for StrategyClass in strategies_to_run: # 使用过滤后的策略列表
                if await StrategyClass.check(browser_service):
                    current_strategy = StrategyClass(browser_service, ai_service, cache_service)
                    logger.info(f"匹配到策略: {StrategyClass.__name__}")
                    break
            
            if current_strategy:
                succeeded, _ = await current_strategy.execute(is_chained_task=False)
                if not succeeded and not getattr(current_strategy, "diagnostic_already_captured", False):
                    await DiagnosticService.capture_page_failure(
                        browser_service,
                        "strategy_returned_failed",
                        context={
                            "strategy": current_strategy.__class__.__name__,
                            "mode": "single_page",
                        },
                    )
            else:
                logger.warning("在当前页面未找到适合的策略。")
            
        elif "下一题" in btn_text or "下一页" in btn_text:
            logger.info("检测到“下一题”按钮，启动“题中题”循环模式。")
            shared_context = ""
            config.HAS_FETCHED_REMOTE_ARTICLE = False
            
            sub_task_index = 0
            tasks_to_cache = [] # 记录需要缓存的任务信息

            while True:
                current_strategy_instance = None
                for StrategyClass in strategies_to_run: # 使用过滤后的策略列表
                    if await StrategyClass.check(browser_service):
                        current_strategy_instance = StrategyClass(browser_service, ai_service, cache_service)
                        logger.info(f"匹配到子题策略: {StrategyClass.__name__}")
                        break
                
                if current_strategy_instance:
                    try:
                        # 在快速缓存模式下，对每个子任务也进行缓存检查
                        if config.FAST_CACHE_MODE:
                            sub_task_breadcrumb = base_breadcrumb_parts + [str(sub_task_index)]
                            if cache_service.get_task_page_cache(sub_task_breadcrumb):
                                logger.info(f"快速缓存模式：子题 {sub_task_index} 已有缓存，跳过。")
                                # 模拟一个成功的、但没有写入缓存的执行结果
                                succeeded, cache_written = True, False
                            else:
                                succeeded, cache_written = await current_strategy_instance.execute(
                                    shared_context=shared_context, is_chained_task=True, sub_task_index=sub_task_index
                                )
                        else:
                             succeeded, cache_written = await current_strategy_instance.execute(
                                shared_context=shared_context, is_chained_task=True, sub_task_index=sub_task_index
                            )

                        if cache_written:
                            tasks_to_cache.append({'index': sub_task_index, 'type': current_strategy_instance.strategy_type})
                        if not succeeded:
                            logger.warning(f"策略 {current_strategy_instance.__class__.__name__} 执行提前终止，任务链中断。")
                            if not getattr(current_strategy_instance, "diagnostic_already_captured", False):
                                await DiagnosticService.capture_page_failure(
                                    browser_service,
                                    "strategy_returned_failed",
                                    context={
                                        "strategy": current_strategy_instance.__class__.__name__,
                                        "mode": "chained_task",
                                        "sub_task_index": sub_task_index,
                                    },
                                )
                            break 
                    except RateLimitException:
                        raise
                    except Exception as e:
                        logger.error(f"策略 {current_strategy_instance.__class__.__name__} 执行时发生错误，终止当前任务链: {e}")
                        await DiagnosticService.capture_page_failure(
                            browser_service,
                            "strategy_execute_failed",
                            e,
                            {
                                "strategy": current_strategy_instance.__class__.__name__,
                                "sub_task_index": sub_task_index,
                            },
                        )
                        break
                else:
                    logger.info("当前子题未匹配到任何策略，尝试提取材料作为共享上下文...")
                    material = await browser_service._extract_additional_material_for_ai()
                    if material:
                        logger.info("已提取到共享材料。")
                        shared_context += f"\n{material}"

                action_btn_loop = browser_service.page.locator(".btn:has-text('下一题'), .btn:has-text('下一页'), .btn:has-text('提 交'), .btn:has-text('提交')").first
                await action_btn_loop.wait_for(state="visible", timeout=10000)
                current_btn_text = await action_btn_loop.text_content()

                if "下一题" in current_btn_text or "下一页" in current_btn_text:
                    logger.info("点击“下一题”，进入下一个子题...")
                    await action_btn_loop.click()
                    await asyncio.sleep(1) 
                    await browser_service.handle_common_popups()
                    sub_task_index += 1
                elif "提 交" in current_btn_text or "提交" in current_btn_text:
                    logger.info("检测到最终“提交”按钮，正在提交任务...")
                    await action_btn_loop.click()
                    await browser_service.handle_rate_limit_modal()
                    await browser_service.handle_submission_confirmation()
                    logger.success("“题中题”任务完成。")

                    if tasks_to_cache:
                        await _cache_chained_answers(browser_service, cache_service, tasks_to_cache, base_breadcrumb_parts)
                    break
                else:
                    logger.warning(f"检测到未知按钮文本 '{current_btn_text}'，循环终止。")
                    break
        else:
            logger.info("此页面无提交或下一题按钮，将检查是否有适用的无操作策略...")
            current_strategy = None
            for StrategyClass in strategies_to_run: # 使用过滤后的策略列表
                if await StrategyClass.check(browser_service):
                    current_strategy = StrategyClass(browser_service, ai_service, cache_service)
                    logger.info(f"匹配到策略: {StrategyClass.__name__}")
                    break
            
            if current_strategy:
                if isinstance(current_strategy, (RolePlayStrategy, DiscussionStrategy)):
                    logger.info(f"检测到 {current_strategy.__class__.__name__}，强制以非链式任务模式(is_chained_task=False)执行。")
                    succeeded, _ = await current_strategy.execute(is_chained_task=False)
                    if not succeeded and not getattr(current_strategy, "diagnostic_already_captured", False):
                        await DiagnosticService.capture_page_failure(
                            browser_service,
                            "strategy_returned_failed",
                            context={
                                "strategy": current_strategy.__class__.__name__,
                                "mode": "no_action_button",
                            },
                        )
                # 在快速缓存模式下，不执行NoReply等非缓存策略
                elif not config.FAST_CACHE_MODE:
                     succeeded, _ = await current_strategy.execute(is_chained_task=True)
                     if not succeeded and not getattr(current_strategy, "diagnostic_already_captured", False):
                         await DiagnosticService.capture_page_failure(
                             browser_service,
                             "strategy_returned_failed",
                             context={
                                 "strategy": current_strategy.__class__.__name__,
                                 "mode": "no_action_button_chained",
                             },
                         )
                else:
                    logger.info(f"快速缓存模式：跳过非缓存策略 {current_strategy.__class__.__name__}。")

            else:
                logger.info("未找到任何适用策略，此页面可能为纯信息页。继续下一个任务。")

    except RateLimitException:
        raise
    except Exception as e:
        logger.error(f"执行策略期间发生错误: {e}")
        await DiagnosticService.capture_page_failure(
            browser_service,
            "strategy_dispatch_failed",
            e,
        )

async def run_auto_mode(browser_service: DriverService, ai_service: AIService, cache_service: CacheService):
   """运行全自动答题模式。"""
   config.IS_AUTO_MODE = True
   logger.always_print("已进入全自动模式。")

   courses = await browser_service.get_course_list()
   if not courses:
       logger.error("未能获取到任何课程，程序终止。")
       return

   logger.always_print("检测到以下课程：")
   for i, name in enumerate(courses):
       logger.always_print(f"[{i + 1}] {name}")

   selected_index = 0  # Default to the first course
   if len(courses) > 1:
       choice = -1
       while choice < 0 or choice >= len(courses):
           try:
               user_input = await asyncio.to_thread(input, f"请输入要进行的课程编号 (1-{len(courses)}): ")
               choice = int(user_input) - 1
               if choice < 0 or choice >= len(courses):
                   logger.warning("输入无效，请输入列表中的编号。")
           except ValueError:
               logger.warning("输入无效，请输入一个数字。")
       selected_index = choice
   else:
       # If there's only one course, automatically select it
       logger.info("检测到只有一门课程，已自动选择。")

   await browser_service.select_course_by_index(selected_index)
   selected_course_name = courses[selected_index]
   current_course_url = browser_service.page.url
   task_progress_service = TaskProgressService(config.TASK_QUEUE_CACHE_FILE)

   course_record = task_progress_service.get_course_record(config.USERNAME, selected_course_name)
   if course_record and not config.REFRESH_TASK_QUEUE:
       pending_tasks = course_record.get("queue", [])
       pending_tasks = task_progress_service.refresh_course_url(pending_tasks, current_course_url)
       task_progress_service.save_queue(config.USERNAME, selected_course_name, pending_tasks)
       logger.always_print(
           f"已从任务队列缓存恢复课程进度：{selected_course_name}，剩余 {len(pending_tasks)} 个任务。"
       )
   else:
       if config.REFRESH_TASK_QUEUE:
           logger.info("REFRESH_TASK_QUEUE=True，将重新扫描课程任务并刷新断点队列。")
       pending_tasks = await browser_service.get_pending_tasks()
       pending_tasks = task_progress_service.refresh_course_url(pending_tasks, current_course_url)
       task_progress_service.save_queue(config.USERNAME, selected_course_name, pending_tasks)

   if not pending_tasks:
       logger.always_print("在本课程未找到任何待完成的任务。")
   else:
       logger.always_print(f"共发现 {len(pending_tasks)} 个待完成任务。")

       # 使用 rich.progress.Progress 上下文管理器来完全控制进度条和日志输出
       progress_columns = [
           TextColumn("[progress.description]{task.description}"),
           BarColumn(),
           MofNCompleteColumn(),
           TextColumn("•"),
           TimeElapsedColumn(),
       ]
       
       # transient=True 会在完成后移除进度条，保持终端清洁
       with Progress(*progress_columns, console=console, transient=True) as progress:
           # 使用 progress.track 迭代任务，它会自动处理进度更新
           for task in progress.track(pending_tasks, description="正在处理课程任务..."):
               # 使用 progress.log 在进度条上方打印状态信息，避免冲突
               progress.log(f"处理中: [单元 {task['unit_name']}] - {task['task_name']}")
               try:
                   await browser_service.navigate_to_task(task['course_url'], task['unit_index'], task['task_index'])
                   await run_strategy_on_current_page(browser_service, ai_service, cache_service)
                   await asyncio.sleep(2)
                   task_progress_service.mark_task_finished(config.USERNAME, selected_course_name, task)
               except RateLimitException:
                   raise
               except Exception as e:
                   logger.error(f"处理任务失败，已跳过当前任务: {e}")
                   await DiagnosticService.capture_page_failure(
                       browser_service,
                       "auto_task_failed",
                       e,
                       {
                           "unit_name": task.get("unit_name"),
                           "task_name": task.get("task_name"),
                           "unit_index": task.get("unit_index"),
                           "task_index": task.get("task_index"),
                       },
                   )
                   task_progress_service.mark_task_finished(config.USERNAME, selected_course_name, task)

       logger.always_print("所有待完成任务处理完毕！")

async def run_manual_debug_mode(browser_service: DriverService, ai_service: AIService, cache_service: CacheService):
   """运行手动调试模式，允许用户手动导航到页面后，由程序接管。"""
   config.IS_AUTO_MODE = False
   logger.always_print("已进入手动调试模式。")
   
   while True:
       user_input = await asyncio.to_thread(input, "请在浏览器中手动进入您想调试的题目页面，然后回到此处按Enter键继续 (输入 'q' 退出此模式): ")
       if user_input.lower() == 'q':
           break

       logger.always_print("程序已接管，开始分析当前页面...")
       logger.always_print("正在检查通用弹窗...")
       await browser_service.handle_common_popups()

       await run_strategy_on_current_page(browser_service, ai_service, cache_service)
       logger.always_print("-" * 20)

async def refresh_study_time_page(
   browser_service: DriverService,
   selected_course_index: int,
   course_url: str,
   selected_task: dict,
) -> str:
   """刷新刷时长页面；若登录态失效，则重新登录并回到原任务。"""
   logger.info("刷时长模式：正在定时刷新页面以维持登录态...")

   try:
       await browser_service.page.reload(wait_until="networkidle", timeout=60000)
   except Exception as e:
       logger.warning(f"刷新当前页面失败，将尝试恢复到原任务: {e}")

   await asyncio.sleep(1)

   if await browser_service.is_login_page():
       logger.warning("刷新后检测到已回到登录页，开始重新登录并恢复刷时长节点。")
       await browser_service.login()
       await browser_service.select_course_by_index(selected_course_index)
       course_url = browser_service.page.url
       await browser_service.navigate_to_task(course_url, selected_task["unit_index"], selected_task["task_index"])
       logger.success("已重新登录并回到刷时长任务页。")
       return course_url

   if not await browser_service.is_task_page_loaded():
       logger.warning("刷新后未检测到任务页，尝试重新进入刷时长任务。")
       await browser_service.navigate_to_task(course_url, selected_task["unit_index"], selected_task["task_index"])
   else:
       await browser_service.handle_common_popups()

   if config.STUDY_TIME_SIMULATE_ACTIVITY:
       await browser_service.simulate_foreground_activity()

   logger.info("刷时长模式：页面刷新检查完成。")
   return course_url

async def run_study_time_mode(browser_service: DriverService):
   """进入一个练习页并保活，用于累计课程学习时长。"""
   config.IS_AUTO_MODE = False
   logger.always_print("已进入刷时长模式。程序会进入一个练习页，定时刷新并处理长时间未操作弹窗。")

   courses = await browser_service.get_course_list()
   if not courses:
       logger.error("未能获取到任何课程，无法进入刷时长模式。")
       return

   logger.always_print("检测到以下课程：")
   for i, name in enumerate(courses):
       logger.always_print(f"[{i + 1}] {name}")

   selected_index = 0
   if len(courses) > 1:
       choice = -1
       while choice < 0 or choice >= len(courses):
           try:
               user_input = await asyncio.to_thread(input, f"请输入要刷时长的课程编号 (1-{len(courses)}): ")
               choice = int(user_input) - 1
               if choice < 0 or choice >= len(courses):
                   logger.warning("输入无效，请输入列表中的编号。")
           except ValueError:
               logger.warning("输入无效，请输入一个数字。")
       selected_index = choice
   else:
       logger.info("检测到只有一门课程，已自动选择。")

   await browser_service.select_course_by_index(selected_index)
   current_course_url = browser_service.page.url

   original_process_only_incomplete = config.PROCESS_ONLY_INCOMPLETE_TASKS
   config.PROCESS_ONLY_INCOMPLETE_TASKS = False
   try:
       candidate_tasks = await browser_service.get_pending_tasks()
   finally:
       config.PROCESS_ONLY_INCOMPLETE_TASKS = original_process_only_incomplete

   if not candidate_tasks:
       logger.error("未找到可进入的必修任务，无法刷时长。")
       return

   selected_task = None
   fallback_task = None
   for task in candidate_tasks:
       if fallback_task is None:
           fallback_task = task

       try:
           logger.info(f"尝试进入刷时长候选任务：[单元 {task['unit_name']}] - {task['task_name']}")
           await browser_service.navigate_to_task(current_course_url, task["unit_index"], task["task_index"])
           if await browser_service.current_page_has_reply():
               selected_task = task
               logger.success("已找到带 has-reply 作答区的练习页，将在此页面保活。")
               break

           logger.info("当前任务页不是 has-reply 类型，继续寻找下一个候选任务。")
       except Exception as e:
           logger.warning(f"进入候选任务失败，继续尝试下一个: {e}")

   if selected_task is None:
       selected_task = fallback_task
       logger.warning("未找到 has-reply 类型练习页，将进入第一个可用任务页保活。")
       await browser_service.navigate_to_task(current_course_url, selected_task["unit_index"], selected_task["task_index"])

   logger.always_print(
       f"刷时长页面已就绪：[单元 {selected_task['unit_name']}] - {selected_task['task_name']}。"
   )
   logger.always_print(
       f"页面将约每 {config.STUDY_TIME_REFRESH_INTERVAL_SECONDS} 秒刷新一次；每 {config.STUDY_TIME_ACTIVITY_INTERVAL_SECONDS} 秒执行一次保活检查。"
   )
   logger.always_print("保持此程序运行即可；需要结束时按 Ctrl+C 或直接关闭程序。")

   heartbeat_count = 0
   last_refresh_at = time.monotonic()
   while True:
       try:
           if time.monotonic() - last_refresh_at >= config.STUDY_TIME_REFRESH_INTERVAL_SECONDS:
               current_course_url = await refresh_study_time_page(
                   browser_service,
                   selected_index,
                   current_course_url,
                   selected_task,
               )
               last_refresh_at = time.monotonic()

           clicked = await browser_service.handle_idle_notice()
           if config.STUDY_TIME_SIMULATE_ACTIVITY:
               await browser_service.simulate_foreground_activity(heartbeat_count)

           heartbeat_count += 1
           if clicked:
               logger.info("保活弹窗已处理，继续挂时长。")
           elif heartbeat_count % 20 == 0:
               logger.info("刷时长模式运行中，未检测到长时间未操作弹窗。")
       except Exception as e:
           logger.warning(f"刷时长保活循环发生异常，将尝试重新进入目标任务: {e}")
           try:
               if await browser_service.is_login_page():
                   await browser_service.login()
                   await browser_service.select_course_by_index(selected_index)
                   current_course_url = browser_service.page.url
               await browser_service.navigate_to_task(current_course_url, selected_task["unit_index"], selected_task["task_index"])
               last_refresh_at = time.monotonic()
           except Exception as recover_error:
               logger.error(f"刷时长页面恢复失败，下一轮将继续尝试: {recover_error}")

       await asyncio.sleep(config.STUDY_TIME_ACTIVITY_INTERVAL_SECONDS)

async def run_listening_export_mode(browser_service: DriverService, ai_service: AIService, cache_service: CacheService):
   """遍历所有必修任务，导出音频听力选择题文本、选项和缓存答案。"""
   config.IS_AUTO_MODE = False
   logger.always_print("已进入听力保存模式。程序会遍历所有必修任务，只保存音频选择题，不提交答案。")

   courses = await browser_service.get_course_list()
   if not courses:
       logger.error("未能获取到任何课程，无法导出听力题。")
       return

   logger.always_print("检测到以下课程：")
   for i, name in enumerate(courses):
       logger.always_print(f"[{i + 1}] {name}")

   selected_index = 0
   if len(courses) > 1:
       choice = -1
       while choice < 0 or choice >= len(courses):
           try:
               user_input = await asyncio.to_thread(input, f"请输入要导出听力题的课程编号 (1-{len(courses)}): ")
               choice = int(user_input) - 1
               if choice < 0 or choice >= len(courses):
                   logger.warning("输入无效，请输入列表中的编号。")
           except ValueError:
               logger.warning("输入无效，请输入一个数字。")
       selected_index = choice
   else:
       logger.info("检测到只有一门课程，已自动选择。")

   await browser_service.select_course_by_index(selected_index)
   current_course_url = browser_service.page.url

   original_process_only_incomplete = config.PROCESS_ONLY_INCOMPLETE_TASKS
   config.PROCESS_ONLY_INCOMPLETE_TASKS = False
   try:
       candidate_tasks = await browser_service.get_pending_tasks()
   finally:
       config.PROCESS_ONLY_INCOMPLETE_TASKS = original_process_only_incomplete

   if not candidate_tasks:
       logger.error("未找到可遍历的必修任务，无法导出听力题。")
       return

   export_service = ListeningExportService(browser_service, ai_service, cache_service)
   all_entries = []
   output_file = config.LISTENING_EXPORT_FILE

   progress_columns = [
       TextColumn("[progress.description]{task.description}"),
       BarColumn(),
       MofNCompleteColumn(),
       TextColumn("•"),
       TimeElapsedColumn(),
   ]

   with Progress(*progress_columns, console=console, transient=True) as progress:
       for task in progress.track(candidate_tasks, description="正在导出听力题..."):
           progress.log(f"扫描中: [单元 {task['unit_name']}] - {task['task_name']}")
           try:
               await browser_service.navigate_to_task(task["course_url"], task["unit_index"], task["task_index"])
               task_entries = await export_service.collect_current_task_entries()
               if task_entries:
                   all_entries.extend(task_entries)
                   ListeningExportService.write_markdown(output_file, all_entries)
                   progress.log(f"已累计导出 {len(all_entries)} 道听力题。")
               await asyncio.sleep(1)
           except RateLimitException:
               raise
           except Exception as e:
               logger.error(f"导出当前任务失败，已跳过: {e}")
               await DiagnosticService.capture_page_failure(
                   browser_service,
                   "listening_export_task_failed",
                   e,
                   {
                       "unit_name": task.get("unit_name"),
                       "task_name": task.get("task_name"),
                       "unit_index": task.get("unit_index"),
                       "task_index": task.get("task_index"),
                   },
               )

   ListeningExportService.write_markdown(output_file, all_entries)
   logger.always_print(f"听力保存模式结束：共导出 {len(all_entries)} 道题，文件位置：{output_file}")

async def main():
   """程序主入口，提供模式选择。"""
   # 启动前检查并获取凭据
   if not await handle_credentials():
       logger.error("因凭据配置失败，程序无法继续运行。")
       return
   
   config.IS_AUTO_MODE = False

   browser_service = DriverService()
   try:
       await browser_service.start(headless=False)
       ai_service = await AIService.create()
       cache_service = CacheService()
       await browser_service.login()

       while True:
           logger.always_print("\n" + "="*30)
           logger.always_print("  请选择运行模式:")
           logger.always_print("  [1] 全自动模式 (扫描并完成所有任务)")
           logger.always_print("  [2] 手动调试模式 (针对特定页面进行调试)")
           logger.always_print("  [3] 快速缓存模式 (仅为客观题生成缓存)")
           logger.always_print("  [4] 刷时长模式 (进入练习页并自动处理长时间未操作弹窗)")
           logger.always_print("  [5] 听力保存模式 (导出音频听力选择题文档)")
           logger.always_print("  [6] 退出程序")
           logger.always_print("="*30)
           mode = await asyncio.to_thread(input, "请输入模式编号: ")

           if mode == '1':
               # config.PROCESS_ONLY_INCOMPLETE_TASKS = True
               await run_auto_mode(browser_service, ai_service, cache_service)
           elif mode == '2':
               await run_manual_debug_mode(browser_service, ai_service, cache_service)
           elif mode == '3':
               logger.info("已激活快速缓存模式。")
               config.FAST_CACHE_MODE = True
               config.PROCESS_ONLY_INCOMPLETE_TASKS = False
               await run_auto_mode(browser_service, ai_service, cache_service)
               # 重置标志以备下次选择
               config.FAST_CACHE_MODE = False
               config.PROCESS_ONLY_INCOMPLETE_TASKS = True
           elif mode == '4':
               await run_study_time_mode(browser_service)
           elif mode == '5':
               await run_listening_export_mode(browser_service, ai_service, cache_service)
           elif mode == '6':
               break
           else:
               logger.warning("输入无效，请输入 1, 2, 3, 4, 5 或 6。")

       logger.always_print("程序已结束。")

   except InvalidCredentialsException:
       logger.error("登录失败：提供的U校园账号或密码不正确。")
       logger.info("为了让您下次可以输入正确的凭据，程序将删除已保存的 .env 文件。")
       try:
           if os.path.exists(".env"):
               os.remove(".env")
               logger.success(".env 文件已删除。请重新运行程序以输入正确的凭据。")
       except OSError as e:
           logger.error(f"删除 .env 文件失败: {e}")
           logger.error("请手动删除 .env 文件后，再重新运行程序。")
   except RateLimitException:
       logger.error("程序因操作过于频繁被服务器限制，已自动终止。")
       logger.warning("请等待几分钟后，再重新运行本程序。")
   except Exception as e:
       logger.error(f"程序运行期间发生致命错误: {e}")
       await DiagnosticService.capture_page_failure(
           browser_service,
           "fatal_error",
           e,
       )
   finally:
       if browser_service:
           logger.always_print("正在关闭浏览器...")
           await browser_service.stop()

if __name__ == "__main__":
   asyncio.run(main())
