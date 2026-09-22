from core.config import telegram_config
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, Application
import logging
import asyncio

tel_bots = {}
commands = [
    BotCommand(command="help", description="Show help message"),
]


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(commands)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await help(update, context)


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = f"Hello, {update.message.from_user.first_name}"
    await update.message.reply_text(help_text, disable_web_page_preview=True)


async def run(token):
    global tel_bots
    application = (
        ApplicationBuilder()
        .token(token)
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )

    # 用token作为key存储bot实例
    tel_bots[token] = application.bot

    # 基础命令
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help))

    # 从services加载其他命令
    from services.rss.commands import register_commands as register_rss_commands
    from services.wiki.commands import register_commands as register_wiki_commands

    register_rss_commands(application)
    register_wiki_commands(application)

    await application.initialize()
    await application.start()
    logging.info("Telegram bot startup successful")
    await application.updater.start_polling(drop_pending_updates=True)


async def init_task():
    logging.info("Initializing Telegram bot")


async def start_task(token):
    return await run(token)


def close_all():
    logging.info("Closing Telegram bot")


async def scheduled_task(token):
    """定时任务"""
    await asyncio.sleep(5)

    bot = tel_bots.get(token)
    if not bot:
        logging.error(f"未找到token对应的bot实例: {token}")
        return

    # 修改导入
    from services.rss.commands import (
        rss_manager,
        send_update_notification,
        send_keywords_summary,
    )

    while True:
        try:
            feeds = rss_manager.get_feeds()
            logging.info(f"定时任务开始检查订阅源更新，共 {len(feeds)} 个订阅")

            # 用于存储所有新增的URL
            all_new_urls = []
            for url in feeds:
                logging.info(f"正在检查订阅源: {url}")
                # add_feed 内部会调用 download_sitemap
                success, error_msg, dated_file, new_urls = rss_manager.add_feed(url)

                if success and dated_file.exists():
                    # 直接调用合并后的函数
                    await send_update_notification(bot, url, new_urls, dated_file)
                    if new_urls:
                        logging.info(
                            f"订阅源 {url} 更新成功，发现 {len(new_urls)} 个新URL，已发送通知。"
                        )
                    else:
                        logging.info(f"订阅源 {url} 更新成功，无新增URL，已发送通知。")
                elif "今天已经更新过此sitemap" in error_msg:
                    logging.info(f"订阅源 {url} {error_msg}")
                else:
                    logging.warning(f"订阅源 {url} 更新失败: {error_msg}")
                # 将新URL添加到汇总列表中
                all_new_urls.extend(new_urls)

            # 调用新封装的函数发送关键词汇总
            await asyncio.sleep(10)  # 等待10秒，确保所有消息都发送完成
            await send_keywords_summary(bot, all_new_urls)

            logging.info("所有订阅源检查完成，等待下一次检查")
            await asyncio.sleep(3600)  # 保持1小时检查间隔
        except Exception as e:
            logging.error(f"检查订阅源更新失败: {str(e)}", exc_info=True)
            await asyncio.sleep(60)  # 出错后等待1分钟再试


async def wiki_scheduled_task(token):
    """wiki(MediaWiki/Fandom)新增词条定时任务，间隔更短，因为wiki编辑频率远高于sitemap更新"""
    await asyncio.sleep(5)

    bot = tel_bots.get(token)
    if not bot:
        logging.error(f"未找到token对应的bot实例: {token}")
        return

    from services.wiki.commands import wiki_manager, send_wiki_update_notification

    while True:
        try:
            feeds = wiki_manager.get_feeds()
            logging.info(f"wiki定时任务开始检查更新，共 {len(feeds)} 个订阅")

            for base_url in feeds:
                success, error_msg, new_pages = wiki_manager.check_new_pages(base_url)
                if success:
                    if new_pages:
                        await send_wiki_update_notification(bot, base_url, new_pages)
                        logging.info(f"wiki {base_url} 发现 {len(new_pages)} 个新增词条，已发送通知。")
                    else:
                        logging.info(f"wiki {base_url} 无新增词条。")
                else:
                    logging.warning(f"wiki {base_url} 检查失败: {error_msg}")

            logging.info("所有wiki订阅检查完成，等待下一次检查")
            await asyncio.sleep(900)  # 15分钟检查间隔
        except Exception as e:
            logging.error(f"检查wiki订阅更新失败: {str(e)}", exc_info=True)
            await asyncio.sleep(60)  # 出错后等待1分钟再试
