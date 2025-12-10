# src/credentials_handler.py
import asyncio
import getpass
from src.utils import logger
import src.config as config

async def handle_credentials():
    """
    检查.env文件中的凭据。如果凭据是默认值或缺失，则提示用户输入、确认并使用.env.example作为模板保存。
    成功返回True，失败返回False。
    """
    env_file_path = ".env"
    default_values = {"你的U校园账号", "你的U校园密码", "你的DeepSeek API Key", None, ""}
    
    username_is_default = config.USERNAME in default_values
    password_is_default = config.PASSWORD in default_values
    api_key_is_default = config.DEEPSEEK_API_KEY in default_values

    if username_is_default or password_is_default or api_key_is_default:
        logger.always_print("="*50)
        logger.always_print("欢迎使用 Unipus AI Automator！")
        logger.always_print("首次运行或配置不完整，需要您提供以下信息完成初始化。")
        logger.always_print("="*50)

        while True: # 用户确认循环
            new_username = ""
            while not new_username:
                new_username = await asyncio.to_thread(input, "请输入您的U校园账号: ")
                if not new_username:
                    logger.warning("账号不能为空，请重新输入。")

            new_password = ""
            while not new_password:
                try:
                    new_password = await asyncio.to_thread(getpass.getpass, "请输入您的U校园密码 (输入时不可见): ")
                except Exception:
                    logger.warning("无法使用密文模式，密码将可见。")
                    new_password = await asyncio.to_thread(input, "请输入您的U校园密码: ")
                if not new_password:
                     logger.warning("密码不能为空，请重新输入。")

            new_api_key = ""
            while not new_api_key:
                new_api_key = await asyncio.to_thread(input, "请输入您的DeepSeek API Key (可从 https://platform.deepseek.com/api_keys 复制): ")
                if not new_api_key:
                    logger.warning("API Key不能为空，请重新输入。")
            
            # 确认步骤
            logger.always_print("\n" + "-"*50)
            logger.always_print("请确认您输入的信息：")
            logger.always_print(f"  - U校园账号: {new_username}")
            logger.always_print(f"  - DeepSeek API Key: {new_api_key}")
            logger.always_print("  - 密码已记录，但为安全起见不显示。")
            logger.always_print("-" * 50)
            
            confirm = ""
            while confirm.lower() not in ['y', 'n']:
                confirm = await asyncio.to_thread(input, "信息是否正确？(y/n): ")

            if confirm.lower() == 'y':
                try:
                    with open(".env.example", "r", encoding="utf-8") as f:
                        env_template = f.read()

                    # 基于模板替换占位符
                    env_content = env_template.replace('"你的U校园账号"', f'"{new_username}"')
                    env_content = env_content.replace('"你的U校园密码"', f'"{new_password}"')
                    env_content = env_content.replace('"你的DeepSeek API Key"', f'"{new_api_key}"')

                    with open(env_file_path, "w", encoding="utf-8") as f:
                        f.write(env_content)
                    
                    logger.success(f"配置已成功保存到 {env_file_path} 文件中！")
                    
                    # 动态更新当前会话的配置
                    config.USERNAME = new_username
                    config.PASSWORD = new_password
                    config.DEEPSEEK_API_KEY = new_api_key
                    logger.info("配置已在当前会话中生效，程序将继续运行。")
                    break # 成功，跳出确认循环

                except FileNotFoundError:
                    logger.error("致命错误：模板文件 .env.example 未找到！")
                    logger.error("请确保 .env.example 文件与主程序在同一目录下。")
                    return False
                except IOError as e:
                    logger.error(f"致命错误：无法写入 .env 文件: {e}")
                    logger.error("请检查程序是否具有当前目录的写入权限。")
                    return False
            else:
                logger.warning("\n好的，请重新输入您的信息。\n")

    return True
