import datetime
import logging
import os

import pytz
import yaml
import utils
from logging import handlers

import telegram.error
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    PicklePersistence,
    MessageHandler,
    filters,
    Defaults, TypeHandler
)

import job_queue
import settings
from config_values import ConversationState
from modules.utils import check_dict_keys, initialize_chat_data
from utils import *
from decorators import send_action

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

bot_logger = logging.getLogger("bot_logger")
bot_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = handlers.RotatingFileHandler(filename="logs/main.log",
                                            maxBytes=1024, backupCount=1)
file_handler.setFormatter(formatter)
bot_logger.addHandler(file_handler)

load_dotenv()


# noinspection GrazieInspection
async def set_data(appl: Application) -> None:
    """
    {
        "settings": {
            "first_boot": True / False,
            "permissions": ...
            "texts": {
                "overall_functioning": {
                    "admin": "...",
                    "allowed_users": "..""
                },
                "text#2": {
                    "admin": "...",
                    "allowed_users": "..."
                }
            }
        },
        "users": {
            "owner": OWNER_ID,
            "admin": MASTER_ID,
            "allowed": {
                user_id: {
                    "permissions": {
                        "can_menage_backups": True / False,
                        ...
                    }
                }
            }
        }
    }
    """

    if not os.path.isfile("config/constants.yml"):
        raise Exception(
            "Missing file 'config/constants.yml' - Create inside 'check_app_update_v2/config/constants.yml'")

    # controllo chiavi
    if "settings" not in (bd := appl.bot_data):
        bd["settings"] = {
            "first_boot": True,
            "permissions": []
        }

    with open("config/constants.yml", "r", encoding='utf-8') as f:
        bd["settings"]["permissions"] = (data := yaml.safe_load(f))["permissions"]
        bd["settings"]["texts"] = data["texts"]

    if "users" not in bd:
        bd["users"] = {
            "owner": int(os.getenv("OWNER_ID")),
            "admin": int(os.getenv("MASTER_ID")),
            "allowed": {}
        }

    with open("config/allowed_ids.yml", "r") as f:
        bd["users"]["allowed"] = yaml.safe_load(f)["allowed_users"]

    # class of app.chat_data: mappingproxy(defaultdict(<class 'dict'>, {}))
    # noinspection PyUnresolvedReferences
    for cd in appl.chat_data:
        # noinspection PyUnresolvedReferences
        await job_queue.reschedule(appl, appl.chat_data[cd])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not await is_allowed_user(user_id=user_id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=chat_id, text="❌ You are not allowed to use this bot.")
        return

    if update.callback_query is not None:
        if len(li := update.callback_query.data.split(" ")) > 1:
            try:
                await context.bot.delete_message(chat_id=chat_id,
                                                 message_id=int(li[1]))
            except telegram.error.BadRequest:
                pass

    if not (cd := context.chat_data):
        return await initialize_chat_data(update, context)

    await check_dict_keys(cd, ["user_type", "permissions", "first_boot"])
    await check_dict_keys(cd["permissions"], context.bot_data["settings"]["permissions"])

    if cd["first_boot"]:
        await context.bot.send_chat_action(action=ChatAction.TYPING, chat_id=chat_id)
        keyboard = [
            [InlineKeyboardButton(text="💡 Informazioni Generali", callback_data="print_tutorial {}")],
            [InlineKeyboardButton(text="⏭ Procedi – Settaggio Valori Default", callback_data="set_defaults {}")],
        ]

        context.job_queue.run_once(callback=job_queue.scheduled_send_message,
                                   data={
                                       "chat_id": chat_id,
                                       "text": "Prima di cominciare ad usare questo bot, vuoi un breve riepilogo sul"
                                               " suo funzionamento generale?\n\n@AleLntr dice che è consigliabile 😊",
                                       "keyboard": keyboard,
                                       "web_preview": False,
                                       "close_button": [[1, 1], [2, 1]]
                                   },
                                   when=1)
        return 0

    await send_menu(update, context)
    return ConversationHandler.END


@send_action(ChatAction.TYPING)
async def tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data.startswith("print_tutorial"):
        if context.chat_data["user_type"] == "admin" or context.chat_data["user_type"] == "owner":
            text = context.bot_data["settings"]["texts"]["overall_functioning"]["admin"]
        else:
            text = context.bot_data["settings"]["texts"]["overall_functioning"]["allowed_users"]

        keyboard = [
            [InlineKeyboardButton(text="⏭ Procedi – Settaggio Valori Default", callback_data="set_defaults {}")]
        ]

        context.job_queue.run_once(callback=job_queue.scheduled_send_message,
                                   data={
                                       "chat_id": update.effective_chat.id,
                                       "message_id": update.callback_query.data.split(" ")[1],
                                       "text": text,
                                       "keyboard": keyboard,
                                       "close_button": [1, 1]
                                   },
                                   when=1.5)
    return 1


async def send_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query is not None:
        if len(li := update.callback_query.data.split(" ")) > 1:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id,
                                                 message_id=int(li[1]))
            except telegram.error.BadRequest:
                pass

    keyboard = [
        [
            InlineKeyboardButton(text="⚙ Settings", callback_data="settings"),
            InlineKeyboardButton(text="📄 List Last Checks", callback_data="last_checks")
        ]
    ]

    text = (f"🔹 Ciao padrone {update.effective_user.first_name}!\n\n"
            f"Sono il bot che controlla gli aggiornamenti delle applicazioni sul Play Store.\n\n"
            f"Scegli un'opzione ⬇")
    if update.callback_query and update.callback_query.data == "back_to_main_menu":
        keyboard.append([InlineKeyboardButton(text="🔐 Close Menu",
                                              callback_data="delete_message {}".format(update.effective_message.id))])
        await settings.parse_conversation_message(context=context,
                                                  data={
                                                      "chat_id": update.effective_chat.id,
                                                      "text": text,
                                                      "reply_markup": InlineKeyboardMarkup(keyboard),
                                                      "message_id": update.effective_message.message_id
                                                  })
    else:
        keyboard.append([InlineKeyboardButton(text="🔐 Close Menu", callback_data="delete_message {}")])
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        context.job_queue.run_once(callback=job_queue.scheduled_send_message,
                                   data={
                                       "chat_id": update.effective_chat.id,
                                       "text": text,
                                       "keyboard": keyboard,
                                       "close_button": [2, 1]
                                   },
                                   when=1)

    return ConversationState.CHANGE_SETTINGS


async def explore_handlers(matches: list, handler_s, update, level=0):
    indent = ' ' * (level * 4)  # Create indentation for better readability
    for handler in handler_s:
        if isinstance(handler, ConversationHandler):
            print(f"{indent}Exploring ConversationHandler at level {level}")
            # Explore entry points
            for entry_point in handler.entry_points:
                if hasattr(entry_point, "pattern"):
                    print(f"{indent}Entry point pattern: {entry_point.pattern}")
                if entry_point.check_update(update):
                    print(f"{indent}Match found in entry point at level {level}")
                    matches.append(handler)

            # Recursively explore states
            for state in handler.states:
                print(f"{indent}Exploring state: {state}")
                await explore_handlers(matches, handler.states[state], update, level + 1)

            # Explore fallbacks
            for fallback in handler.fallbacks:
                if hasattr(fallback, "pattern"):
                    print(f"{indent}Fallback pattern: {fallback.pattern}")
                if fallback.check_update(update):
                    print(f"{indent}Match found in fallback at level {level}")
                    matches.append(handler)

        else:
            if hasattr(handler, "pattern"):
                print(f"{indent}Handler pattern: {handler.pattern}")
            if handler.check_update(update):
                print(f"{indent}Match found at level {level}")
                matches.append(handler)

    return matches


async def catch_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    matched_handlers = []
    if update.callback_query and ("back_to_settings" in update.callback_query.data):
        print(update.callback_query.data)
        for handler_group in context.application.handlers.values():
            matched_handlers = await explore_handlers(matched_handlers, handler_group, update)
        if matched_handlers:
            print(f"Matched handlers: {matched_handlers}")
        else:
            print("No matching handler found")
        print("=====================================================")


def main():
    persistence = PicklePersistence(filepath="config/persistence")
    appl = (ApplicationBuilder().token(os.getenv("BOT_TOKEN")).persistence(persistence).
            defaults(Defaults(tzinfo=pytz.timezone('Europe/Rome'))).
            post_init(set_data).build())

    conv_handler1 = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(pattern="edit_default_settings", callback=settings.set_defaults)
        ],
        states={
            0: [
                CallbackQueryHandler(pattern="^print_tutorial.+$", callback=tutorial),
                CallbackQueryHandler(pattern="^set_defaults.+$", callback=settings.set_defaults),
                CallbackQueryHandler(pattern="^confirm_edit_default_settings.+$", callback=settings.set_defaults)
            ],
            1: [
                CallbackQueryHandler(pattern="^set_defaults.+$", callback=settings.set_defaults)
            ],
            2: [
                MessageHandler(filters=filters.TEXT, callback=settings.set_defaults),
                CallbackQueryHandler(pattern="^interval_incorrect.+$", callback=settings.set_defaults),
                CallbackQueryHandler(pattern="^interval_correct.+$", callback=settings.set_defaults)
            ],
            3: [
                CallbackQueryHandler(pattern="^default_send_on_check_true.+$", callback=settings.set_defaults),
                CallbackQueryHandler(pattern="^default_send_on_check_false.+$", callback=settings.set_defaults)
            ]
        },
        fallbacks=[CallbackQueryHandler(pattern="cancel_edit_settings", callback=settings.change_settings)],
        name="default_settings_conv_handler"
    )

    set_app_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(pattern="app_name_from_link_correct", callback=settings.set_app),
            CallbackQueryHandler(pattern="confirm_app_to_edit", callback=settings.set_app),
            CallbackQueryHandler(pattern="^edit_app_from_check.+$", callback=settings.set_app),
            CallbackQueryHandler(pattern="^edit_app_from_add.+$", callback=settings.set_app)
        ],
        states={
            ConversationState.SET_INTERVAL: [
                MessageHandler(filters=filters.TEXT, callback=settings.set_app),
                CallbackQueryHandler(pattern="^set_default_values$", callback=settings.set_app),
                CallbackQueryHandler(pattern="^edit_set_default_values$", callback=settings.set_app)
            ],
            ConversationState.CONFIRM_INTERVAL: [
                CallbackQueryHandler(pattern="interval_correct", callback=settings.set_app),
                CallbackQueryHandler(pattern="interval_incorrect", callback=settings.set_app)
            ],
            ConversationState.SEND_ON_CHECK: [
                CallbackQueryHandler(pattern="^send_on_check.+$", callback=settings.set_app)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(pattern="^back_to_settings$", callback=settings.send_menage_apps_menu),
            CallbackQueryHandler(pattern="^delete_message.+$", callback=settings.delete_extemporary_message)
        ],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        }
    )

    add_app_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(pattern="add_app", callback=settings.add_app)
        ],
        states={
            ConversationState.SEND_LINK: [
                MessageHandler(filters=filters.TEXT, callback=settings.add_app)
            ],
            ConversationState.CONFIRM_APP_NAME: [
                # set_app_conv_handler,
                CallbackQueryHandler(pattern="app_name_from_link_not_correct", callback=settings.add_app)
            ],
            ConversationState.ADD_OR_EDIT_FINISH: []
        },
        fallbacks=[
            CallbackQueryHandler(pattern="^back_to_settings$", callback=settings.send_menage_apps_menu)
        ],
        allow_reentry=True  # per consentire di aggiungere un'altra app
    )

    edit_app_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(pattern="^edit_app$", callback=settings.edit_app)
        ],
        states={
            ConversationState.EDIT_SELECT_APP: [
                MessageHandler(filters.TEXT, callback=settings.edit_app)
            ],
            ConversationState.EDIT_CONFIRM_APP: [
                # set_app_conv_handler
            ],
            ConversationState.ADD_OR_EDIT_FINISH: []
        },
        fallbacks=[
            CallbackQueryHandler(pattern="^back_to_settings$", callback=settings.send_menage_apps_menu)
        ],
        allow_reentry=True  # per consentire di modificare un'altra app
    )

    delete_app_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(pattern="delete_app", callback=settings.remove_app)
        ],
        states={
            ConversationState.DELETE_APP_SELECT: [
                MessageHandler(filters.TEXT, callback=settings.remove_app)
            ],
            ConversationState.DELETE_APP_CONFIRM: [
                CallbackQueryHandler(pattern="confirm_remove", callback=settings.remove_app),
                CallbackQueryHandler(pattern="cancel_remove", callback=settings.remove_app),
                CallbackQueryHandler(pattern="^suspend_from_remove.+$", callback=settings.suspend_app)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(pattern="^back_to_settings$", callback=settings.send_menage_apps_menu)
        ],
        allow_reentry=True,  # per consentire di rimuovere un'altra app o riselezionare l'app
    )

    conv_handler2 = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(pattern="settings", callback=settings.change_settings),
            CallbackQueryHandler(pattern="^default_setting_finished.+$", callback=send_menu),
            CallbackQueryHandler(pattern="^first_configuration_completed.+$", callback=send_menu),
            CallbackQueryHandler(pattern="last_checks", callback=settings.list_last_checks)
        ],
        states={
            ConversationState.CHANGE_SETTINGS: [
                CallbackQueryHandler(pattern="menage_apps", callback=settings.menage_apps),
                conv_handler1
            ],
            ConversationState.MANAGE_APPS: [
                add_app_conv_handler,
                edit_app_conv_handler,
                delete_app_conv_handler,
                CallbackQueryHandler(pattern="list_apps", callback=settings.list_apps),
                CallbackQueryHandler(pattern="unsuspend_app", callback=settings.suspend_app),
                CallbackQueryHandler(pattern="^back_to_main_settings$", callback=settings.menage_apps),
                CallbackQueryHandler(pattern="settings", callback=settings.change_settings),
                CallbackQueryHandler(pattern="back_to_settings_settled", callback=settings.send_menage_apps_menu)
            ],
            ConversationState.LIST_APPS: [
                CallbackQueryHandler(pattern="back_from_list", callback=settings.menage_apps)
            ],
            ConversationState.UNSUSPEND_APP: [
                CallbackQueryHandler(pattern="^unsuspend_app.+$", callback=settings.suspend_app),
                CallbackQueryHandler(pattern="^back_to_main_settings.+$", callback=settings.menage_apps)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(pattern="^back_to_main_menu$", callback=send_menu),
            CallbackQueryHandler(pattern="^back_to_settings$", callback=settings.menage_apps),
            CallbackQueryHandler(pattern="^back_to_settings_no_apps$", callback=settings.send_menage_apps_menu),
            CallbackQueryHandler(pattern="^back_to_settings_settled$", callback=settings.send_menage_apps_menu)
        ],
        allow_reentry=True
    )

    # app.add_handler(TypeHandler(Update, callback=catch_update), group=-1)

    appl.add_handler(conv_handler1)
    appl.add_handler(conv_handler2)

    appl.add_handler(
        CallbackQueryHandler(pattern="^load_first_boot_configuration_.+$", callback=utils.first_boot_configuration))

    appl.add_handler(CallbackQueryHandler(pattern="^suspend_app.+$", callback=settings.suspend_app))
    appl.add_handler(CallbackQueryHandler(pattern="^delete_message.+$",
                                          callback=settings.delete_extemporary_message))
    appl.add_handler(CallbackQueryHandler(pattern="^edit_from_job.+$", callback=settings.see_app_settings))
    appl.add_handler(set_app_conv_handler)

    appl.run_polling()


if __name__ == '__main__':
    load_dotenv()
    main()
