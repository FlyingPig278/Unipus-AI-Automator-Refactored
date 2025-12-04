import asyncio

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator

from src import prompts, config
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_voice_strategy import BaseVoiceStrategy
from src.utils import logger


class QAVoiceStrategy(BaseVoiceStrategy):
    """
    处理语音简答题的策略。
    该策略负责从页面提取问题，调用AI生成答案，然后通过语音上传。
    """
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
        try:
            # 检查是否有录音按钮，这是所有语音题的共同点
            record_button_selector = ".button-record"
            if not await driver_service.page.locator(record_button_selector).first.is_visible(timeout=1000):
                return False

            # 检查旧版或新版语音题的容器
            old_container = ".oral-personal-state-wrapper"
            new_container = ".oral-state-record-wrapper"
            
            # 使用 locator.or_() 来同时检查两种容器
            combined_locator = driver_service.page.locator(old_container).or_(driver_service.page.locator(new_container))
            
            if await combined_locator.first.is_visible(timeout=1000):
                logger.info("检测到语音简答题结构，应用QAVoiceStrategy。")
                return True
                
        except Exception:
            return False
        return False

    async def execute(self, shared_context: str = "", is_chained_task: bool = False) -> bool:
        logger.info("=" * 20)
        logger.info("开始执行语音问答策略 (QAVoiceStrategy)...")

        is_oral_recitation_type = await self.driver_service.page.locator(".oral-state-record-wrapper").first.is_visible(timeout=500)
        should_abort_page = False

        direction_text, additional_material, page_level_article_text = "", "", ""
        if not is_oral_recitation_type:
            logger.info("检测到『纯语音简答题』，将通过AI生成答案。")
            logger.info("正在并发提取页面级信息...")
            page_level_tasks = [ self._get_direction_text(), self.driver_service._extract_additional_material_for_ai() ]
            results = await asyncio.gather(*page_level_tasks)
            direction_text, additional_material = results
            logger.info("页面级信息提取完毕。")

            if "about the passage you have just read" in direction_text and not config.HAS_FETCHED_REMOTE_ARTICLE:
                logger.info("检测到需要返回前文获取文章的特殊语音题型。")
                try:
                    header_tasks_container = self.driver_service.page.locator(".pc-header-tasks-container")
                    current_active_tab_locator = header_tasks_container.locator(".pc-header-task-activity")
                    original_tab_title = await current_active_tab_locator.get_attribute("title")
                    first_tab_locator = header_tasks_container.locator(".pc-task").first
                    if not original_tab_title or not await first_tab_locator.is_visible():
                        raise Exception("无法找到当前激活的标签或第一个任务标签。")
                    logger.debug(f"正在从 '{original_tab_title}' 导航到第一个任务页获取文章...")
                    await first_tab_locator.click()
                    await self.driver_service.handle_common_popups()
                    await self.driver_service.page.locator(".layout-material-container").wait_for(timeout=15000)
                    logger.debug("正在提取文章内容...")
                    page_level_article_text = await self.driver_service._extract_additional_material_for_ai()
                    if not page_level_article_text:
                        logger.warning("已跳转到文章页，但未能提取到文章文本。")
                    logger.debug(f"文章提取完毕，正在返回 '{original_tab_title}'...")
                    original_tab_locator = header_tasks_container.locator(f'[title="{original_tab_title}"]')
                    await original_tab_locator.click()
                    await self.driver_service.page.locator(".p-oral-personal-state .oral-personal-state-wrapper").wait_for(timeout=15000)
                    logger.success("已成功返回问题页面。")
                    config.HAS_FETCHED_REMOTE_ARTICLE = True
                    logger.info("远程文章获取状态锁已激活，本次“题中题”不再重复跳转。")
                except Exception as e:
                    logger.error(f"在返回获取文章的过程中发生严重错误，将中止任务: {e}")
                    return False
        else:
            logger.info("检测到『口语陈述题』，将根据主问题和笔记扩展成句子。")

        all_question_containers = []
        if is_oral_recitation_type:
            all_question_containers = await self.driver_service.page.locator(".oral-container.oral-state-record-margin").all()
        else:
            all_question_containers = await self.driver_service.page.locator(".p-oral-personal-state .oral-personal-state-wrapper").all()

        logger.info(f"发现 {len(all_question_containers)} 个语音题容器。")

        for i, container in enumerate(all_question_containers):
            logger.info(f"\n--- 开始处理第 {i + 1} 个语音题 ---")
            try:
                prompt = ""
                if is_oral_recitation_type:
                    main_question_locator = container.locator(".score-sentence-container .component-htmlview")
                    main_question = (await main_question_locator.text_content() or "").strip()

                    content_elements = await container.locator(".sentence-container .media-sentenceContainer").all()
                    all_content_texts = []
                    for elem in content_elements:
                        text = (await elem.text_content() or "").strip()
                        if text:
                            all_content_texts.append(text)
                    keywords_text = "\n".join(all_content_texts)

                    if not keywords_text:
                        logger.error("在当前容器中找不到关键词笔记，中止。")
                        should_abort_page = True
                        break
                    
                    logger.info(f"提取到主问题: '{main_question}'")
                    logger.info(f"提取到关键词: '{keywords_text}'")
                    prompt = prompts.ORAL_RECITATION_PROMPT.format(main_question=main_question, keywords=keywords_text)
                else:
                    question_locator = container.locator(".oral-personal-state-oral-container .oral-personal-state-sentence-container .component-htmlview")
                    logger.info("正在并发提取当前题目信息...")
                    sub_question_tasks = [self._get_article_text(container=container), question_locator.text_content(timeout=5000)]
                    results = await asyncio.gather(*sub_question_tasks)
                    current_question_media_text, question_text_raw = results[0], (results[1] or "")
                    logger.info("当前题目信息提取完毕。")

                    if not question_text_raw.strip():
                        logger.error("在当前容器中找不到问题文本，中止。")
                        should_abort_page = True
                        break
                    
                    question_text = question_text_raw.strip()
                    logger.info(f"提取到问题文本: '{question_text}'")
                    combined_article_text = f"{page_level_article_text}\n{current_question_media_text}\n{shared_context}".strip()
                    prompt = prompts.QAVOICE_PROMPT.format(direction_text=direction_text, article_text=combined_article_text, additional_material=additional_material, question_text=question_text)
                
                if not config.IS_AUTO_MODE:
                    logger.info("=" * 50)
                    logger.info("即将发送给 AI 的完整 Prompt 如下：")
                    logger.info(prompt)
                    logger.info("=" * 50)
                if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                    confirm = await asyncio.to_thread(input, "是否确认发送此 Prompt？[Y/n]: ")
                    if confirm.strip().upper() not in ["Y", ""]:
                        logger.warning("用户取消了 AI 调用，终止当前任务。")
                        should_abort_page = True
                        break
                json_data = self.ai_service.get_chat_completion(prompt)
                if not json_data or "answer" not in json_data:
                    logger.error("AI未能生成有效答案或返回格式不正确，中止当前页面。")
                    should_abort_page = True
                    break
                answer_text = json_data.get("answer")
                logger.info(f"AI生成的答案: '{answer_text}'")
                succeeded, should_abort_from_task = await self._execute_single_voice_task(container=container, ref_text=answer_text, retry_params=self.RETRY_PARAMS)
                if should_abort_from_task:
                    should_abort_page = True
                    break

            except Exception as e:
                logger.error(f"处理第 {i + 1} 个语音题时发生严重错误: {e}")
                should_abort_page = True
                break
            finally:
                await self._cleanup_one_shot_injection()
        
        logger.info("\n所有语音简答题处理完毕。")
        if should_abort_page:
            logger.warning("由于发生错误或分数不达标，已中止最终提交。")
            return False
        if not is_chained_task:
            should_submit = True
            if not (config.IS_AUTO_MODE and config.AUTO_MODE_NO_CONFIRM):
                confirm = await asyncio.to_thread(input, "所有语音简答题均已完成且分数达标。是否确认提交？[Y/n]: ")
                if confirm.strip().upper() not in ["Y", ""]:
                    should_submit = False
            
            if should_submit:
                await self.driver_service.page.click(".btn")
                logger.info("答案已提交。正在处理最终确认弹窗...")
                await self.driver_service.handle_submission_confirmation()
            else:
                logger.warning("用户取消提交。")
                return False
        
        return True

    async def _get_article_text(self, container: Locator | None = None) -> str:
        search_scope = container if container else self.driver_service.page
        media_url, media_type = await self.driver_service.get_media_source_and_type(search_scope=search_scope)
        if media_url:
            logger.info(f"发现 {media_type} 文件，准备转写: {media_url}")
            try:
                article_text = self.ai_service.transcribe_media_from_url(media_url)
                if not article_text:
                    logger.warning("媒体文件转写失败。")
                return article_text
            except Exception as e:
                logger.error(f"媒体文件转写时发生错误: {e}")
                return ""
        
        try:
            article_locator = search_scope.locator(".comp-common-article-content").first
            if await article_locator.is_visible(timeout=500):
                logger.debug("发现文章容器，正在提取文本...")
                return await article_locator.text_content()
        except PlaywrightError:
            pass

        logger.info("未在本页/容器内找到可用的音频、视频或文章。")
        return ""

