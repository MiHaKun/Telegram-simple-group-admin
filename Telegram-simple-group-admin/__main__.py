from . import logger, config
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    PicklePersistence,
    ChatJoinRequestHandler,
)
from telegram.helpers import create_deep_linked_url, mention_html
import telegram
import random
from string import ascii_letters as letters
import os


# 延时ban掉用户的回调。
# 如果到时候用户没解封，就踢了。
async def _ban_user_cb(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id, _ = job.data.split("-")
    user_id = int(user_id)
    chat_member = await context.bot.get_chat_member(job.chat_id, user_id)
    if chat_member.status == "kicked" or chat_member.status == "restricted":
        await context.bot.ban_chat_member(job.chat_id, user_id, 0)


# 延时ban掉用户
async def ban_user_later(
    delay: float, chat_id, user_id: int, context: ContextTypes.DEFAULT_TYPE
):
    name = f"banjob_{chat_id}_{user_id}"
    context.job_queue.run_once(
        _ban_user_cb, delay, chat_id=chat_id, name=name, data=f"{user_id}-0"
    )
    return name


# 延时删除消息的回调
async def _delete_message_cb(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    msg_id = job.data
    await context.bot.delete_message(job.chat_id, msg_id)


# 延时删除用户
async def delete_message_later(
    delay: float, chat_id, msg_id: int, context: ContextTypes.DEFAULT_TYPE
):
    name = f"deljob_{chat_id}_{msg_id}"
    context.job_queue.run_once(
        _delete_message_cb, delay, chat_id=chat_id, name=name, data=msg_id
    )
    return name


# 删除任务
def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


# 一般的私聊start指令
# 如果有必要，可以加入管理员的一些特殊菜单。好比重新加载配置之类的。
# 目前没做重新加载，因为貌似这个没必要进行热插拔。
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # check whether is admin
    if user.id in config["admin_ids"]:
        logger.info(f"{user.first_name}({user.id}) is admin")
        try:
            bg = await context.bot.get_chat(config["group_id"])
            if bg.type == "supergroup" or bg.type == "group":
                logger.info(f"admin group is {bg.title}")
        except Exception as e:
            logger.error(f"admin group error {e}")
            await update.message.reply_html(
                f"⚠️⚠️后台管理群组设置错误，请检查配置。⚠️⚠️\n你需要确保已经将机器人 @{context.bot.username} 邀请入管理群组并且给与了管理员权限。\n错误细节：{e}\n请联系 @MrMiHa 获取技术支持。"
            )

        await update.message.reply_html(
            f"你好管理员 {user.first_name}({user.id})\n\n欢迎使用 {config['app_name']} 机器人。\n\n 目前你的配置完全正确。可以在群组 <b> {bg.title} </b> 中使用机器人。"
        )
    else:
        logger.info(f"{user.first_name}({user.id}) is not admin")
        await update.message.reply_html(
            f"本群机器人并不支持普通用户使用。\n\n请联系管理员 @{config['contact_username']} 获取帮助。"
        )


# 利用deeplink区分不同的跳转来源。
# 这个函数响了，代表是用户过来通过验证。
# 用户私聊机器人，走的上面的 start 函数。
async def start_with_deep_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"User {update.effective_user.id} start with deep link. {update.message.text}"
    )
    user = update.effective_user
    prefix, user_id, chat_id = update.message.text.split("_")
    if (
        prefix != "/start joingroup"
        or user_id != str(user.id)
        or chat_id != str(config["group_id"])
    ):
        await update.message.reply_html("无效群跳入。")
        return
    chat_member = await context.bot.get_chat_member(chat_id, user.id)
    if chat_member.status == "kicked":
        await update.message.reply_html("你已经被禁止加入群组。")
        return
    await context.bot.delete_message(chat_id, context.user_data.get("srcjoin"))
    context.user_data["current_join_group"] = chat_id
    # 私信用户, 发送图片。
    file_name = random.choice(os.listdir("./assets/imgs"))
    code = file_name.replace("image_", "").replace(".png", "")
    file = f"./assets/imgs/{file_name}"
    codes = ["".join(random.sample(letters, 5)) for _ in range(0, 7)]
    codes.append(code)
    random.shuffle(codes)

    photo = context.bot_data.get(f"image|{code}")
    if not photo:
        # 没发送过，就用内置图片。反之，利用发送过的file_id
        photo = file
    buttons = [
        InlineKeyboardButton(x, callback_data=f"vcode_{x}_{user.id}") for x in codes
    ]
    button_matrix = [buttons[i : i + 4] for i in range(0, len(buttons), 4)]
    sent = await context.bot.send_photo(
        user.id,
        photo,
        f"{mention_html(user.id, user.first_name)}请选择图片中的文字。回答错误将入群。",
        reply_markup=InlineKeyboardMarkup(button_matrix),
        parse_mode="HTML",
    )
    # 存下已经发送过的图片的file_id，省掉上传速度
    biggest_photo = sorted(sent.photo, key=lambda x: x.file_size, reverse=True)[0]
    context.bot_data[f"image|{code}"] = biggest_photo.file_id
    context.user_data["vcode"] = code
    await delete_message_later(
        config["ban_after"], sent.chat.id, sent.message_id, context
    )


# 删除service消息。
async def status_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if config["delete_service_message"]:
        await update.message.delete()


# 加入群组的处理函数
async def join_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_join_request:
        return
    logger.info(
        f"New user {update.chat_join_request.from_user.id} request to join group {update.effective_chat.id}"
    )
    chat = update.effective_chat
    user = update.chat_join_request.from_user
    # 无条件审批通过这个用户
    await update.chat_join_request.approve()
    # 限制用户
    limitation = telegram.ChatPermissions()
    limitation.no_permissions()
    await context.bot.restrict_chat_member(chat.id, user.id, limitation, 0)
    # 群内提醒用户
    button = InlineKeyboardButton(
        "点击加入",
        url=create_deep_linked_url(
            context.bot.username, f"joingroup_{user.id}_{chat.id}"
        ),
    )
    sent = await context.bot.send_message(
        chat.id,
        config["msg_new_user_joined_group"].format(
            mention_html(user.id, user.full_name)
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[button]]),
    )
    context.user_data[f"srcjoin"] = sent.id
    # 启动延时任务
    await delete_message_later(config["ban_after"], chat.id, sent.message_id, context)
    await ban_user_later(config["ban_after"], chat.id, user.id, context)

    # 用户状态初始化下
    context.user_data["current_join_group"] = None


async def callback_query_vcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 验证码的点击事件处理
    query = update.callback_query
    user = query.from_user
    code = query.data.split("_")[1]
    user_id = query.data.split("_")[2]
    if user_id == str(user.id):
        # 是正确的人点击
        logger.info(
            f"User {user.id} clicked {code}, the right code is {context.user_data.get('vcode')}"
        )
        if code == context.user_data.get("vcode"):
            # 点击合法
            logger.info(f"User {user.id} clicked the right code.")
            await query.answer(f"正确，欢迎。")
            sent = await context.bot.send_message(user.id, f"输入正确，欢迎入群。")
            await delete_message_later(
                config["ban_after"], sent.chat.id, sent.message_id, context
            )
            chat = await context.bot.get_chat(context.user_data["current_join_group"])
            await context.bot.restrict_chat_member(
                chat.id, user.id, chat.permissions, 0
            )
            remove_job_if_exists(f"banjob_{chat.id}_{user.id}", context)
        else:
            # 点击错误
            logger.info(f"User {user.id} clicked the wrong code.")
            await query.answer(f"~错误~，等20分钟后入群。")
            await context.bot.send_message(
                user.id, f"你的验证码错误，等待20分钟后再次尝试入群。"
            )
            await context.bot.ban_chat_member(config["group_id"], user.id, 1200)
    await query.message.delete()


# 全局异常
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logger.error(f"Exception while handling an update: {context.error} ")
    logger.debug(f"Exception detail is :", exc_info=context.error)


if __name__ == "__main__":
    pickle_persistence = PicklePersistence(
        filepath=f"./assets/{config['app_name']}.pickle"
    )
    application = (
        ApplicationBuilder()
        .token(config["bot_token"])
        .persistence(persistence=pickle_persistence)
        .build()
    )
    # Handler 的添加顺序是不能更改的。要改变，你需要理解 Handler的执行顺序以及优先级。
    application.add_handler(MessageHandler(filters.StatusUpdate.ALL, status_update))
    application.add_handler(
        CommandHandler("start", start_with_deep_link, filters.Regex(r"joingroup"))
    )
    application.add_handler(
        CommandHandler(
            "start", start, filters.ChatType.PRIVATE & ~filters.Regex(r"joingroup")
        )
    )
    application.add_handler(ChatJoinRequestHandler(join_group))
    application.add_handler(
        CallbackQueryHandler(callback_query_vcode, pattern="^vcode_")
    )
    application.add_error_handler(error_handler)

    application.run_polling()
