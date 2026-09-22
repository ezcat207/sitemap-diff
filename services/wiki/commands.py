import logging
import asyncio
from urllib.parse import urlparse
from .manager import WikiManager
from core.config import telegram_config
from telegram import Update, Bot
from telegram.ext import ContextTypes, CommandHandler, Application

wiki_manager = WikiManager()


async def send_wiki_update_notification(
    bot: Bot,
    base_url: str,
    new_pages: list[dict],
    target_chat: str = None,
) -> None:
    """发送wiki新增词条通知"""
    chat_id = target_chat or telegram_config["target_chat"]
    if not chat_id:
        logging.error("未配置发送目标，请检查TELEGRAM_TARGET_CHAT环境变量")
        return

    if not new_pages:
        return

    domain = urlparse(base_url).netloc
    header_message = (
        f"🆕 {domain} 🆕\n"
        f"------------------------------------\n"
        f"发现新增词条！(共 {len(new_pages)} 条)\n"
        f"来源: {base_url}\n"
    )
    try:
        await bot.send_message(chat_id=chat_id, text=header_message, disable_web_page_preview=True)
        await asyncio.sleep(1)
        for page in new_pages:
            await bot.send_message(
                chat_id=chat_id, text=f"{page['title']}\n{page['url']}", disable_web_page_preview=False
            )
            await asyncio.sleep(1)
        end_message = f"🆕 {domain} 更新推送完成 🆕\n------------------------------------"
        await bot.send_message(chat_id=chat_id, text=end_message, disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"发送wiki更新消息失败 for {base_url}: {str(e)}", exc_info=True)


async def wiki_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /wiki 命令，用于监控 Fandom/MediaWiki 类站点的新增词条 (走 api.php，不受 sitemap 的 Cloudflare 拦截影响)"""
    user = update.message.from_user
    logging.info(f"收到wiki命令 - 用户: {user.username}(ID:{user.id})")

    if not context.args:
        await update.message.reply_text(
            "请使用以下命令：\n"
            "/wiki list - 显示所有监控的wiki站点\n"
            "/wiki add BASE_URL - 添加wiki监控（如 https://genshin-impact.fandom.com）\n"
            "/wiki del BASE_URL - 删除wiki监控"
        )
        return

    cmd = context.args[0].lower()
    if cmd == "list":
        feeds = wiki_manager.get_feeds()
        if not feeds:
            await update.message.reply_text("当前没有wiki订阅")
            return
        feed_list = "\n".join([f"- {feed}" for feed in feeds])
        await update.message.reply_text(f"当前wiki订阅列表：\n{feed_list}")

    elif cmd == "add":
        if len(context.args) < 2:
            await update.message.reply_text(
                "请提供wiki站点根地址\n例如：/wiki add https://genshin-impact.fandom.com"
            )
            return
        base_url = context.args[1]
        success, error_msg, new_pages = wiki_manager.add_feed(base_url)
        if success:
            if error_msg == "已存在的wiki更新成功":
                await update.message.reply_text("该wiki已在监控列表中")
            else:
                await update.message.reply_text(f"成功添加wiki监控：{base_url}\n(已建立基线，后续检查将推送新增词条)")
            await send_wiki_update_notification(context.bot, base_url, new_pages)
        else:
            await update.message.reply_text(f"添加wiki监控失败：{base_url}\n原因：{error_msg}")

    elif cmd == "del":
        if len(context.args) < 2:
            await update.message.reply_text("请提供要删除的wiki站点地址\n例如：/wiki del https://genshin-impact.fandom.com")
            return
        base_url = context.args[1]
        success, error_msg = wiki_manager.remove_feed(base_url)
        if success:
            await update.message.reply_text(f"成功删除wiki订阅：{base_url}")
        else:
            await update.message.reply_text(f"删除wiki订阅失败：{base_url}\n原因：{error_msg}")


def register_commands(application: Application):
    application.add_handler(CommandHandler("wiki", wiki_command))


def collect_keywords(new_pages: list[dict]) -> list[str]:
    """从新增词条列表中提取标题作为关键词，供 /news 汇总复用"""
    return [p["title"] for p in new_pages if p.get("title")]
