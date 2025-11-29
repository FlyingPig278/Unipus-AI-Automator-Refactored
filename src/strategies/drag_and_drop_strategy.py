import asyncio
import json
from playwright.async_api import Error as PlaywrightError
from src import prompts
from src.strategies.base_strategy import BaseStrategy
from src.services.driver_service import DriverService
from src.services.ai_service import AIService
from src.services.cache_service import CacheService

class DragAndDropStrategy(BaseStrategy):
    """
    处理拖拽排序题的策略。
    采用JS函数直接调用的方式，更新React组件状态来完成排序。
    实现了“缓存优先，AI后备”的逻辑。
    """

    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "drag_and_drop_js_injection"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        """检查当前页面是否为拖拽排序题。"""
        try:
            is_visible = await driver_service.page.locator("div#sortableListWrapper").first.is_visible(timeout=2000)
            if is_visible:
                print("检测到拖拽排序题，应用JS调用策略。")
                return True
        except PlaywrightError:
            return False
        return False

    async def execute(self) -> None:
        """执行拖拽题的JS函数调用逻辑，优先使用缓存。"""
        print("=" * 20)
        print("开始执行拖拽题策略 (JS函数调用模式)...")

        try:
            breadcrumb_parts = await self.driver_service.get_breadcrumb_parts()
            if not breadcrumb_parts:
                raise Exception("无法获取页面面包屑，终止策略。")

            cache_write_needed = False
            target_order = []

            # 1. 检查缓存
            task_page_cache = self.cache_service.get_task_page_cache(breadcrumb_parts)
            if task_page_cache and task_page_cache.get('type') == self.strategy_type and task_page_cache.get('answers'):
                print("在缓存中找到此页面的答案。")
                # 直接获取完整的答案列表
                target_order = task_page_cache['answers']
            
            # 2. 如果缓存未命中，则调用AI
            if not target_order:
                print("缓存未命中，将调用AI进行解答...")
                cache_write_needed = True
                
                transcript = await self._get_media_transcript()
                options_locators = await self.driver_service.page.locator("div.sequence-reply-view-item-text").all()
                options_text_list = [await loc.text_content() for loc in options_locators]
                options_text_for_ai = "\n".join([f"- {opt.strip()}" for opt in options_text_list])

                print(f"提取到 {len(options_text_list)} 个待排序选项。")

                prompt = prompts.DRAG_AND_DROP_PROMPT.format(
                    media_transcript=transcript,
                    options_list=options_text_for_ai
                )
                print("正在请求AI获取正确顺序...")
                ai_response = self.ai_service.get_chat_completion(prompt)
                if not ai_response or "ordered_options" not in ai_response:
                    raise Exception("未能从AI获取有效的排序结果。")
                
                target_order = ai_response["ordered_options"]
                print(f"AI返回的正确顺序: {', '.join(target_order)}")
            
            # 3. 准备并执行JS代码
            js_code = self._get_js_to_execute(target_order)
            print("正在页面中执行JS以更新题目顺序...")
            await self.driver_service.page.evaluate(js_code)
            print("JS代码执行完毕，UI应已更新。")

            # 4. 提交答案
            confirm = await asyncio.to_thread(input, "AI或缓存已更新答案顺序。是否确认提交？[Y/n]: ")
            if confirm.strip().upper() in ["Y", ""]:
                await self.driver_service.page.click(".btn")
                print("答案已提交。正在处理最终确认弹窗...")
                await self.driver_service.handle_submission_confirmation()

                if cache_write_needed:
                    print("准备从解析页面提取正确答案并写入缓存...")
                    await self._write_answers_to_cache(breadcrumb_parts)
            else:
                print("用户取消提交。")

        except Exception as e:
            print(f"执行拖拽题策略时发生错误: {e}")

    async def _get_media_transcript(self) -> str:
        """尝试转录页面上的视频或音频以获取上下文。"""
        media_url, media_type = await self.driver_service.get_media_source_and_type()
        if media_url:
            print(f"发现 {media_type} 文件，准备转写...")
            return self.ai_service.transcribe_media_from_url(media_url)
        return "无"

    def _get_js_to_execute(self, target_order: list[str]) -> str:
        """生成最终要在page.evaluate中执行的JS代码字符串。"""
        target_order_js_array = json.dumps(target_order)
        return f"""
        (function solveWithCapturedPayload() {{
            const TARGET_ORDER = {target_order_js_array};
            const dom = document.querySelector('#sortableListWrapper');
            if (!dom) {{ console.error("❌ 未找到 #sortableListWrapper"); return; }}
            const key = Object.keys(dom).find(k => k.startsWith('__reactFiber$'));
            if (!key) {{ console.error("❌ React 实例未挂载"); return; }}
            let fiber = dom[key];
            let targetInstance = null;
            let depth = 0;
            while (fiber && depth < 15) {{
                const instance = fiber.stateNode;
                if (instance && instance.state && Array.isArray(instance.state.options)) {{
                    targetInstance = instance;
                    break;
                }}
                fiber = fiber.return;
                depth++;
            }}
            if (!targetInstance) {{ console.error("❌ 未找到目标组件实例"); return; }}
            const currentOptions = targetInstance.state.options;
            const newOptions = [];
            TARGET_ORDER.forEach(val => {{
                const match = currentOptions.find(opt => opt.value === val);
                if (match) newOptions.push(match);
            }});
            const payloadDatas = TARGET_ORDER.map(val => ({{ value: [val] }}));
            targetInstance.setState({{ options: newOptions }}, () => {{
                if (targetInstance.props.dispatch) {{
                    const mockEvent = {{
                        type: 'componentValuesChangeEvent',
                        datas: payloadDatas,
                        toType: function() {{ return 'ComponentEvent'; }}
                    }};
                    targetInstance.props.dispatch(mockEvent);
                }}
            }});
        }})();
        """

    async def _write_answers_to_cache(self, breadcrumb_parts: list[str]):
        """导航到答案解析页面，提取正确答案，并写入缓存。"""
        try:
            await self.driver_service._navigate_to_answer_analysis_page()
            correct_answers_list = await self.driver_service.extract_all_correct_answers_from_analysis_page()

            if not correct_answers_list:
                print("警告：未能从解析页面提取到任何答案，无法更新缓存。" )
                return
            
            self.cache_service.save_task_page_answers(
                breadcrumb_parts,
                self.strategy_type,
                correct_answers_list
            )
        except Exception as e:
            print(f"写入缓存过程中发生错误: {e}")

    async def close(self):
        """此策略不管理需要关闭的资源。"""
        pass
			
