import os.path
import re
import glob

import yaml
import logging
import telegram
from google_play_scraper.exceptions import NotFoundError

from telegram.constants import ChatAction
from telegram.ext import CallbackContext, ContextTypes, ConversationHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from google_play_scraper import app
from datetime import datetime, timedelta
from pytz import timezone

from yaml_de_serializer import serialize_dict_to_yaml, deserialize_dict_from_yaml
from config_values import *
import modules.job_queue as job_queue

bot_logger = logging.getLogger("bot_logger")
settings_logger = logging.getLogger("settings_logger")


async def is_allowed_user(user_id: int, users: dict) -> bool:
    await check_dict_keys(users, ["owner", "admin", "allowed"])
    return user_id == users["owner"] or user_id == users["admin"] or user_id in users["allowed"]


async def is_allowed_user_function(user_id: int, users: dict, permission: str) -> bool:
    if not await is_allowed_user(user_id, users):
        return False

    if user_id == users["owner"]:
        return True

    if user_id == users["admin"]:
        return True

    if permission not in users["allowed"][user_id]:
        raise ValueError(f"Permission {permission} does not exist in {user_id} record.")

    return users["allowed"][user_id]["permissions"][permission]


async def get_functions_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton(text="🗂 Gestisci App", callback_data="menage_apps"),
            InlineKeyboardButton(text="🔧 Imp. Default", callback_data="edit_default_settings")
        ]
    ]

    cd = context.chat_data

    if cd["user_type"] == 'owner' or cd["user_type"] == 'admin':
        for permission in context.bot_data["settings"]["permissions"]:
            p = context.bot_data["settings"]["permissions"][permission]
            button = InlineKeyboardButton(text=p["button_text"], callback_data=p["button_data"])
            if len(keyboard) == 1 or len(keyboard[1]) == 2:
                keyboard.insert(1, [button])
            else:
                keyboard[1].append(button)
    else:
        for permission in context.bot_data["settings"]["permissions"]:
            p = context.bot_data["settings"]["permissions"][permission]
            if await is_allowed_user_function(user_id=update.effective_user.id,
                                              users=context.bot_data["users"],
                                              permission=permission):
                button = InlineKeyboardButton(text=p["button_text"], callback_data=p["button_data"])
            else:
                button = InlineKeyboardButton(text=p["button_text"] + " ⛔️", callback_data=p["button_data"])

            if len(keyboard) == 1 or len(keyboard[1]) == 2:
                keyboard.insert(1, [button])
            else:
                keyboard[1].append(button)

    keyboard.append([InlineKeyboardButton(text="🔙 Menu Principale", callback_data="back_to_main_menu")])

    return keyboard


async def check_dict_keys(d: dict, keys: list):
    mancanti = [key for key in keys if key not in d]
    if len(mancanti) != 0:
        raise Exception(f"Missing key(s): {mancanti} in dictionary {d}")


async def get_app_id_from_link(link: str) -> str:
    return link.split('id=')[1].split('&hl=')[0]


async def is_there_suspended_app(apps: dict) -> bool:
    for ap in apps:
        if apps[ap]['suspended']:
            return True
    return False


async def parse_conversation_message(context: CallbackContext, data: dict):
    await check_dict_keys(data, ["chat_id", "message_id", "text", "reply_markup"])

    chat_id, message_id, text, reply_markup = data["chat_id"], data["message_id"], data["text"], data["reply_markup"]

    keyboard = [
        [InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="back_to_settings")]
    ]

    reply_markup = reply_markup if reply_markup else (InlineKeyboardMarkup(keyboard) if reply_markup is None else None)

    try:
        await context.bot.edit_message_text(chat_id=chat_id,
                                            message_id=message_id,
                                            text=text,
                                            reply_markup=reply_markup,
                                            parse_mode="HTML",
                                            disable_web_page_preview=True)
        return message_id

    except telegram.error.BadRequest as e:
        settings_logger.warning(f"Not able to edit message: {e}. A new one will be sent.")

        # se il messaggio è stato rimosso e ne viene mandato un altro, i tasti che contengono un id scatenerebbero
        # un'eccezione nelle fasi successive, ma il 'try-except...pass' ovvia al problema.
        message = await context.bot.send_message(chat_id=chat_id,
                                                 text=text,
                                                 reply_markup=reply_markup,
                                                 parse_mode="HTML",
                                                 disable_web_page_preview=True)

        if "close_button" in data:
            button = keyboard
            for i in data["close_button"][:-1]:
                button = button[i - 1]

            # noinspection PyTypeChecker
            button[data["close_button"][-1] - 1] = InlineKeyboardButton(
                text="🔙 Torna Indietro",
                callback_data=f"back_to_main_settings {message_id}"
            )

            await context.bot.edit_message_reply_markup(chat_id=chat_id,
                                                        message_id=message.id,
                                                        reply_markup=InlineKeyboardMarkup(keyboard))
        return message.id


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
    if update.callback_query and update.callback_query.data == "from_backup_restore":
        keyboard.append([InlineKeyboardButton(text="🔐 Close Menu",
                                              callback_data="delete_message {}".format(update.effective_message.id))])
        await parse_conversation_message(context=context,
                                         data={
                                             "chat_id": update.effective_chat.id,
                                             "text": text,
                                             "reply_markup": InlineKeyboardMarkup(keyboard),
                                             "message_id": update.effective_message.message_id
                                         })
        return ConversationHandler.END
    else:
        if update.callback_query and update.callback_query.data == "back_to_main_menu":
            await delete_message(chat_id=update.effective_chat.id, message_id=update.effective_message.message_id,
                                 context=context)
        keyboard.append([InlineKeyboardButton(text="🔐 Close Menu", callback_data="delete_message {}")])
        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "close_button": [2, 1]
        }, context=context)

        return ConversationState.CHANGE_SETTINGS


async def initialize_chat_data(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    cd = context.chat_data
    bd = context.bot_data
    """
        {
            "user_type": "owner" / "admin" / "allowed"
            "permissions": {
                "can_menage_backups": True / False
            }
            "first_boot": True,
            "apps": {
                1: {
                        "app_name": nome dell'app
                        "app_id": id del pacchetto
                        "app_link": link al Play Store
                        "current_version": ultima versione rilevata
                        "last_check_time": data e ora dell'ultimo controllo (serve in caso di arresti anomali)
                        "check_interval": intervallo tra due check
                        "next_check": data e ora prossimo check
                        "send_on_check": manda un messaggio anche se non è stato trovato un nuovo aggiornamento
                    },
                ...
            },
            "settings": {
                    "default_check_interval": {
                            "input": {
                                    "months": mesi
                                    "days": giorni
                                    "hours": ore
                                    "minutes": minuti
                                    "seconds": secondi
                                },
                            "timedelta": timedelta dell'input
                        },
                    "default_send_on_check": manda un messaggio anche se non è stato trovato un nuovo aggiornamento default
                    "first_boot": primo avvio
                },
            "last_checks":{
                    "1": {
                        "last_check_time": data ultimo check
                    },
                    ...
            },
            ,
            "backups": {
                1: {
                    "file_name": "backup1.txt",
                    "backup_time": datetime,
    
                }
            }
        }
    """

    if user_id == bd["users"]["owner"]:
        cd["user_type"] = "owner"
        cd["permissions"] = {}
        for permission in context.bot_data["settings"]["permissions"]:
            cd["permissions"][permission] = True
    elif user_id == bd["users"]["admin"]:
        cd["user_type"] = "admin"
        cd["permissions"] = {}
        for permission in context.bot_data["settings"]["permissions"]:
            cd["permissions"][permission] = True

    else:
        cd["user_type"] = "allowed"
        cd["permissions"] = {}
        for permission in context.bot_data["settings"]["permissions"]:
            cd["permissions"][permission] = bd["users"]["allowed"][user_id][permission]

    cd["chat_id"] = update.effective_chat.id
    cd["apps"] = {}
    cd["settings"] = {
        "default_check_interval": {
            "input": {
                "months": None,
                "days": None,
                "hours": None,
                "minutes": None,
                "seconds": None
            },
            "timedelta": None
        },
        "default_send_on_check": None
    }
    cd["last_checks"] = []
    cd["first_boot"] = True
    cd["backups"] = {}
    cd["temp"] = {}

    if os.path.isdir(user_folder := ("backups/" + str(update.effective_user.id))):
        l = glob.glob(user_folder + "/*.yml")
        for el in l:
            file_name = el.split("\\")[1]
            cd["backups"][len(cd["backups"]) + 1] = {}
            cd["backups"][len(cd["backups"])]["file_name"] = file_name
            file_name = file_name.split(".yml")[0]
            cd["backups"][len(cd["backups"])]["backup_time"] = datetime.strptime(file_name,
                                                                                 "%d_%m_%Y_%H_%M_%S")

    if "editing" in cd:
        del cd["editing"]
    if "adding" in cd:
        del cd["adding"]
    if "removing" in cd:
        del cd["removing"]

    if os.path.isfile("config/first_boot.yml") and user_id == bd["users"]["owner"]:
        with open("config/first_boot.yml", 'r') as f:
            try:
                first_boot = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                raise Exception(f"Error in 'first_boot.yml' file. Check YAML syntax or contact @AleLntr: {exc}")
            else:
                # controllo chiavi - le chiavi 'settings' (con 'default_interval' e 'default_send_on_check') e 'apps'
                # devono necessariamente essere presenti
                if "settings" not in first_boot:
                    raise Exception("Missing key 'settings' in 'first_boot.yml' configuration file.")
                for key in ['default_interval', 'default_send_on_check']:
                    if key not in first_boot["settings"]:
                        raise Exception(f"Missing key '{key}' in 'first_boot.yml' (settings) configuration file.")
                if "apps" not in first_boot:
                    raise Exception("Missing key 'apps' in 'first_boot.yml' configuration file.")
                for el in first_boot["apps"]:
                    for key in ['link', 'interval', 'send_on_check']:
                        if key not in first_boot["apps"][el]:
                            raise Exception(f"Missing key '{key}' in 'first_boot.yml' (apps[{el}]) configuration file.")

                if (await check_first_boot_configuration(first_boot)).get_code() != 1:
                    text = ("⚠️ <b>Syntax Error in First Boot Configuration File</b>\n\n"
                            "🔸 C'è qualcosa che non va nel file <code>first_boot.yml</code>. Controlla il file "
                            "<code>logs/main.logs</code> per i dettagli.\n\n"
                            "ℹ La configurazione verrà ignorata.")
                    keyboard = [
                        [
                            InlineKeyboardButton(text="🐔 Va bene, sono un pollo", callback_data="linxay_chicken {}")
                        ]
                    ]

                    data = {
                        "chat_id": update.effective_chat.id,
                        "text": text,
                        "keyboard": keyboard,
                        "web_preview": False,
                        "close_button": [1, 1]
                    }

                    return FirstBootConfigFileCheck(FOUND_AND_INVALID, data)

                else:
                    cd['first_boot_configuration'] = first_boot

                    text = (
                        "🚨 <b>First Boot File Found</b>\n\nÈ stata trovata una configurazione all'interno del file "
                        "<code>first_boot.yml</code>.\n\n"
                        "➡ <b>Default Settings</b>\n"
                        f"    - <u>Interval</u>: <code>{first_boot['settings']['default_interval']}</code>\n"
                        f"    - <u>Send On Check</u>: <code>{first_boot['settings']['default_send_on_check']}"
                        f"</code>\n\n")

                    if len(first_boot['apps']):
                        text += "➡ <b>Apps</b>\n"
                        for el in first_boot['apps']:
                            ad = app(app_id=await get_app_id_from_link(first_boot['apps'][el]['link']))
                            text += f"    - <u>Name</u>: <code>{ad.get('title')}</code>\n"
                            text += f"    - <u>Interval</u>: <code>{first_boot['apps'][el]['interval']}</code>\n"
                            text += (f"    - <u>Send On Check</u>: <code>{first_boot['apps'][el]['send_on_check']}"
                                     f"</code>\n\n")

                    text += "🔸 Vuoi caricare questa configurazione?"
                    keyboard = [
                        [
                            InlineKeyboardButton(text="🆗 Si", callback_data="load_first_boot_configuration_yes"),
                            InlineKeyboardButton(text="🚮 No", callback_data="load_first_boot_configuration_no")
                        ]
                    ]

                    data = {
                        "chat_id": update.effective_chat.id,
                        "text": text,
                        "keyboard": keyboard,
                        "web_preview": False,
                        "close_button": [[1, 1], [1, 2]]
                    }

                    return FirstBootConfigFileCheck(FOUND_AND_VALID, data)
    else:
        text = ("🚧 <b>First Boot</b>\n\n"
                "ℹ️ <code>Configuration file not found</code>\n\n🔸 Prima di cominciare ad usare questo bot, "
                "vuoi un breve riepilogo sul suo funzionamento generale?\n\n"
                "@AleLntr dice che è consigliabile 😊")
        keyboard = [
            [InlineKeyboardButton(text="💡 Informazioni Generali", callback_data="print_tutorial {}")],
            [InlineKeyboardButton(text="⏭ Procedi – Settaggio Valori Default",
                                  callback_data="set_defaults {}")],
        ]
        data = {
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "web_preview": False,
            "close_button": [[1, 1], [2, 1]]
        }
        return FirstBootConfigFileCheck(NOT_FOUND, data)


async def validate_interval(interval: str):
    pattern = r"(?:(\d+)m)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)min)?(?:(\d+)s)?"

    if not (match := re.match(pattern, interval)):
        return ValidateIntervalOutcome.INVALID_FORMAT, None

    months = match.group(1)
    days = match.group(2)
    hours = match.group(3)
    minutes = match.group(4)
    seconds = match.group(5)

    if not all([months, days, hours, minutes, seconds]):
        return ValidateIntervalOutcome.MISSING_VALUES, None

    months, days, hours, minutes, seconds = [int(value) for value in [months, days, hours, minutes, seconds]]

    if any(value < 0 for value in [months, days, hours, minutes, seconds]):
        return ValidateIntervalOutcome.NON_POSITIVE_VALUES, None

    return ValidateIntervalOutcome.SUCCESS, [months, days, hours, minutes, seconds]


async def parse_interval(interval: str):
    ico, values = await validate_interval(interval)

    if ico != ValidateIntervalOutcome.SUCCESS:
        bot_logger.warning(f"Invalid interval {interval}")
        return ico

    return values


async def validate_send_on_check(value):
    if not isinstance(value, bool):
        return ValidateSendOnCheckOutcome.INVALID_TYPE

    return ValidateSendOnCheckOutcome.SUCCESS


async def validate_app_config(app_config, conf: dict):
    if not isinstance(app_config, dict):
        return ValidateAppConfiguration.INVALID_TYPE

    if len([missing for missing in ["link", "interval", "send_on_check"] if missing not in app_config]) != 0:
        return ValidateAppConfiguration.MISSING_VALUES

    if not app_config["link"].startswith("https://play.google.com/store/apps/"):
        return ValidateAppConfiguration.INVALID_LINK

    if app_config["interval"] != 'DEFAULT':
        aico, values = await validate_interval(app_config["interval"])
        if aico != ValidateIntervalOutcome.SUCCESS:
            return ValidateAppConfiguration.from_interval_outcome(aico)
    else:
        app_config["interval"] = conf["settings"]["default_interval"]

    if app_config["send_on_check"] != 'DEFAULT':
        if await validate_send_on_check(app_config["send_on_check"]) != ValidateSendOnCheckOutcome.SUCCESS:
            return ValidateAppConfiguration.SEND_ON_CHECK_INVALID_TYPE
    else:
        app_config["send_on_check"] = conf["settings"]["default_send_on_check"]

    return ValidateAppConfiguration.SUCCESS


async def check_first_boot_configuration(conf: dict):
    ico, values = await validate_interval(conf['settings']['default_interval'])

    if ico != ValidateIntervalOutcome.SUCCESS:
        ico = ValidateIntervalOutcome.get_outcome(ico)
        bot_logger.warning(f"First Boot Configuration – Syntax Error: {ico}. Check the file.")
        return ico

    soco = await validate_send_on_check(conf['settings']['default_send_on_check'])

    if soco != ValidateSendOnCheckOutcome.SUCCESS:
        soco = ValidateSendOnCheckOutcome.get_outcome(soco)
        bot_logger.warning(f"First Boot Configuration – Syntax Error: {soco}. Check the file.")
        return soco

    for app_index in conf['apps']:
        aco = await validate_app_config(conf['apps'][app_index], conf)
        if aco != ValidateAppConfiguration.SUCCESS:
            aco = ValidateAppConfiguration.get_outcome(aco)
            bot_logger.warning(f"First Boot Configuration – Syntax Error for app #{app_index}: {aco}. Check the file.")
            return aco

    return ValidateResult('Success', 1, 'Configuration is valid.')


async def load_first_boot_configuration(update: Update, context: CallbackContext):
    cd = context.chat_data

    if update.callback_query.data == "load_first_boot_configuration_no":
        await delete_message(context=context, chat_id=update.effective_chat.id,
                             message_id=update.effective_message.id)
        del cd['first_boot_configuration']

        keyboard = [
            [InlineKeyboardButton(text="💡 Informazioni Generali", callback_data="print_tutorial {}")],
            [InlineKeyboardButton(text="⏭ Procedi – Settaggio Valori Default", callback_data="set_defaults {}")],
        ]

        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": "🚧 <b>First Boot</b>\n\n"
                    "ℹ️ <code>Configuration file ignored</code>\n\n🔸 Prima di cominciare ad usare questo bot, "
                    "vuoi un breve riepilogo sul suo funzionamento generale?\n\n"
                    "@AleLntr dice che è consigliabile 😊",
            "keyboard": keyboard,
            "close_button": [[1, 1], [2, 1]]
        }, context=context)
        return 0

    await delete_message(context=context, chat_id=update.effective_chat.id, message_id=update.effective_message.id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # carica la configurazione presa dal file 'first_boot.yml'
    dci = cd["settings"]["default_check_interval"]

    values = await parse_interval(cd["first_boot_configuration"]["settings"]["default_interval"])

    if not isinstance(values, list) or len(values) != 5:
        raise ValueError("Default interval must be a list of exactly 5 non-negative integers.")

    dci["input"] = {}

    dci["input"]["months"] = values[0]
    dci["input"]["days"] = values[1]
    dci["input"]["hours"] = values[2]
    dci["input"]["minutes"] = values[3]
    dci["input"]["seconds"] = values[4]

    dci["timedelta"] = timedelta(days=values[0] * 30 + values[1], hours=values[2], minutes=values[3], seconds=values[4])

    cd["settings"]["default_send_on_check"] = cd["first_boot_configuration"]["settings"]["default_send_on_check"]

    for app_index in (apps := cd["first_boot_configuration"]["apps"]):
        try:
            app_details = app(app_id=await get_app_id_from_link(apps[app_index]["link"]))
        except NotFoundError as e:
            raise ValueError(f"App with link '{apps[app_index]['link']}' not found: {e}")
        else:
            cd["apps"][len(cd["apps"]) + 1] = {
                "app_name": app_details["title"],
                "app_id": app_details["appId"],
                "app_link": app_details["url"],
                "current_version": app_details["version"],
                "last_check": None,
                "last_update": datetime.strptime(app_details["lastUpdatedOn"], "%b %d, %Y").strftime("%d %B %Y"),
                # 'next_check_time' viene creato in 'schedule_app_check'
                "send_on_check": cd["first_boot_configuration"]["apps"][app_index]["send_on_check"],
                "suspended": False
            }
            values = await parse_interval(cd["first_boot_configuration"]["apps"][len(cd["apps"])]["interval"])
            cd["apps"][len(cd["apps"])]["check_interval"] = {
                "input": {
                    "months": values[0],
                    "days": values[1],
                    "hours": values[2],
                    "minutes": values[3],
                    "seconds": values[4]
                },
                "timedelta": timedelta(
                    days=values[0] * 30 + values[1],
                    hours=values[2],
                    minutes=values[3],
                    seconds=values[4])
            }
            await schedule_app_check(cd, False, update, context)

    cd["first_boot"] = False

    keyboard = [
        [
            InlineKeyboardButton(text="⏭ Procedi al Menu Principale", callback_data="first_configuration_completed {}")
        ]
    ]

    await send_message_with_typing_action(data={
        "chat_id": update.effective_chat.id,
        "text": "✅ <b>First Boot Configuration Completed</b>\n\n"
                "🔹 Tutte le impostazioni e le app sono state configurate correttamente.",
        "keyboard": keyboard,
        "close_button": [1, 1]
    }, context=context)

    del cd["first_boot_configuration"]

    return ConversationHandler.END


async def send_message_with_typing_action(data: dict, context: CallbackContext, action: ChatAction = ChatAction.TYPING):
    await check_dict_keys(data, ["chat_id", "text"])

    await context.bot.send_chat_action(chat_id=data["chat_id"], action=action)
    context.job_queue.run_once(
        callback=job_queue.scheduled_send_message,
        data=data,
        when=1.5
    )


async def delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    try:
        await context.bot.delete_message(chat_id=chat_id,
                                         message_id=message_id)
    except telegram.error.BadRequest:
        pass


async def schedule_app_check(cd: dict, send_message: bool, update: Update, context: CallbackContext):
    added = True if "editing" not in cd else False

    if added:
        ap = cd["apps"][len(cd["apps"])]
    else:
        index = int(cd["app_index_to_edit"])
        ap = context.chat_data["apps"][index]
        del cd["app_index_to_edit"]
        del context.chat_data["editing"]

    ap["next_check"] = {}
    ap["next_check"] = datetime.now(timezone('Europe/Rome')) + ap["check_interval"]["timedelta"]

    if not added:
        jobs = context.job_queue.get_jobs_by_name(ap['app_name'])
        if len(jobs) > 0:
            for job in jobs:
                job.schedule_removal()

    # noinspection PyUnboundLocalVariable
    context.job_queue.run_repeating(
        callback=job_queue.scheduled_app_check,
        interval=ap["check_interval"]["timedelta"],
        chat_id=update.effective_chat.id,
        name=ap['app_name'],
        data={
            "chat_data": cd,
            "app_link": ap["app_link"],
            "app_id": ap["app_id"],
            "app_index": len(cd["apps"]) if added else index
        }
    )

    if send_message:
        text = (f"☑️ <b>App Settled Successfully</b>\n\n"
                f"🔹<u>Check Interval</u> ➡ "
                f"<code>"
                f"{ap['check_interval']['input']['months']}m"
                f"{ap['check_interval']['input']['days']}d"
                f"{ap['check_interval']['input']['hours']}h"
                f"{ap['check_interval']['input']['minutes']}"
                f"min"
                f"{ap['check_interval']['input']['seconds']}s"
                f"</code>\n"
                f"🔹<u>Send On Check</u> ➡ "
                f"<code>{ap['send_on_check']}</code>\n\n"
                f"🔸 <u>Next Check</u> ➡ <code>{ap['next_check'].strftime('%d %B %Y – %H:%M:%S')}</code>"
                f"\n\n")

        if added:
            button = InlineKeyboardButton(text="➕ Aggiungi Altra App", callback_data="add_app")
        else:
            button = InlineKeyboardButton(text="✏ Modifica Altra App", callback_data="edit_app")

        keyboard = [
            [
                button,
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="back_to_settings_settled")
            ]
        ] if "from_check" not in cd else [
            [
                InlineKeyboardButton(text="🗑 Chiudi", callback_data="delete_message {}")
            ]
        ]

        data = {
            "chat_id": update.effective_chat.id,
            "text": text,
            "message_id": update.effective_message.id,
            "keyboard": keyboard
        } if "from_check" not in cd else {
            "chat_id": update.effective_chat.id,
            "text": text,
            "message_id": update.effective_message.id,
            "keyboard": keyboard,
            "close_button": [1, 1]
        }

        if "from_check" in cd:
            del cd["from_check"]

        await send_message_with_typing_action(data=data, context=context)

    bot_logger.info(f"Repeating Job for app {ap['app_name']} Scheduled Successfully "
                    f"– Next Check at {(datetime.now(timezone('Europe/Rome'))
                                        + ap['check_interval']['timedelta']).strftime('%d %b %Y - %H:%M:%S')}")

    if "editing" in cd:
        del context.chat_data["editing"]

    return ConversationHandler.END


async def yaml_dict_dumper(cd: dict, filepath: str) -> bool:
    return serialize_dict_to_yaml(cd, filepath)


async def yaml_dict_loader(filepath: str):
    return deserialize_dict_from_yaml(filepath)


async def schedule_messages_to_delete(context: CallbackContext, messages: dict):
    for message in messages:
        await check_dict_keys(messages[message], ["time", "chat_id"])
        t, chat_id = messages[message]["time"], messages[message]["chat_id"]

        context.job_queue.run_once(callback=job_queue.scheduled_delete_message,
                                   data={
                                       "message_id": int(message),
                                       "chat_id": chat_id
                                   },
                                   when=t)


async def send_not_allowed_function_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("❌ Non sei abilitato all'uso di questa funzione.\n\n"
            "🔸 Scegli un'opzione")
    keyboard = [
        [
            InlineKeyboardButton(text="🔙 Torna Indietro", callback_data='settings$')
        ]
    ]

    await parse_conversation_message(data={
        "chat_id": update.effective_chat.id,
        "text": text,
        "message_id": -1,
        "reply_markup": InlineKeyboardMarkup(keyboard)
    }, context=context)
