from playwright.async_api import Error as PlaywrightError
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_strategy import BaseStrategy
from src.utils import logger


class NoReplyStrategy(BaseStrategy):
    """
    处理纯信息展示页面（无作答区域）的策略。
    这些页面通常包含需要播放的媒体文件，播放完毕后任务即算完成。
    本策略通过执行一段特定的JS代码来直接调用后端的提交函数，从而绕过媒体播放。
    """
    def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
        super().__init__(driver_service, ai_service, cache_service)
        self.strategy_type = "no_reply"

    @staticmethod
    async def check(driver_service: DriverService) -> bool:
        """
        检查当前页面是否为纯信息页，且必须包含媒体文件。
        判断依据是页面主要容器 .layoutBody-container 是否缺少 .has-reply class，
        同时页面上存在可播放的媒体文件。
        """
        try:
            # 1. 检查页面是否无作答区域
            container = driver_service.page.locator(".layoutBody-container")
            if await container.count() > 0:
                class_attr = await container.first.get_attribute("class")
                # 必须没有作答区域
                if class_attr and "has-reply" not in class_attr:
                    # 辅助判断：确保页面不是空的或错误的，且必须有 material
                    if await driver_service.page.locator(".question-common-abs-material").count() > 0:
                        # 2. 检查是否存在媒体文件
                        media_url, _ = await driver_service.get_media_source_and_type()
                        if media_url:
                            logger.info("检测到页面无作答区域，且包含媒体文件，应用“无作答页面策略”。")
                            return True
                        else:
                            logger.info("检测到页面无作答区域，但未发现媒体文件，不应用“无作答页面策略”。")
                            return False
                    else:
                        logger.info("检测到页面无作答区域，但无 .question-common-abs-material，不应用“无作答页面策略”。")
                        return False
                else:
                    logger.info("检测到页面有作答区域 (含has-reply class)，不应用“无作答页面策略”。")
                    return False
            else:
                logger.info("未找到 .layoutBody-container，不应用“无作答页面策略”。")
                return False
        except PlaywrightError as e:
            logger.error(f"检查 NoReplyStrategy 时出错: {e}")
            return False
        except Exception as e:
            logger.error(f"在 NoReplyStrategy 检查媒体文件时发生异常: {e}")
            return False
        return False # Fallback

    async def execute(self, shared_context: str = "", is_chained_task: bool = False, sub_task_index: int = -1) -> tuple[bool, bool]:
        logger.info("="*20)
        logger.info("开始执行“无作答页面”策略...")

        # 用户提供的、用于直接调用内部JS函数完成任务的脚本
        submission_script = """
        (async function() {
            console.log("🚀 开始执行：基于内部路由的精准提交脚本...");

            try {
                // 1. Webpack 挂钩
                let webpackReq;
                const chunkName = 'webpackChunkexploration_pc';
                if (!window[chunkName]) {
                    console.error("❌ 未找到 Webpack 对象: " + chunkName);
                    return { success: false, message: "未找到 Webpack 对象: " + chunkName };
                }

                window[chunkName].push([
                    ['__hack_page_manager_' + Math.random()], 
                    {},
                    (r) => { webpackReq = r; }
                ]);

                // 2. 获取核心模块
                const mod = webpackReq(66115);
                if (!mod || !mod.rM || !mod.Xf) {
                    console.error("❌ 核心模块(66115)加载失败");
                    return { success: false, message: "核心模块(66115)加载失败" };
                }

                // 3. 获取关键管理器实例
                const dummyController = new mod.Xf();
                const AnswerManager = dummyController._courseAnswerManager;
                const PageManager = dummyController._pageManger;

                if (!PageManager) {
                    console.error("❌ 无法获取 PageManager (页面管理器)。");
                    return { success: false, message: "无法获取 PageManager" };
                }

                // 4. [核心] 直接询问 APP：当前是哪一页？
                const pageState = PageManager.getCurPage();
                
                if (!pageState || !pageState.pid) {
                    console.error("❌ 无法获取当前页面状态。请尝试点击一下左侧目录刷新状态。");
                    return { success: false, message: "无法获取当前页面状态" };
                }

                const currentGroupId = pageState.pid;
                console.log(`📍 系统内部锁定当前 Group ID: %c${currentGroupId}`, "color: blue; font-weight: bold;");

                // 5. 获取当前页面的所有任务 ID
                let targetIds = pageState.ids || [];
                
                if (targetIds.length === 0) {
                    const CourseManager = mod.rM.getInstance();
                    targetIds = CourseManager.getQuesIds(currentGroupId) || [];
                }

                if (targetIds.length === 0) {
                    console.warn("⚠️ 未发现子题目 ID，尝试提交 Group ID 本身。");
                    targetIds = [currentGroupId];
                }

                console.log(`🎯 准备提交以下任务 ID:`, targetIds);

                // 6. 执行提交
                for (const qid of targetIds) {
                    console.log(`⚡️ [${qid}] 正在提交...`);
                    
                    const payload = {
                        quesDatas: [],
                        groupId: currentGroupId,
                        isCompleted: [],
                        thirdPartyJudges: "[]",
                        submitType: 2,
                        hideLoading: true,
                        associationGroupId: "",
                        version: "default"
                    };

                    try {
                        await AnswerManager._submitDebounce(payload);
                        console.log(`✅ [${qid}] 请求已发送`);
                    } catch (e) {
                        if (e && (e.message.includes("Unexpected") || e.name === 'SyntaxError')) {
                            console.log(`✅ [${qid}] 提交成功 (服务器返回了空响应)`);
                        } else {
                            console.error(`❌ [${qid}] 提交异常:`, e);
                        }
                    }
                    
                    await new Promise(r => setTimeout(r, 500));
                }

                console.log("%c🏁 执行结束！请刷新页面查看进度。", "color: red; font-weight: bold;");
                return { success: true, message: "执行成功" };

            } catch (err) {
                console.error("❌ 执行精准提交脚本时发生意外错误:", err);
                return { success: false, message: err.message };
            }
        })();
        """

        try:
            result = await self.driver_service.page.evaluate(submission_script)
            if result and result.get('success'):
                logger.success(f"成功执行了JS提交脚本: {result.get('message')}")
                return True, False
            else:
                error_message = result.get('message') if result else '未知JS执行错误'
                logger.error(f"执行JS提交脚本失败: {error_message}")
                return False, False
        except Exception as e:
            logger.error(f"调用JS脚本时发生Playwright错误: {e}")
            return False, False
    async def close(self) -> None:
        pass
