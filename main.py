import asyncio
import src.config as config
from src.services.driver_service import DriverService
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.strategies.checkbox_strategy import CheckboxStrategy
from src.strategies.single_choice import SingleChoiceStrategy
from src.strategies.read_aloud_strategy import ReadAloudStrategy
from src.strategies.multiple_choice_strategy import MultipleChoiceStrategy
from src.strategies.discussion_strategy import DiscussionStrategy
from src.strategies.drag_and_drop_strategy import DragAndDropStrategy
from src.strategies.fill_in_the_blank_strategy import FillInTheBlankStrategy
from src.strategies.short_answer_strategy import ShortAnswerStrategy
from src.strategies.qa_voice_strategy import QAVoiceStrategy

# ==============================================================================
# 全局可用策略列表
# 策略的顺序很重要，会按照从上到下的顺序进行检查。
# ==============================================================================
AVAILABLE_STRATEGIES = [
    ReadAloudStrategy,          # 文字朗读题
    QAVoiceStrategy,            # 语音简答题
    CheckboxStrategy,           # 自检打钩题
    DragAndDropStrategy,        # 拖拽排序题
    FillInTheBlankStrategy,     # 填空题
    ShortAnswerStrategy,        # 简答题
    MultipleChoiceStrategy,     # 多选题
    SingleChoiceStrategy,       # 单选题
    DiscussionStrategy          # 讨论题
]

async def run_strategy_on_current_page(browser_service: DriverService, ai_service: AIService, cache_service: CacheService):
    """
    在当前页面上智能执行解题策略。
    能够区分简单任务、"题中题"任务，并能优雅地处理无按钮的纯信息页面。
    """
    try:
        btn_text = ""
        try:
            # 使用更精确的选择器，只寻找我们关心的“提交”或“下一题”按钮
            action_btn = browser_service.page.locator(".btn:has-text('下一题'), .btn:has-text('提 交')").first
            await action_btn.wait_for(state="visible", timeout=3000)
            btn_text = await action_btn.text_content()
        except Exception:
            # 捕获超时等错误，意味着页面上很可能没有我们关心的按钮
            print("在页面上未找到‘提交’或‘下一题’按钮。")

        # 模式一：简单任务（直接提交）
        if "提 交" in btn_text:
            print("检测到“提交”按钮，执行单页策略...")
            current_strategy = None
            for StrategyClass in AVAILABLE_STRATEGIES:
                if await StrategyClass.check(browser_service):
                    current_strategy = StrategyClass(browser_service, ai_service, cache_service)
                    print(f"匹配到策略: {StrategyClass.__name__}")
                    break
            
            if current_strategy:
                # 正常执行，策略自己负责缓存和提交
                await current_strategy.execute(is_chained_task=False)
            else:
                print("在当前页面未找到适合的策略。")
            
        # 模式二：“题中题”任务（“下一题”循环）
        elif "下一题" in btn_text:
            print("检测到“下一题”按钮，启动“题中题”循环模式（缓存已禁用）。")
            shared_context = ""
            
            while True:
                current_strategy = None
                for StrategyClass in AVAILABLE_STRATEGIES:
                    if await StrategyClass.check(browser_service):
                        current_strategy = StrategyClass(browser_service, ai_service, cache_service)
                        print(f"匹配到子题策略: {StrategyClass.__name__}")
                        break
                
                if current_strategy:
                    try:
                        await current_strategy.execute(shared_context=shared_context, is_chained_task=True)
                    except Exception as e:
                        print(f"策略 {current_strategy.__class__.__name__} 执行时发生错误，终止当前任务链: {e}")
                        break # 发生错误，立即终止循环
                else:
                    print("当前子题未匹配到任何策略，尝试提取材料作为共享上下文...")
                    material = await browser_service._extract_additional_material_for_ai()
                    if material:
                        print("已提取到共享材料。")
                        shared_context += f"\n{material}"

                # 再次使用精确选择器定位操作按钮
                action_btn_loop = browser_service.page.locator(".btn:has-text('下一题'), .btn:has-text('提 交')").first
                await action_btn_loop.wait_for(state="visible", timeout=10000)
                current_btn_text = await action_btn_loop.text_content()

                if "下一题" in current_btn_text:
                    print("点击“下一题”，进入下一个子题...")
                    await action_btn_loop.click()
                    await asyncio.sleep(1) 
                    await browser_service.handle_common_popups()
                elif "提 交" in current_btn_text:
                    print("检测到最终“提交”按钮，正在提交任务...")
                    await action_btn_loop.click()
                    await browser_service.handle_submission_confirmation()
                    print("“题中题”任务完成。")
                    break
                else:
                    print(f"检测到未知按钮文本 '{current_btn_text}'，循环终止。")
                    break
        
        # 模式三：无按钮页面
        else:
            print("此页面无提交或下一题按钮，将检查是否有适用的无操作策略...")
            current_strategy = None
            for StrategyClass in AVAILABLE_STRATEGIES:
                if await StrategyClass.check(browser_service):
                    current_strategy = StrategyClass(browser_service, ai_service, cache_service)
                    print(f"匹配到策略: {StrategyClass.__name__}")
                    break
            
            if current_strategy:
                # 假设此策略执行后不需要提交
                await current_strategy.execute(is_chained_task=True) 
            else:
                print("未找到任何适用策略，此页面可能为纯信息页。继续下一个任务。")

    except Exception as e:
        print(f"执行策略期间发生错误: {e}")

async def run_auto_mode(browser_service: DriverService, ai_service: AIService, cache_service: CacheService):
   """运行全自动答题模式。"""
   # 1. 获取并选择课程
   courses = await browser_service.get_course_list()
   if not courses:
       print("未能获取到任何课程，程序终止。")
       return

   print("\n检测到以下课程：")
   for i, name in enumerate(courses):
       print(f"[{i + 1}] {name}")

   choice = -1
   while choice < 0 or choice >= len(courses):
       try:
           user_input = await asyncio.to_thread(input, f"请输入要进行的课程编号 (1-{len(courses)}): ")
           choice = int(user_input) - 1
           if choice < 0 or choice >= len(courses):
               print("输入无效，请输入列表中的编号。")
       except ValueError:
           print("输入无效，请输入一个数字。")

   await browser_service.select_course_by_index(choice)

   # 2. 获取待办任务列表
   pending_tasks = await browser_service.get_pending_tasks()

   if not pending_tasks:
       print("在本课程未找到任何待完成的任务。")
   else:
       print(f"共发现 {len(pending_tasks)} 个待完成任务。")

       # 3. 循环处理每个任务
       for task in pending_tasks:
           print(f"\n正在处理任务: [单元 {task['unit_name']}] - {task['task_name']}")
           await browser_service.navigate_to_task(task['course_url'], task['unit_index'], task['task_index'])
           await run_strategy_on_current_page(browser_service, ai_service, cache_service)
           await asyncio.sleep(2)

       print("\n所有待完成任务处理完毕！")

async def run_manual_debug_mode(browser_service: DriverService, ai_service: AIService, cache_service: CacheService):
   """运行手动调试模式，允许用户手动导航到页面后，由程序接管。"""
   print("\n已进入手动调试模式。")
   while True:
       user_input = await asyncio.to_thread(input, "请在浏览器中手动进入您想调试的题目页面，然后回到此处按Enter键继续 (输入 'q' 退出此模式): ")
       if user_input.lower() == 'q':
           break

       print("程序已接管，开始分析当前页面...")

       print("正在检查通用弹窗...")
       await browser_service.handle_common_popups()

       await run_strategy_on_current_page(browser_service, ai_service, cache_service)
       print("-" * 20)

async def main():
   """程序主入口，提供模式选择。"""
   if not all([config.USERNAME, config.PASSWORD, config.DEEPSEEK_API_KEY]):
       print("错误：请确保您已经从 .env.example 复制创建了 .env 文件，")
       print("并在其中填写了您的 U_USERNAME, U_PASSWORD, 和 DEEPSEEK_API_KEY。")
       return

   browser_service = DriverService()
   try:
       # 异步启动浏览器
       await browser_service.start(headless=False)

       # 初始化其他服务
       ai_service = AIService()
       cache_service = CacheService()

       # 异步登录
       await browser_service.login()

       # 模式选择循环
       while True:
           print("\n" + "="*30)
           print("  请选择运行模式:")
           print("  [1] 全自动模式 (扫描并完成所有任务)")
           print("  [2] 手动调试模式 (针对特定页面进行调试)")
           print("  [3] 退出程序")
           print("="*30)
           mode = await asyncio.to_thread(input, "请输入模式编号: ")

           if mode == '1':
               await run_auto_mode(browser_service, ai_service, cache_service)
           elif mode == '2':
               await run_manual_debug_mode(browser_service, ai_service, cache_service)
           elif mode == '3':
               break
           else:
               print("输入无效，请输入 1, 2, 或 3。")

       print("程序已结束。")

   except Exception as e:
       print(f"\n程序运行期间发生致命错误: {e}")
   finally:
       if browser_service:
           print("正在关闭浏览器...")
           await browser_service.stop()

if __name__ == "__main__":
   asyncio.run(main())