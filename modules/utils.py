import os.path
import re

import yaml
import logging
import telegram

from telegram.constants import ChatAction
from telegram.ext import CallbackContext, ContextTypes
from telegram import Update, InlineKeyboardButton
from google_play_scraper import app

from config_values import ValidateIntervalOutcome
from modules.config_values import ValidateSendOnCheckOutcome, ValidateResult, ValidateAppConfiguration
from modules.job_queue import scheduled_send_message


bot_logger = logging.getLogger("bot_logger")

async def is_allowed_user(user_id: int, users: dict) -> bool:
    await check_dict_keys(users, ["owner", "admin", "allowed"] )
    return user_id == users["owner"] or user_id == users["admin"] or user_id in users["allowed"]


async def check_dict_keys(d: dict, keys: list):
    mancanti = [key for key in keys if key not in d]
    if len(mancanti) != 0:
        raise Exception(f"Missing key(s): {mancanti} in dictionary {d}")


async def get_app_id_from_link(link: str) -> str:
    return link.split('id=')[1].split('&hl=')[0]


async def initialize_chat_data(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
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
                    "tutorial": primo avvio
                },
            "last_checks":{
                    "1": {
                        "last_check_time": data ultimo check
                    },
                    ...
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

    cd["apps"] = {}
    cd["settings"] = {
        "default_check_interval": {
            "timedelta": None,
            "input": None
        },
        "default_send_on_check": None,
    }
    cd["last_checks"] = []
    cd["first_boot"] = True

    if "editing" in cd:
        del cd["editing"]
    if "adding" in cd:
        del cd["adding"]
    if "removing" in cd:
        del cd["removing"]

    if os.path.isfile("config/first_boot.yml") and user_id == bd["users"]["owner"]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
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
                    keyboard = [
                        [
                            InlineKeyboardButton(text="🐔 Va bene, sono un pollo", callback_data="linxay_chicken")
                        ]
                    ]
                    context.job_queue.run_once(
                        callback=scheduled_send_message,
                        data={
                            "text": "⚠️ <b>Syntax Error in First Boot Configuration File</b>\n\n"
                                    "🔸 C'è qualcosa che non va nel file <code>first_boot.yml</code>. Controlla il file "
                                    "<code>logs/main.logs</code> per i dettagli.\n\n"
                                    "ℹ La configurazione verrà ignorata.",
                            "chat_id": chat_id,
                            "keyboard": keyboard
                        },
                        when=2
                    )

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

                    context.job_queue.run_once(
                        callback=scheduled_send_message,
                        data={
                            "text": text,
                            "chat_id": chat_id,
                            "keyboard": keyboard
                        },
                        when=2
                    )
                
                
async def validate_interval(interval: str, default_value: bool):
    if default_value:
        if interval == "DEFAULT":
            return ValidateIntervalOutcome.SUCCESS, 'default'

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


async def validate_send_on_check(value, default_value: bool):
    if default_value and not isinstance(value, bool):
        return ValidateSendOnCheckOutcome.INVALID_TYPE

    if not default_value and (not isinstance(value, bool) and value != 'DEFAULT'):
        return ValidateSendOnCheckOutcome.INVALID_TYPE

    return ValidateSendOnCheckOutcome.SUCCESS


async def validate_app_config(app_config):
    if not isinstance(app_config, dict):
        return ValidateAppConfiguration.INVALID_TYPE

    if len([missing for missing in ["link", "interval", "send_on_check"] if missing not in app_config]) != 0:
        return ValidateAppConfiguration.MISSING_VALUES

    if not app_config["link"].startswith("https://play.google.com/store/apps/"):
        return ValidateAppConfiguration.INVALID_LINK

    if app_config["interval"] != 'DEFAULT':
        aico, values = await validate_interval(app_config["interval"], False)
        if aico != ValidateIntervalOutcome.SUCCESS:
            return ValidateAppConfiguration.from_interval_outcome(aico)

    if await validate_send_on_check(app_config["send_on_check"], False) != ValidateSendOnCheckOutcome.SUCCESS:
        return ValidateAppConfiguration.SEND_ON_CHECK_INVALID_TYPE

    return ValidateAppConfiguration.SUCCESS


async def check_first_boot_configuration(conf: dict):
    ico, values = await validate_interval(conf['settings']['default_interval'], True)

    if ico != ValidateIntervalOutcome.SUCCESS:
        ico = ValidateIntervalOutcome.get_outcome(ico)
        bot_logger.warning(f"First Boot Configuration – Syntax Error: {ico}. Check the file.")
        return ico

    soco = await validate_send_on_check(conf['settings']['default_send_on_check'], True)

    if soco != ValidateSendOnCheckOutcome.SUCCESS:
        soco = ValidateSendOnCheckOutcome.get_outcome(soco)
        bot_logger.warning(f"First Boot Configuration – Syntax Error: {soco}. Check the file.")
        return soco

    for app_index in conf['apps']:
        aco = await validate_app_config(conf['apps'][app_index])
        if aco != ValidateAppConfiguration.SUCCESS:
            aco = ValidateAppConfiguration.get_outcome(aco)
            bot_logger.warning(f"First Boot Configuration – Syntax Error for app #{app_index}: {aco}. Check the file.")
            return aco

    return ValidateResult('Success', 1, 'Configuration is valid.')


async def first_boot_configuration(update: Update, context: CallbackContext):
    cd = context.chat_data

    if update.callback_query.data == "load_first_boot_configuration_no":
        del cd['first_boot']
        return

    await delete_message(context=context, chat_id=update.effective_chat.id, message_id=update.effective_message.id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # carica la configurazione presa dal file 'first_boot.yml'



async def delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    try:
        await context.bot.delete_message(chat_id=chat_id,
                                         message_id=message_id)
    except telegram.error.BadRequest:
        pass