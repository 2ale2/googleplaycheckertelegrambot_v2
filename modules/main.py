import os
from logging import handlers

import pytz
import telegram.error
from dotenv import load_dotenv
from telegram.ext import (
    ApplicationBuilder,
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PicklePersistence,
    MessageHandler,
    filters,
    Defaults,
    TypeHandler
)

import settings
import utils
from decorators import send_action
from modules.settings import set_user_permissions, manage_users_and_permissions
from utils import *

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

bot_logger = logging.getLogger("bot_logger")
bot_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = handlers.RotatingFileHandler(filename="logs/main.log",
                                            maxBytes=1024*1024*10, backupCount=1)
file_handler.setFormatter(formatter)
bot_logger.addHandler(file_handler)

load_dotenv()


# noinspection GrazieInspection
async def set_bot_data(appl: Application) -> None:
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
            "permissions": {}
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
        await job_queue.reschedule(appl, appl.chat_data[cd], False)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not await is_allowed_user(user_id=user_id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=chat_id, text="❌ Non sei abilitato all'uso di questo bot.")
        return

    if update.callback_query is not None:
        if len(li := update.callback_query.data.split(" ")) > 1:
            try:
                await context.bot.delete_message(chat_id=chat_id,
                                                 message_id=int(li[1]))
            except telegram.error.BadRequest:
                pass

    if update.callback_query and update.callback_query.data.startswith("linxay_chicken"):
        text = ("🚧 <b>First Boot</b>\n\n"
                "ℹ️ <code>Configuration file ignored</code>\n\n🔸 Prima di cominciare ad usare questo bot, "
                "vuoi un breve riepilogo sul suo funzionamento generale?\n\n"
                "@AleLntr dice che è consigliabile 😊")
        keyboard = [
            [InlineKeyboardButton(text="💡 Informazioni Generali", callback_data="print_tutorial {}")],
            [InlineKeyboardButton(text="⏭ Procedi – Settaggio Valori Default",
                                  callback_data="set_defaults {}")],
        ]
        await send_message_with_typing_action(data={
            "chat_id": chat_id,
            "text": text,
            "keyboard": keyboard,
            "web_preview": False,
            "close_button": [[1, 1], [2, 1]]
        }, context=context)
        return 0

    if (cd := context.chat_data) and "first_boot" in cd and cd["first_boot"]:
        cd = {}

    if not cd:
        check = await initialize_chat_data(update, context)
        await send_message_with_typing_action(data=check.get_message_data(), context=context)
        if check.get_code() == FOUND_AND_VALID or check.get_code() == NOT_FOUND:
            return 0
        if check.get_code() == FOUND_AND_INVALID:
            return ConversationHandler.END

    await check_dict_keys(cd, ["user_type", "permissions", "first_boot"])
    await check_dict_keys(cd["permissions"], context.bot_data["settings"]["permissions"])

    await send_menu(update, context)
    return ConversationHandler.END


@send_action(ChatAction.TYPING)
async def tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return
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
    if update.effective_message and update.effective_message.text == "1":
        print("here's a valid update. it should be handled by the following handler...")
        if MessageHandler(filters=filters.TEXT, callback=settings.backup_and_restore).check_update(update):
            print("...and it actually is!\n\n" + update.to_json() + "\n\n")
        else:
            print("...but it's not.")


def main():
    if os.path.exists("config/persistence"):
        os.remove("config/persistence")
        print("\n\ni  Persistence file removed\n\n")

    persistence = PicklePersistence(filepath="config/persistence")
    appl = (ApplicationBuilder().token(os.getenv("BOT_TOKEN")).persistence(persistence).
            defaults(Defaults(tzinfo=pytz.timezone('Europe/Rome'))).
            post_init(set_bot_data).arbitrary_callback_data(True).build())

    conv_handler1 = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(pattern="^linxay_chicken.+$", callback=start),
            CallbackQueryHandler(pattern="edit_default_settings", callback=settings.set_defaults)
        ],
        states={
            0: [
                CallbackQueryHandler(pattern="^print_tutorial.+$", callback=tutorial),
                CallbackQueryHandler(pattern="^set_defaults.+$", callback=settings.set_defaults),
                CallbackQueryHandler(pattern="^confirm_edit_default_settings.+$", callback=settings.set_defaults),
                CallbackQueryHandler(pattern="^load_first_boot_configuration_.+$",
                                     callback=utils.load_first_boot_configuration)
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
            ],
            4: [
                CallbackQueryHandler(pattern="^set_default_permission.+$", callback=settings.set_defaults),
                CallbackQueryHandler(pattern="^default_settings_completed$", callback=settings.set_defaults)
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

    backup_restore_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(pattern="backup_restore", callback=settings.backup_and_restore)],
        states={
            ConversationState.BACKUP_MENU: [
                CallbackQueryHandler(pattern="^create_backup$", callback=settings.backup_and_restore),
                CallbackQueryHandler(pattern="^change_max_backups$", callback=settings.backup_and_restore),
                MessageHandler(filters=filters.TEXT, callback=settings.backup_and_restore)
            ],
            ConversationState.BACKUP_COMPLETED: [
                CallbackQueryHandler(pattern="^download_backup_file.+$", callback=settings.backup_and_restore),
            ],
            ConversationState.BACKUP_SELECTED: [
                CallbackQueryHandler(pattern="^download_backup_file.+$", callback=settings.backup_and_restore),
                CallbackQueryHandler(pattern="^delete_backup.+$", callback=settings.backup_and_restore),
                CallbackQueryHandler(pattern="^restore_backup.+$", callback=settings.backup_and_restore)
            ],
            ConversationState.BACKUP_DELETE: [
                CallbackQueryHandler(pattern="^confirm_delete_backup.+$", callback=settings.backup_and_restore)
            ],
            ConversationState.BACKUP_RESTORE: [
                CallbackQueryHandler(pattern="^confirm_restore_backup.+$", callback=settings.backup_and_restore)
            ],
            ConversationState.EDIT_MAX_BACKUPS: [
                MessageHandler(filters=filters.TEXT, callback=settings.backup_and_restore)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(pattern="from_backup_restore", callback=settings.change_settings)
        ],
        allow_reentry=True
    )

    user_managing_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(pattern="^user_managing$", callback=settings.manage_users_and_permissions)
        ],
        states={
            ConversationState.USERS_MANAGING_MENU: [
                CallbackQueryHandler(pattern="^add_allowed_user$", callback=settings.manage_users_and_permissions),
                CallbackQueryHandler(pattern="^remove_allowed_user$", callback=settings.manage_users_and_permissions),
                CallbackQueryHandler(pattern="^edit_user_permissions$", callback=settings.manage_users_and_permissions),
                CallbackQueryHandler(pattern="^edit_default_permissions$",
                                     callback=settings.manage_users_and_permissions),
                CallbackQueryHandler(pattern="^list_users_permissions$",
                                     callback=settings.manage_users_and_permissions)
            ],
            ConversationState.ADD_USER: [
                MessageHandler(filters=filters.TEXT, callback=settings.manage_users_and_permissions)
            ],
            ConversationState.CONFIRM_USER: [
                CallbackQueryHandler(pattern="^confirm_user.+$", callback=settings.manage_users_and_permissions),
                CallbackQueryHandler(pattern="^add_allowed_user$", callback=settings.manage_users_and_permissions)
            ],
            ConversationState.ADD_USER_LABEL: [
                MessageHandler(filters=filters.TEXT, callback=settings.manage_users_and_permissions)
            ],
            ConversationState.CONFIRM_LABEL: [
                CallbackQueryHandler(pattern="^confirm_label$", callback=settings.manage_users_and_permissions),
                CallbackQueryHandler(pattern="^rewrite_label$", callback=settings.manage_users_and_permissions)
            ],
            ConversationState.SET_PERMISSION: [
                CallbackQueryHandler(pattern="^set_permission_true.+$", callback=set_user_permissions),
                CallbackQueryHandler(pattern="^set_permission_false.+$", callback=set_user_permissions),
                CallbackQueryHandler(pattern="^set_default_permissions$", callback=set_user_permissions)
            ],

            ConversationState.REMOVE_OR_EDIT_USER: [
                MessageHandler(filters=filters.TEXT, callback=settings.manage_users_and_permissions)
            ],
            ConversationState.CONFIRM_REMOVE_USER: [
                CallbackQueryHandler(pattern="^remove_allowed_user.+$", callback=settings.manage_users_and_permissions),
                CallbackQueryHandler(pattern="^remove_allowed_user$", callback=settings.manage_users_and_permissions)
            ],

            ConversationState.CONFIRM_EDIT_USER: [
                CallbackQueryHandler(pattern="^edit_allowed_user.+$", callback=manage_users_and_permissions),
                CallbackQueryHandler(pattern="^edit_user_permissions$", callback=manage_users_and_permissions)
            ],

            ConversationState.DELETE_USER_BACKUPS: [
                CallbackQueryHandler(pattern="^delete_backup_files.+$", callback=settings.manage_users_and_permissions)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(pattern="^from_user_managing$", callback=settings.change_settings)
        ],
        allow_reentry=True
    )

    conv_handler2 = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(pattern="^settings$", callback=settings.change_settings),
            CallbackQueryHandler(pattern="^default_setting_finished.+$", callback=send_menu),
            CallbackQueryHandler(pattern="^first_configuration_completed.+$", callback=send_menu),
            CallbackQueryHandler(pattern="last_checks", callback=settings.list_last_checks)
        ],
        states={
            ConversationState.CHANGE_SETTINGS: [
                CallbackQueryHandler(pattern="menage_apps", callback=settings.menage_apps),
                conv_handler1,
                backup_restore_conv_handler,
                user_managing_conv_handler
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

    # appl.add_handler(TypeHandler(Update, callback=catch_update), group=-1)

    appl.add_handler(conv_handler1)
    appl.add_handler(conv_handler2)

    appl.add_handler(CallbackQueryHandler(pattern="^suspend_app.+$", callback=settings.suspend_app))
    appl.add_handler(CallbackQueryHandler(pattern="^delete_message.+$",
                                          callback=settings.delete_extemporary_message))
    appl.add_handler(CallbackQueryHandler(pattern="^edit_from_job.+$", callback=settings.see_app_settings))
    appl.add_handler(set_app_conv_handler)

    appl.run_polling()


if __name__ == '__main__':
    load_dotenv()
    main()
