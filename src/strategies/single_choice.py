from selenium.webdriver.common.by import By

from src import prompts, config
from src.services.ai_service import AIService
from src.services.cache_service import CacheService
from src.services.driver_service import DriverService
from src.strategies.base_strategy import BaseStrategy
from selenium.webdriver.support import expected_conditions as EC


class SingleChoiceStrategy(BaseStrategy):
   """
   单选题的处理策略。
   适用于页面上包含明确的A, B, C, D选项的题目。
   实现了“缓存优先，AI后备”的逻辑。
   """
   def __init__(self, driver_service: DriverService, ai_service: AIService, cache_service: CacheService):
       super().__init__(driver_service, ai_service, cache_service)
       self.strategy_type = "single_choice"

   @staticmethod
   def check(driver_service: DriverService) -> bool:
       """检查当前页面是否为单选题。"""
       try:
           # 检查题目区域和选项区域是否存在
           driver_service.driver.find_element(By.CSS_SELECTOR, config.QUESTION_WRAP) # 整体题目区域
           driver_service.driver.find_element(By.CSS_SELECTOR, config.QUESTION_OPTION_WRAP) # 选项区域
           print("页面初步符合[单选题]特征，应用单选题策略。")
           return True
       except:
           return False

   def _get_full_question_text_for_ai(self, question_wrap_element) -> str:
       """
       从单个题目区块中提取完整的题目和选项文本，用于AI Prompt。
       这是为了给AI提供尽可能完整的上下文。
       """
       # 获取整个题目区块的文本，这会包含题目、选项，但不含解析（因为还没提交）
       return question_wrap_element.text.strip()

   def execute(self) -> None:
       """执行单选题的解题逻辑，优先从缓存中查找答案。"""
       print("=" * 20)
       print("开始执行单选题策略...")

       try:
           breadcrumb_parts = self.driver_service.get_breadcrumb_parts()
           original_question_wraps = self.driver_service.driver.find_elements(By.CSS_SELECTOR, config.QUESTION_WRAP)
           if not breadcrumb_parts or not original_question_wraps:
               print("错误：无法获取页面关键信息（面包屑或题目），终止策略。")
               return
       except Exception as e:
           print(f"提取面包屑或题目容器时出错: {e}")
           return

       cache_write_needed = False
       answers_to_fill = []

       # 1. 一次性获取整个页面的缓存
       task_page_cache = self.cache_service.get_task_page_cache(breadcrumb_parts)

       all_questions_in_cache = False
       if task_page_cache and task_page_cache.get('type') == self.strategy_type:
           print("在缓存中找到此页面的记录，尝试匹配所有题目...")
           cached_questions = task_page_cache.get('questions', {})
           temp_answers = []
           all_found = True
           for question_wrap_element in original_question_wraps:
               question_text_for_hash = self.driver_service._get_full_question_text_for_caching(question_wrap_element)
               # 使用 cache_service 内部的哈希方法来生成键
               question_hash = self.cache_service._generate_question_hash(question_text_for_hash)

               if question_hash in cached_questions:
                   answer_obj = cached_questions[question_hash]
                   temp_answers.append(answer_obj['answer'])
                   print(f"在缓存中找到答案: ... -> {answer_obj['answer']}")
               else:
                   all_found = False
                   print(f"题目 '{question_text_for_hash[:30]}...' 在页面缓存中未找到。")
                   break

           if all_found:
               all_questions_in_cache = True
               answers_to_fill = temp_answers

       # 2. 根据缓存情况决定下一步
       if all_questions_in_cache:
           print("所有题目均在缓存中找到答案，直接填写。")
       else:
           print("部分或全部题目在缓存中未找到，将调用AI进行解答...")
           cache_write_needed = True

           # --- AI后备逻辑 ---
           article_text = self._get_article_text()
           direction_text = self._get_direction_text()
           full_questions_and_options_text = "\n".join(
               [self._get_full_question_text_for_ai(qw) for qw in original_question_wraps])
           article_section = f"以下是文章内容:\n{article_text}\n\n" if article_text else ""

           prompt = (
               f"{prompts.SINGLE_CHOICE_PROMPT}\n"
               f"以下是题目的说明:\n{direction_text}\n\n"
               f"{article_section}"
               f"以下是题目和选项:\n{full_questions_and_options_text}"
           )

           print("按回车键继续以调用AI...")
           input()

           json_data = self.ai_service.get_chat_completion(prompt)
           if not json_data or "questions" not in json_data:
               print("未能从AI获取有效答案，终止执行。")
               return

           print(f"AI回答: {json_data}")
           answers_to_fill = [str(item["answer"]).upper() for item in json_data.get("questions", []) if
                              "answer" in item]

       # 3. 统一执行填写和提交流程
       self._fill_and_submit(answers_to_fill, cache_write_needed, breadcrumb_parts)

   def _get_article_text(self) -> str:
       """提取文章或听力原文（音频或视频）。"""
       media_url, media_type = self.driver_service.get_media_source_and_type()
       if media_url:
           print(f"发现 {media_type} 文件，准备转写: {media_url}")
           # 注意：此处假设ai_service有transcribe_audio_from_url方法
           # 您可能需要根据ai_service的实现来调整
           try:
                article_text = self.ai_service.transcribe_media_from_url(media_url)
                if not article_text:
                    print("警告：媒体文件转写失败。")
                return article_text
           except Exception as e:
                print(f"媒体文件转写时发生错误: {e}")
                return ""
       print("未在本页找到可用的音频或视频文件。")
       return ""

   def _get_direction_text(self) -> str:
       """提取题目说明文字。"""
       try:
           # 注意：QUESTION_LOADING_MARKER可能不是最准确的题目说明选择器
           return self.driver_service.get_element_text(By.CSS_SELECTOR, config.QUESTION_LOADING_MARKER)
       except Exception:
           print("未找到题目说明（Direction）。")
           return ""

   def _fill_and_submit(self, answers: list[str], cache_write_needed: bool, breadcrumb_parts: list[str]):
       """
       将答案填入网页并提交。在操作前执行严格的预验证。
       """
       try:
           print("正在解析并预验证答案...")
           option_wraps = self.driver_service.driver.find_elements(By.CSS_SELECTOR, config.QUESTION_OPTION_WRAP)

           if len(answers) != len(option_wraps):
               print(f"错误：收到的答案数量 ({len(answers)}) 与页面题目数量 ({len(option_wraps)}) 不匹配，为避免错位，已终止此题作答。")
               return

           is_valid = True
           for i, option_wrap in enumerate(option_wraps):
               answer_char = answers[i]
               answer_index = ord(answer_char) - ord("A")
               options = option_wrap.find_elements(By.CLASS_NAME, "option")
               if not (0 <= answer_index < len(options)):
                   print(f"错误：第 {i+1} 题的答案 '{answer_char}' 无效（选项范围是 A-{chr(ord('A')+len(options)-1)}），已终止此题作答。")
                   is_valid = False
                   break
           
           if not is_valid:
               return

           print("预验证通过，开始填写答案...")
           for i, option_wrap in enumerate(option_wraps):
               answer_char = answers[i]
               answer_index = ord(answer_char) - ord("A")
               options = option_wrap.find_elements(By.CLASS_NAME, "option")
               print(f"第 {i+1} 题，选择选项: {answer_char}")
               options[answer_index].click()
           
           print("答案填写完毕。")

           confirm = input("AI或缓存已选择答案。是否确认提交？[Y/n]: ").strip().upper()
           if confirm == "Y" or confirm == "":
               self.driver_service._click(By.CSS_SELECTOR, config.SUBMIT_BUTTON)
               print("答案已提交。正在处理最终确认弹窗...")
               self.driver_service.handle_submission_confirmation()

               if cache_write_needed:
                   print("准备从解析页面提取正确答案并写入缓存...")
                   self._write_answers_to_cache(breadcrumb_parts)
           else:
               print("用户取消提交。")

       except Exception as e:
           print(f"填写或提交答案时出错: {e}")

   def _write_answers_to_cache(self, breadcrumb_parts: list[str]):
       """
       导航到答案解析页面，提取正确答案，并作为一个整体写入缓存。
       """
       try:
           original_page_url = self.driver_service.driver.current_url
           self.driver_service._navigate_to_answer_analysis_page()
           extracted_analysis_answers = self.driver_service.extract_all_correct_answers_from_analysis_page()

           # 返回原页面以重新匹配题目和答案
           self.driver_service.driver.get(original_page_url)
           self.driver_service.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, config.QUESTION_WRAP)))
           print("已返回原始题目页面，开始匹配并准备写入缓存...")

           fresh_question_wraps = self.driver_service.driver.find_elements(By.CSS_SELECTOR, config.QUESTION_WRAP)

           if len(fresh_question_wraps) != len(extracted_analysis_answers):
               print(
                   f"警告：写入缓存失败，原始页面题目数量({len(fresh_question_wraps)})与解析页面答案数量({len(extracted_analysis_answers)})不匹配。")
               return

           # 准备要传递给缓存服务的数据列表
           answers_data_to_cache = []
           for i in range(len(fresh_question_wraps)):
               full_question_text = self.driver_service._get_full_question_text_for_caching(fresh_question_wraps[i])
               correct_answer = extracted_analysis_answers[i]['correct_answer']

               if not full_question_text:
                   print(f"警告：无法为第 {i + 1} 题生成缓存键，跳过写入。")
                   continue

               answers_data_to_cache.append({
                   'question_text': full_question_text,
                   'correct_answer': correct_answer
               })

           # 一次性保存整个页面的答案
           if answers_data_to_cache:
               self.cache_service.save_task_page_answers(
                   breadcrumb_parts,
                   self.strategy_type,
                   answers_data_to_cache
               )

       except Exception as e:
           print(f"写入缓存过程中发生错误: {e}")