import asyncio
import os
import src.config as config
from src.credentials_handler import handle_credentials
from src.services.driver_service import DriverService, RateLimitException, InvalidCredentialsException
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.utils import logger, console
from src.strategies.checkbox_strategy import CheckboxStrategy
from src.strategies.single_choice import SingleChoiceStrategy
from src.strategies.read_aloud_strategy import ReadAloudStrategy
from src.strategies.multiple_choice_strategy import MultipleChoiceStrategy
from src.strategies.discussion_strategy import DiscussionStrategy
from src.strategies.drag_and_drop_strategy import DragAndDropStrategy
from src.strategies.fill_in_the_blank_strategy import FillInTheBlankStrategy
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
    ]
    
    # 创建一个本次运行要使用的策略列表副本
    strategies_to_run = AVAILABLE_STRATEGIES

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
        strategies_to_run = [s for s in AVAILABLE_STRATEGIES if s in cacheable_strategies]

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
                await current_strategy.execute(is_chained_task=False)
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
                            break 
                    except Exception as e:
                        logger.error(f"策略 {current_strategy_instance.__class__.__name__} 执行时发生错误，终止当前任务链: {e}")
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
                    await current_strategy.execute(is_chained_task=False)
                # 在快速缓存模式下，不执行NoReply等非缓存策略
                elif not config.FAST_CACHE_MODE:
                     await current_strategy.execute(is_chained_task=True)
                else:
                    logger.info(f"快速缓存模式：跳过非缓存策略 {current_strategy.__class__.__name__}。")

            else:
                logger.info("未找到任何适用策略，此页面可能为纯信息页。继续下一个任务。")

    except Exception as e:
        logger.error(f"执行策略期间发生错误: {e}")

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

   pending_tasks = await browser_service.get_pending_tasks()

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
               await browser_service.navigate_to_task(task['course_url'], task['unit_index'], task['task_index'])
               await run_strategy_on_current_page(browser_service, ai_service, cache_service)
               await asyncio.sleep(2)

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
           logger.always_print("  [4] 退出程序")
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
               break
           else:
               logger.warning("输入无效，请输入 1, 2, 或 3。")

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
   finally:
       if browser_service:
           logger.always_print("正在关闭浏览器...")
           await browser_service.stop()

if __name__ == "__main__":
   asyncio.run(main())