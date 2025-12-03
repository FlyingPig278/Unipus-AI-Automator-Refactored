import asyncio
from typing import List, Dict, Any
from playwright.async_api import Locator # 新增导入
from playwright.async_api import Error as PlaywrightError
from src import prompts  # 新增导入
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_voice_strategy import BaseVoiceStrategy


class QAVoiceStrategy(BaseVoiceStrategy):
    """
    处理语音简答题的策略。
    该策略负责从页面提取问题，调用AI生成答案，然后通过语音上传。
    """

    # 语音简答题的重试参数，可能需要与朗读题不同
    RETRY_PARAMS = [
        {'length_scale': 1.0, 'noise_scale': 0.2, 'noise_w': 0.2, 'description': "正常语速，低噪声"},
        {'length_scale': 0.9, 'noise_scale': 0.33, 'noise_w': 0.4, 'description': "稍快语速，中等噪声"},
        {'length_scale': 1.1, 'noise_scale': 0.1, 'noise_w': 0.1, 'description': "稍慢语速，极低噪声"},
    ]

    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "qa_voice"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        """
        检查当前页面是否为语音简答题目。
        通过检测录音按钮和特定的问题容器结构来判断。
        """
        try:
            # 检测核心容器
            main_container_selector = ".oral-personal-state-wrapper"
            is_main_container_visible = await driver_service.page.locator(main_container_selector).first.is_visible(timeout=1000)

            # 检测录音按钮
            record_button_selector = ".button-record"
            is_record_button_visible = await driver_service.page.locator(record_button_selector).first.is_visible(timeout=1000)

            if is_main_container_visible and is_record_button_visible:
                print("检测到语音简答题结构，应用QAVoiceStrategy。")
                return True
        except Exception:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        """
        执行语音简答题的回答流程。
        包含一个特殊逻辑：如果检测到题目指示需要前文，则会自动导航到Activity 1获取文章，然后再返回作答。
        """
        print("=" * 20)
        print("开始执行语音简答策略...")

        # 1. 检查是否需要返回获取文章 (页面级别逻辑，只执行一次)
        direction_text = await self._get_direction_text()
        page_level_article_text = "" # 用于存储跨页获取的文章
        
        # 通过模糊匹配判断是否属于需要返回前文的特殊题型
        if "about the passage you have just read" in direction_text:
            print("检测到需要返回前文获取文章的特殊语音题型。")
            try:
                # a. 记录当前激活tab的稳定属性（title），并找到第一个tab
                header_tasks_container = self.driver_service.page.locator(".pc-header-tasks-container")
                current_active_tab_locator = header_tasks_container.locator(".pc-header-task-activity")
                original_tab_title = await current_active_tab_locator.get_attribute("title")

                first_tab_locator = header_tasks_container.locator(".pc-task").first
                
                if not original_tab_title or not await first_tab_locator.is_visible():
                    raise Exception("无法找到当前激活的标签或第一个任务标签。")

                # b. 点击第一个tab以导航到文章页面
                print(f"正在从 '{original_tab_title}' 导航到第一个任务页获取文章...")
                await first_tab_locator.click()

                print("正在检查通用弹窗...")
                await self.driver_service.handle_common_popups()

                await self.driver_service.page.locator(".layout-material-container").wait_for(timeout=15000)
                
                # c. 抓取文章内容
                print("正在提取文章内容...")
                page_level_article_text = await self.driver_service._extract_additional_material_for_ai() # 直接从文字材料中提取
                if not page_level_article_text:
                    print("警告：已跳转到文章页，但未能提取到文章文本。")

                # d. 使用title属性构建稳定的locator，返回原始问题页面
                print(f"文章提取完毕，正在返回 '{original_tab_title}'...")
                original_tab_locator = header_tasks_container.locator(f'[title="{original_tab_title}"]')
                await original_tab_locator.click()
                await self.driver_service.page.locator(".p-oral-personal-state .oral-personal-state-wrapper").wait_for(timeout=15000)
                print("已成功返回问题页面。")

            except Exception as e:
                print(f"在返回获取文章的过程中发生严重错误，将中止任务: {e}")
                return False
        
        # 2. 页面级别的额外材料 (在循环外，因为通常对整个页面有效)
        additional_material = await self.driver_service._extract_additional_material_for_ai()
        
        question_containers_selector = ".p-oral-personal-state .oral-personal-state-wrapper"
        all_question_containers = await self.driver_service.page.locator(question_containers_selector).all()
        print(f"发现 {len(all_question_containers)} 个语音简答题容器。")

        should_abort_page = False

        for i, container in enumerate(all_question_containers):
            print(f"\n--- 开始处理第 {i + 1} 个语音简答题 ---")

            try:
                # 3. 针对当前子题，提取其内部的媒体文件
                current_question_media_text = await self._get_article_text(container=container)
                
                # 4. 提取子题问题文本
                question_locator = container.locator(".oral-personal-state-oral-container .oral-personal-state-sentence-container .component-htmlview")
                if not await question_locator.is_visible(timeout=5000):
                    print("错误：在当前容器中找不到问题文本元素，中止本页所有语音简答题。")
                    should_abort_page = True
                    break
                question_text = (await question_locator.text_content()).strip()
                print(f"提取到问题文本: '{question_text}'")

                # 5. 组合所有上下文信息
                combined_article_text = ""
                if page_level_article_text:
                    combined_article_text += page_level_article_text + "\n"
                if current_question_media_text:
                    combined_article_text += current_question_media_text + "\n"
                if shared_context:
                    combined_article_text += shared_context + "\n"

                prompt = prompts.QAVOICE_PROMPT.format(
                    direction_text=direction_text,
                    article_text=combined_article_text.strip(),
                    additional_material=additional_material,
                    question_text=question_text
                )

                print("=" * 50)
                print("即将发送给 AI 的完整 Prompt 如下：")
                print(prompt)
                print("=" * 50)
                confirm = await asyncio.to_thread(input, "是否确认发送此 Prompt？[Y/n]: ")
                if confirm.strip().upper() not in ["Y", ""]:
                    print("用户取消了 AI 调用，终止当前任务。")
                    should_abort_page = True
                    break

                json_data = self.ai_service.get_chat_completion(prompt)
                
                if not json_data or "answer" not in json_data:
                    print("AI未能生成有效答案或返回格式不正确，中止当前页面。")
                    should_abort_page = True
                    break

                answer_text = json_data.get("answer")
                print(f"AI生成的答案: '{answer_text}'")

                succeeded, should_abort_from_task = await self._execute_single_voice_task(
                    container=container,
                    ref_text=answer_text,
                    retry_params=self.RETRY_PARAMS
                )

                if should_abort_from_task:
                    should_abort_page = True
                    break

            except Exception as e:
                print(f"处理第 {i + 1} 个语音简答题时发生严重错误: {e}")
                should_abort_page = True
                break
            finally:
                await self._cleanup_injection()

        print("\n所有语音简答题处理完毕。")

        if should_abort_page:
            print("由于发生错误或分数不达标，已中止最终提交。")
            return False

        # 如果不是“题中题”的一部分，则执行提交流程
        if not is_chained_task:
            confirm = await asyncio.to_thread(input, "所有语音简答题均已完成且分数达标。是否确认提交？[Y/n]: ")
            if confirm.strip().upper() in ["Y", ""]:
                await self.driver_service.page.click(".btn")
                print("答案已提交。正在处理最终确认弹窗...")
                await self.driver_service.handle_submission_confirmation()
            else:
                print("用户取消提交。")
                return False
        
        return True # 所有操作成功完成

    async def _get_article_text(self, container: Locator | None = None) -> str:
        """
        提取文章或听力原文（音频或视频）。
        如果提供了container，则只在该container内部查找媒体。
        """
        search_scope = container if container else self.driver_service.page
        media_url, media_type = await self.driver_service.get_media_source_and_type(search_scope=search_scope)
        if media_url:
            print(f"发现 {media_type} 文件，准备转写: {media_url}")
            try:
                article_text = self.ai_service.transcribe_media_from_url(media_url)
                if not article_text:
                    print("警告：媒体文件转写失败。")
                return article_text
            except Exception as e:
                print(f"媒体文件转写时发生错误: {e}")
                return ""
        
        # 尝试查找常规文章容器（可能在container内，也可能在全局）
        try:
            article_locator = search_scope.locator(".comp-common-article-content").first
            if await article_locator.is_visible(timeout=500):
                print("发现文章容器，正在提取文本...")
                return await article_locator.text_content()
        except PlaywrightError:
            pass # 未找到，继续

        print("未在本页/容器内找到可用的音频、视频或文章。")
        return ""

    async def _get_direction_text(self) -> str:
        """提取题目说明文字。"""
        try:
            return await self.driver_service.page.locator(".abs-direction").text_content()
        except Exception:
            print("未找到题目说明（Direction）。")
            return ""


