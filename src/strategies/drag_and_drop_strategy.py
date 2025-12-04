import asyncio
import json
from playwright.async_api import Error as PlaywrightError
from src import prompts, config
from src.strategies.base_strategy import BaseStrategy
from src.services.driver_service import DriverService
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.utils import logger

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
                logger.info("检测到拖拽排序题，应用JS调用策略。")
                return True
        except PlaywrightError:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False, sub_task_index: int = -1) -> tuple[bool, bool]:
        logger.info("=" * 20)
        logger.info("开始执行拖拽题策略 (JS函数调用模式)...")

        try:
            breadcrumb_parts = await self.driver_service.get_breadcrumb_parts()
            if not breadcrumb_parts:
                raise Exception("无法获取页面面包屑，终止策略。")

            cache_write_needed = False
            target_order = []
            use_cache = False

            if not is_chained_task:
                task_page_cache = self.cache_service.get_task_page_cache(breadcrumb_parts)
                if not config.FORCE_AI and task_page_cache and task_page_cache.get('type') == self.strategy_type and task_page_cache.get('answers'):
                    logger.info("在缓存中找到此页面的答案。")
                    target_order = task_page_cache['answers']
                    use_cache = True
                elif config.FORCE_AI and task_page_cache:
                    logger.info("FORCE_AI为True，强制忽略缓存，调用AI。")
            
            if not target_order:
                if is_chained_task:
                    logger.info("处于“题中题”模式，跳过缓存，直接调用AI。")
                else:
                    logger.info("缓存未命中，将调用AI进行解答...")
                
                cache_write_needed = not is_chained_task
                
                logger.info("正在并发提取媒体、材料等信息...")
                tasks = [
                    self._get_media_transcript(),
                    self.driver_service._extract_additional_material_for_ai()
                ]
                results = await asyncio.gather(*tasks)
                transcript, additional_material = results
                logger.info("信息提取完毕。")
                
                full_context = f"{shared_context}\n{transcript}\n{additional_material}".strip()

                options_locators = await self.driver_service.page.locator("div.sequence-reply-view-item-text").all()
                options_text_list = [await loc.text_content() for loc in options_locators]
                options_text_for_ai = "\n".join([f"- {opt.strip()}" for opt in options_text_list])

                logger.info(f"提取到 {len(options_text_list)} 个待排序选项。")

                prompt = prompts.DRAG_AND_DROP_PROMPT.format(
                    media_transcript=full_context,
                    options_list=options_text_for_ai
                )

                if not config.IS_AUTO_MODE:
                    logger.info("=" * 50)
                    logger.info("即将发送给 AI 的完整 Prompt 如下：")
                    logger.info(prompt)
                    logger.info("=" * 50)
                
                if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                    confirm = await asyncio.to_thread(input, "是否确认发送此 Prompt？[Y/n]: ")
                    if confirm.strip().upper() not in ["Y", ""]:
                        logger.warning("用户取消了 AI 调用，终止当前任务。")
                        return False, False

                logger.info("正在请求AI获取正确顺序...")
                ai_response = self.ai_service.get_chat_completion(prompt)
                if not ai_response or "ordered_options" not in ai_response:
                    logger.error("未能从AI获取有效的排序结果。")
                    return False, False
                
                target_order = ai_response["ordered_options"]
                logger.info(f"AI返回的正确顺序: {', '.join(target_order)}")
            
            js_code = self._get_js_to_execute(target_order)
            logger.debug("正在页面中执行JS以更新题目顺序...")
            await self.driver_service.page.evaluate(js_code)
            logger.success("JS代码执行完毕，UI应已更新。")

            if not is_chained_task:
                should_submit = True
                if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                    confirm = await asyncio.to_thread(input, "AI或缓存已更新答案顺序。是否确认提交？[Y/n]: ")
                    if confirm.strip().upper() not in ["Y", ""]:
                        should_submit = False

                if should_submit:
                    await self.driver_service.page.click(".btn")
                    await self.driver_service.handle_rate_limit_modal()
                    logger.info("答案已提交。正在处理最终确认弹窗...")
                    await self.driver_service.handle_submission_confirmation()

                    if cache_write_needed:
                        logger.info("准备从解析页面提取正确答案并写入缓存...")
                        await self._write_answers_to_cache(breadcrumb_parts)
                    return True, cache_write_needed
                else:
                    logger.warning("用户取消提交。")
                    return False, False
            else:
                return True, cache_write_needed

        except Exception as e:
            logger.error(f"执行拖拽题策略时发生错误: {e}")
            return False, False

    async def _get_media_transcript(self) -> str:
        media_url, media_type = await self.driver_service.get_media_source_and_type()
        if media_url:
            logger.info(f"发现 {media_type} 文件，准备转写...")
            return self.ai_service.transcribe_media_from_url(media_url)
        return "无"

    def _get_js_to_execute(self, target_order: list[str]) -> str:
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
        try:
            await self.driver_service._navigate_to_answer_analysis_page()
            correct_answers_list = await self.driver_service.extract_all_correct_answers_from_analysis_page()

            if not correct_answers_list:
                logger.warning("未能从解析页面提取到任何答案，无法更新缓存。" )
                return
            
            self.cache_service.save_task_page_answers(
                breadcrumb_parts,
                self.strategy_type,
                correct_answers_list
            )
        except Exception as e:
            logger.error(f"写入缓存过程中发生错误: {e}")

    async def close(self):
        pass
			
