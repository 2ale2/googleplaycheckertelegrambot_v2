import os.path
import re

import yaml
from telegram.ext import CallbackContext
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from google_play_scraper import app

from config_values import CheckIntervalResult


async def is_allowed_user(user_id: int, users: dict) -> bool:
    await check_dict_keys(users, ["owner", "admin", "allowed"] )
    return user_id == users["owner"] or user_id == users["admin"] or user_id in users["allowed"]


async def check_dict_keys(d: dict, keys: list):
    mancanti = [key for key in keys if key not in d]
    if len(mancanti) != 0:
        raise Exception(f"Missing key(s): {mancanti} in dictionary {d}")


async def get_app_id_from_link(link: str) -> str:
    return link.split('id=')[1].split('&hl=')[0]


async def check_interval(interval: str):
    pattern = r"(?:(\d+)m)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)min)?(?:(\d+)s)?"

    if not (match := re.match(pattern, interval)):
        return CheckIntervalResult.INVALID_FORMAT

    months = match.group(1)
    days = match.group(2)
    hours = match.group(3)
    minutes = match.group(4)
    seconds = match.group(5)

    if not all([months, days, hours, minutes, seconds]):
        return CheckIntervalResult.MISSING_VALUES

    months, days, hours, minutes, seconds = [int(value) for value in [months, days, hours, minutes, seconds]]

    if any(value < 0 for value in [months, days, hours, minutes, seconds]):
        return CheckIntervalResult.NON_POSITIVE_VALUES

    return CheckIntervalResult.SUCCESS


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
    if update.callback_query:
        if update.callback_query.data == "load_first_boot_configuration_no":
            del cd['first_boot']
        else:
            # carica la configurazione presa dal file 'first_boot.yml'

            pass


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

    if os.path.isfile("config/first_boot.yml") and user_id == bd["users"]["owner"] and not update.callback_query:
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

                cd['first_boot_configuration'] = first_boot

                text = ("🚨 <b>First Boot File Found</b>\n\nÈ stata trovata una configurazione all'interno del file "
                        "<code>first_boot.yml</code>.\n\n"
                        "➡ <b>Default Settings</b>\n"
                        f"    - <u>Interval</u>: <code>{first_boot['settings']['default_interval']}</code>\n"
                        f"    - <u>Send On Check</u>: <code>{first_boot['settings']['default_send_on_check']}</code>\n\n")

                if len(first_boot['apps']):
                    text += "➡ <b>Apps</b>\n"
                    for el in first_boot['apps']:
                        ad = app(app_id=await get_app_id_from_link(first_boot['apps'][el]['link']))
                        text += f"    - <u>Name</u>: <code>{ad.get('title')}</code>\n"
                        text += f"    - <u>Interval</u>: <code>{first_boot['apps'][el]['interval']}</code>\n"
                        text += f"    - <u>Send On Check</u>: <code>{first_boot['apps'][el]['send_on_check']}</code>\n\n"

                text += "🔸 Vuoi caricare questa configurazione?"
                keyboard = [
                    [
                        InlineKeyboardButton(text="🆗 Si", callback_data="load_first_boot_configuration_yes"),
                        InlineKeyboardButton(text="🚮 No", callback_data="load_first_boot_configuration_no")
                    ]
                ]

                await context.bot.send_message(text=text, chat_id=update.effective_chat.id,
                                               reply_markup=InlineKeyboardMarkup(keyboard),
                                               parse_mode='HTML',
                                               disable_web_page_preview=True)
                pass

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
