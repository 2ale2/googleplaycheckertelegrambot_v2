import logging
from datetime import timedelta, datetime
from logging import handlers
from time import sleep

import pytz
import requests
import telegram
from google_play_scraper import app
from google_play_scraper.exceptions import NotFoundError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
from telegram.constants import ChatAction
from telegram.ext import CallbackContext, ConversationHandler, ContextTypes

import job_queue
from config_values import ConversationState
from utils import check_dict_keys, delete_message, schedule_app_check
from decorators import send_action

settings_logger = logging.getLogger("settings_logger")
settings_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = handlers.RotatingFileHandler(filename="logs/settings.log",
                                            maxBytes=1024, backupCount=1)
file_handler.setFormatter(formatter)
settings_logger.addHandler(file_handler)

bot_logger = logging.getLogger("bot_logger")


@send_action(ChatAction.TYPING)
async def set_defaults(update: Update, context: CallbackContext):
    if update.callback_query and update.callback_query.data == "edit_default_settings":
        await delete_message(context=context, chat_id=update.effective_chat.id,
                             message_id=update.effective_message.message_id)
        inp = context.bot_data["settings"]["default_check_interval"]["input"]
        text = (f"🔧 <b>Impostazioni di Default</b>\n\n"
                f"  🔹 <u>Default Interval</u> "
                f"<code>{inp['months']}m{inp['days']}d{inp['hours']}h{inp['minutes']}min{inp['seconds']}s</code>\n"
                f"  🔹 <u>Default Send On Check</u> "
                f"<code>{context.bot_data['settings']['default_send_on_check']}</code>\n\n"
                f"🔸 Scegli un'opzione.")

        sleep(1)

        message_id = await parse_conversation_message(context=context, data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "message_id": update.effective_message.message_id,
            "reply_markup": False
        })

        keyboard = [
            [
                InlineKeyboardButton(text="✏ Modifica", callback_data=f"confirm_edit_default_settings {message_id}"),
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="cancel_edit_settings")
            ]
        ]

        await context.bot.edit_message_reply_markup(chat_id=update.effective_chat.id,
                                                    message_id=message_id,
                                                    reply_markup=InlineKeyboardMarkup(keyboard))

        return 0

    if update.callback_query and (update.callback_query.data.startswith("set_defaults") or
                                  update.callback_query.data.startswith("interval_incorrect") or
                                  update.callback_query.data.startswith("confirm_edit_default_settings")):

        bot_logger.info(f"User {update.effective_user.id} – Starting to set default settings.")

        if "message_to_delete" in context.chat_data:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=context.chat_data["message_to_delete"])
            del context.chat_data["message_to_delete"]

        if len(li := update.callback_query.data.split(" ")) > 1:
            await delete_message(context=context, message_id=int(li[1]), chat_id=update.effective_chat.id)

        sleep(1)

        message = await context.bot.send_message(chat_id=update.effective_chat.id,
                                                 text="🔧 <b>Setting Default Values</b>\n\n"
                                                      "➡ <u>Default Checking Interval</u> – Se non specificherai un "
                                                      "intervallo di controllo, verrà settato quello che stai "
                                                      "impostando adesso.\n\n"
                                                      "❔ <b>Format</b>\nFornisci una stringa nel formato ↙\n\n "
                                                      "<code>?m?d?h?min?s</code>\n\nsostituendo i <code>?</code> con i "
                                                      "valori corrispondenti di:\n\n"
                                                      "\t1️⃣ <code>m</code> – Mesi\n"
                                                      "\t2️⃣ <code>d</code> – Giorni\n"
                                                      "\t3️⃣ <code>h</code> – Ore\n"
                                                      "\t4️⃣ <code>min</code> – Minuti\n"
                                                      "\t5️⃣ <code>s</code> – Secondi\n\n"
                                                      "Inserisci tutti i valori corrispondenti anche se nulli.\n\n "
                                                      "<b>Esempio</b> 🔎 – <code>0m2d0h15min0s</code>\n\n"
                                                      "ℹ È consigliabile non scendere sotto i 30 secondi.\n\n"
                                                      "🔹Non è un valore definitivo: lo puoi cambiare quando vorrai.",
                                                 parse_mode="HTML")
        context.chat_data["messages_to_delete"] = message.id
        return 2

    if not update.callback_query and update.message:
        if "message_to_delete" in context.chat_data:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=context.chat_data["message_to_delete"])
            del context.chat_data["message_to_delete"]
        try:
            # noinspection DuplicatedCode
            months = int(update.message.text.split('m')[0])
            days = int(update.message.text.split('d')[0].split('m')[1])
            hours = int(update.message.text.split('h')[0].split('d')[1])
            minutes = int(update.message.text.split('min')[0].split('h')[1])
            seconds = int(update.message.text.split('s')[0].split('min')[1])

            context.job_queue.run_once(callback=job_queue.scheduled_delete_message,
                                       data={
                                           "chat_id": update.effective_chat.id,
                                           "message_id": context.chat_data["messages_to_delete"],
                                       },
                                       when=2)

            context.job_queue.run_once(callback=job_queue.scheduled_delete_message,
                                       data={
                                           "chat_id": update.effective_chat.id,
                                           "message_id": update.message.id,
                                       },
                                       when=2.5)

            del context.chat_data["messages_to_delete"]

        except ValueError:
            text = ("❌ <b>Usa il formato indicato</b>, non aggiungere, togliere o cambiare lettere."
                    "\n\n🔎 <code>#m#d#h#min#s</code>")
            message = await context.bot.send_message(chat_id=update.effective_chat.id,
                                                     text=text, parse_mode="HTML")
            context.chat_data["messages_to_delete"] = message.id
            return 2
        else:
            if months < 0 or days < 0 or hours < 0 or minutes < 0 or seconds < 0:
                text = ("❌ <b>Tutti i valori devono essere positivi</b>\n\n🔸 Fornisci un nuovo intervallo.\n\n"
                        "🔎 <code>#m#d#h#min#s</code>")
                message = await context.bot.send_message(chat_id=update.effective_chat.id,
                                                         text=text, parse_mode="HTML")
                context.chat_data["messages_to_delete"] = message.id
                return 2

            if months == 0 and days == 0 and hours == 0 and minutes == 0 and seconds == 0:
                text = ("❌ <b>L'intervallo non può essere nullo</b>\n\n🔸 Fornisci un nuovo intervallo.\n\n"
                        "ℹ È consigliabile non scendere sotto i 30 secondi.\n\n🔎 <code>#m#d#h#min#s</code>")
                message = await context.bot.send_message(chat_id=update.effective_chat.id,
                                                         text=text, parse_mode="HTML")
                context.chat_data["messages_to_delete"] = message.id
                return 2

            context.chat_data["settings"]["default_check_interval"]["timedelta"] = timedelta(days=days + months * 30,
                                                                                            seconds=seconds,
                                                                                            minutes=minutes,
                                                                                            hours=hours)
            context.bot_data["settings"]["default_check_interval"]["input"] = {
                "days": days,
                "months": months,
                "seconds": seconds,
                "minutes": minutes,
                "hours": hours
            }

            # noinspection DuplicatedCode
            text = (f"❓ Conferma se l'intervallo indicato è corretto.\n\n"
                    f"▫️️ <code>{months}</code> mesi\n"
                    f"▫️ <code>{days}</code> giorni\n"
                    f"▫️ <code>{hours}</code> ore\n"
                    f"▫️ <code>{minutes}</code> minuti\n"
                    f"▫️ <code>{seconds}</code> secondi")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            sleep(1)
            message = await context.bot.send_message(chat_id=update.effective_chat.id,
                                                     text=text,
                                                     parse_mode="HTML")
            keyboard = [
                [
                    InlineKeyboardButton(text="✅ È corretto", callback_data=f"interval_correct {message.id}"),
                    InlineKeyboardButton(text="❌ Non è corretto", callback_data=f"interval_incorrect {message.id}")
                ]
            ]
            await context.bot.edit_message_reply_markup(chat_id=update.effective_chat.id,
                                                        message_id=message.id,
                                                        reply_markup=InlineKeyboardMarkup(keyboard))
            return 2

    if update.callback_query and update.callback_query.data.startswith("interval_correct"):
        i = context.bot_data["settings"]["default_check_interval"]["input"]
        bot_logger.info(f"Default Interval -> Setting Completed: "
                        f"{i['months']}m{i['days']}d{i['months']}h{i['months']}min{i['seconds']}s")

        if len(li := update.callback_query.data.split(" ")) > 1:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=int(li[1]))

        text = ("🔧 <b>Setting Default Values</b>\n\n"
                "➡ <u>Default Send On Check</u> – Scegli se, di default, ti verrà mandato un messaggio <b>solo "
                "quando viene trovato un aggiornamento</b> (<code>False</code>) o <b>ad ogni controllo</b>"
                " (<code>True</code>)."
                "\n\n🔹Potrai cambiare questa impostazione in seguito.")

        sleep(1)

        message = await context.bot.send_message(chat_id=update.effective_chat.id,
                                                 text=text,
                                                 parse_mode="HTML")
        keyboard = [
            [
                InlineKeyboardButton(text="✅ True", callback_data=f"default_send_on_check_true {message.id}"),
                InlineKeyboardButton(text="❌ False", callback_data=f"default_send_on_check_false {message.id}")
            ]
        ]
        await context.bot.edit_message_reply_markup(chat_id=update.effective_chat.id,
                                                    message_id=message.id,
                                                    reply_markup=InlineKeyboardMarkup(keyboard))
        return 3

    if update.callback_query and update.callback_query.data.startswith("default_send_on_check"):
        i = context.bot_data["settings"]["default_check_interval"]["input"]
        if len(li := update.callback_query.data.split(" ")) > 1:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=int(li[1]))

        if update.callback_query.data.startswith("default_send_on_check_true"):
            context.bot_data["settings"]["default_send_on_check"] = True
        else:
            context.bot_data["settings"]["default_send_on_check"] = False

        bot_logger.info(f"Default Send On Check -> Setting Completed: "
                        f"{context.bot_data['settings']['default_send_on_check']}")

        bot_logger.info(f"Default Setting Completed.")

        text = (f"☑️ <b>Setting Completed</b>\n\n"
                f"🔸 <u>Default Interval</u> – "
                f"<code>{i['months']}m"
                f"{i['days']}d"
                f"{i['hours']}h"
                f"{i['minutes']}min"
                f"{i['seconds']}s</code>\n"
                f"🔸 <u>Default Send On Check</u> – "
                f"<code>{str(context.bot_data['settings']['default_send_on_check'])}"
                f"</code>\n\n"
                f"🔹Premi il tasto sotto per procedere.")

        sleep(1)
        message = await context.bot.send_message(chat_id=update.effective_chat.id,
                                                 text=text,
                                                 parse_mode="HTML")
        keyboard = [
            [InlineKeyboardButton(text="⏭ Procedi", callback_data=f"default_setting_finished {message.id}")]
        ]

        await context.bot.edit_message_reply_markup(chat_id=update.effective_chat.id,
                                                    message_id=message.id,
                                                    reply_markup=InlineKeyboardMarkup(keyboard))
        if not context.bot_data["settings"]["tutorial"]:
            context.bot_data["settings"]["tutorial"] = True
        return ConversationHandler.END


async def change_settings(update: Update, context: CallbackContext):
    text = ("⚙ <b>Settings Panel</b>\n\n🔹Da qui puoi cambiare le impostazioni di default e gestire le applicazioni "
            "monitorate.\n\n🔸 Scegli un'opzione.")

    keyboard = [
        [
            InlineKeyboardButton(text="🗂 Gestisci App", callback_data="menage_apps"),
            InlineKeyboardButton(text="🔧 Imp. Default", callback_data="edit_default_settings")
        ],
        [InlineKeyboardButton(text="🔙 Menu Principale", callback_data="back_to_main_menu")]
    ]

    await parse_conversation_message(context=context,
                                     data={
                                         "chat_id": update.effective_chat.id,
                                         "message_id": update.effective_message.message_id,
                                         "text": text,
                                         "reply_markup": InlineKeyboardMarkup(keyboard)}
                                     )

    return (ConversationState.CHANGE_SETTINGS if update.callback_query.data != "cancel_edit_settings"
            else ConversationHandler.END)


async def menage_apps(update: Update, context: CallbackContext):
    if update.callback_query:
        if update.callback_query.data == "menage_apps" or update.callback_query.data.startswith("back_to_settings"):

            if "format_message" in context.chat_data:
                await delete_message(context=context,
                                     message_id=context.chat_data["format_message"],
                                     chat_id=update.effective_chat.id)
                del context.chat_data["format_message"]

            if "message_to_delete" in context.chat_data:
                await schedule_messages_to_delete(context=context,
                                                  messages={
                                                      int(context.chat_data["message_to_delete"]): {
                                                          "chat_id": update.effective_chat.id,
                                                          "time": 2
                                                      }
                                                  })

                del context.chat_data["message_to_delete"]

            text = ("🗂 <b>Gestione Applicazioni</b>\n\n"
                    "🔹Da questo menù, puoi visualizzare e gestire le applicazioni.")

            keyboard = [
                [
                    InlineKeyboardButton(text="✏️ Modifica", callback_data="edit_app"),
                    InlineKeyboardButton(text="➕ Aggiungi", callback_data="add_app"),
                    InlineKeyboardButton(text="➖ Rimuovi", callback_data="delete_app")
                ],
                [
                    InlineKeyboardButton(text="📄 Lista App", callback_data="list_apps")
                ],
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro",
                                         callback_data=f"settings {update.effective_message.id}")
                ]
            ]

            for ap in (a := context.bot_data["apps"]):
                if a[ap]["suspended"]:
                    keyboard[1].append(InlineKeyboardButton(text="⏯ Riattiva App", callback_data="unsuspend_app"))
                    break

            await parse_conversation_message(context=context,
                                             data={
                                                 "chat_id": update.effective_chat.id,
                                                 "message_id": update.effective_message.message_id,
                                                 "text": text,
                                                 "reply_markup": InlineKeyboardMarkup(keyboard)}
                                             )

            return ConversationState.MANAGE_APPS

        if update.callback_query.data == "list_apps" or update.callback_query.data == "go_back_to_list_apps":
            if len(context.bot_data["apps"]) == 0:
                keyboard = [
                    [
                        InlineKeyboardButton(text="➕ Aggiungi", callback_data="add_app"),
                        InlineKeyboardButton(text="🔙 Torna Indietro",
                                             callback_data=f"back_to_main_settings {update.effective_message.id}")
                    ]
                ]
                text = ("🅾️ <code>No Apps Yet</code>\n\n"
                        "🔸 Usa la tastiera per aggiungerne.")

                await parse_conversation_message(context=context,
                                                 data={
                                                     "chat_id": update.effective_chat.id,
                                                     "message_id": update.effective_message.message_id,
                                                     "text": text,
                                                     "reply_markup": InlineKeyboardMarkup(keyboard)})

            else:
                keyboard = [
                    [
                        InlineKeyboardButton(text="➕ Aggiungi", callback_data="add_app"),
                        InlineKeyboardButton(text="➖ Rimuovi", callback_data="remove_app"),
                        InlineKeyboardButton(text="🖋 Modifica", callback_data="edit_app")
                    ],
                    [InlineKeyboardButton(text="🔎 Dettagli App", callback_data="info_app")],
                    [InlineKeyboardButton(text="🔙 Torna Indietro",
                                          callback_data=f"back_to_main_settings {update.effective_message.id}")]
                ]

                text = "👁‍🗨 <b>Watched Apps</b>\n\n"
                for a in context.bot_data["apps"]:
                    text += (f"  {a}. {context.bot_data['apps'][str(a)]['title']}\n"
                             f"    <code>Interval</code> {context.bot_data['apps'][str(a)]['check_interval']}\n"
                             f"    <code>Send On Check</code> {context.bot_data['apps'][str(a)]['send_on_check']}\n"
                             )

                text += "\n🆘 Per i dettagli su un'applicazione, scegli 🖋 Modifica\n\n🔸Scegli un'opzione."

                await parse_conversation_message(context=context,
                                                 data={
                                                     "chat_id": update.effective_chat.id,
                                                     "message_id": update.effective_message.message_id,
                                                     "text": text,
                                                     "reply_markup": InlineKeyboardMarkup(keyboard)}
                                                 )

            return ConversationState.LIST_APPS

        if update.callback_query.data == "remove_app" or update.callback_query.data == "go_back_to_remove_app":
            pass

        if update.callback_query.data == "edit_app" or update.callback_query.data == "go_back_to_edit_app":
            pass

        if update.callback_query.data == "info_app" or update.callback_query.data == "go_back_to_info_app":
            pass


async def close_menu(update: Update, context: CallbackContext):
    await delete_message(context=context, chat_id=update.effective_chat.id,
                         message_id=int(update.callback_query.data.split(" ")[1]))

    return ConversationHandler.END


@send_action(action=ChatAction.TYPING)
async def list_apps(update: Update, context: CallbackContext):
    await delete_message(context=context, chat_id=update.effective_chat.id, message_id=update.effective_message.id)

    text = "🗃 <b>App List</b>\n\n"

    if len(context.bot_data["apps"]) == 0:
        text += ("ℹ Nessuna app aggiunta.\n\n"
                 "🔸 Scegli un'opzione.")

    else:
        for a in context.bot_data["apps"]:
            ap = context.bot_data["apps"][a]
            text += (f"  {a}. <i>{ap['title']}</i>\n"
                     f"     🔸<u>App ID</u>: <code>{ap['appId']}</code>\n"
                     f"     🔸<u>App Link</u>: <a href=\"{ap['url']}\">link 🔗</a>\n"
                     f"     🔸<u>Current Version</u>: <code>{ap['current_version']}</code>\n"
                     f"     🔸<u>Last Update</u>: <code>{ap['last_update']}</code>\n\n"
                     f"     🔸<u>Check Interval</u>: <code>"
                     f"{ap['check_interval']['input']['months']}m"
                     f"{ap['check_interval']['input']['days']}d"
                     f"{ap['check_interval']['input']['hours']}h"
                     f"{ap['check_interval']['input']['minutes']}min"
                     f"{ap['check_interval']['input']['seconds']}s</code>\n"
                     f"     🔸<u>Send On Check</u>: <code>{ap['send_on_check']}</code>\n\n")

            text += (f"     🔸<u>Last Check</u>: <code>None</code>\n"
                     if ap["last_check"] is None
                     else f"     🔸<u>Last Check</u>: <code>"
                          f"{datetime.strftime(ap['last_check'], '%d %B %Y – %H:%M:%S')}"
                          f"</code>\n")

            text += (f"     🔸<u>Next Check</u>: <code>{datetime.strftime(ap['next_check'], '%d %B %Y – %H:%M:%S')}"
                     f"</code>\n\n     ⏸ <b>Suspended</b>: <code>{ap['suspended']}</code>\n\n")

        text += f"🔹 Scegli un'opzione."

    keyboard = [
        [InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="back_to_settings")]
    ]

    sleep(1)
    await parse_conversation_message(context=context, data={
        "chat_id": update.effective_chat.id,
        "text": text,
        "message_id": -1,
        "reply_markup": InlineKeyboardMarkup(keyboard)
    })

    return ConversationState.LIST_APPS


@send_action(action=ChatAction.TYPING)
async def list_last_checks(update: Update, context: CallbackContext):
    await delete_message(context=context, chat_id=update.effective_chat.id, message_id=update.effective_message.id)
    text = "📜 <b>Last Checks</b>\n\n"
    keyboard = [
        [
            InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="back_to_main_menu")
        ]
    ]

    if len(context.bot_data["last_checks"]) == 0:
        text += "🔸 Nessun controllo effettuato."

    else:
        for check in context.bot_data["last_checks"]:
            text += (f"🔸<b> {check['title']}</b>\n"
                     f"🔹 Time: <code>{datetime.strftime(check['time'], '%d %B %Y – %H:%M:%S')}</code>\n")
            if check["update_found"]:
                text += (f"▫ Update Found ➡ Upgraded from <code>{check['current_version']}</code> "
                         f"to <code>{check['new_version']}</code>")
            else:
                text += f"▪ Update Not Found ➡ <code>Current Version: {check['current_version']}</code>"
            text += "\n\n"

        text += "ℹ I controlli di eventuali app sospese non sono in lista."

    sleep(1)
    await parse_conversation_message(context=context,
                                     data={
                                         "chat_id": update.effective_chat.id,
                                         "message_id": update.effective_message.id,
                                         "text": text,
                                         "reply_markup": InlineKeyboardMarkup(keyboard)
                                     })
    return ConversationState.CHANGE_SETTINGS


async def add_app(update: Update, context: CallbackContext):
    if update.callback_query and update.callback_query.data == "add_app":
        text = "➕ <b>Add App</b>\n\n"

        if len(context.bot_data["apps"]) != 0:
            text += "🗃 <u>Elenco</u>\n\n"
            for ap in context.bot_data["apps"]:
                text += f"  {ap}. {context.bot_data['apps'][str(ap)]['title']}\n"

        text += "\n🔸 Manda il link all'applicazione su Google Play."

        context.chat_data["send_link_message"] = update.effective_message.id

        await parse_conversation_message(data={
            "chat_id": update.effective_chat.id,
            "message_id": update.effective_message.message_id,
            "text": text,
            "reply_markup": None
        }, context=context)

        return ConversationState.SEND_LINK

    not_cquery_message = update.message if update.message and not update.callback_query else None

    if not_cquery_message:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                           action=ChatAction.TYPING)
        if len(entities := not_cquery_message.entities) == 1 and entities[0].type == MessageEntity.URL:
            if "message_to_delete" in context.chat_data:
                await delete_message(context=context, chat_id=update.effective_chat.id,
                                     message_id=context.chat_data["message_to_delete"])
                del context.chat_data["message_to_delete"]

            link = update.message.text[entities[0].offset:]
            res = requests.get(link)

            if res.status_code != 200:
                settings_logger.warning(f"Not able to gather link {link}: {res.reason}")
                text = (f"❌ A causa di un problema di rete, non riuscito a reperire il link che hai mandato.\n\n"
                        f"🔍 <i>Reason</i>\n<code>❓ {res.reason}</code>\n\n"
                        f"🆘 Se il problema persiste, contatta @AleLntr\n\n"
                        f"🔸 Puoi riprovare a mandare lo stesso link o cambiarlo.")

                await parse_conversation_message(context=context,
                                                 data={
                                                     "chat_id": update.effective_chat.id,
                                                     "message_id": not_cquery_message.id,
                                                     "text": text,
                                                     "reply_markup": None
                                                 })

                return ConversationState.SEND_LINK

            app_details = await get_app_details_with_link(link=link)

            for ap in (a := context.bot_data["apps"]):
                if a[ap]["appId"] == app_details.get('appId'):
                    keyboard = [
                        [
                            InlineKeyboardButton(text="✏ Modifica l'App", callback_data=f"edit_app_from_add {ap}"),
                            InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="back_to_settings")
                        ]
                    ]
                    await parse_conversation_message(context=context,
                                                     data={
                                                         "chat_id": update.effective_chat.id,
                                                         "message_id": -1,
                                                         "text": "⚠ Hai già aggiunto questa applicazione.\n\n"
                                                                 "🔸 Scegli un'opzione.",
                                                         "reply_markup": InlineKeyboardMarkup(keyboard)
                                                     })
                    return ConversationHandler.END

            if isinstance(app_details, NotFoundError) or isinstance(app_details, IndexError):
                if isinstance(app_details, NotFoundError):
                    text = ("⚠️ Ho avuto problemi a reperire l'applicazione.\n\n"
                            "Potrebbe essere un problema di API o l'applicazione potrebbe essere stata rimossa.\n\n"
                            "🔸 Contatta @AleLntr per risolvere il problema, o manda un altro link.")
                else:
                    text = "❌ Sembra che il link non sia corretto (manca l'ID del pacchetto)"

                message_id = await parse_conversation_message(context=context,
                                                              data={
                                                                  "chat_id": update.effective_chat.id,
                                                                  "message_id": -1,
                                                                  "text": text,
                                                                  "reply_markup": None
                                                              })

                context.chat_data["message_to_delete"] = message_id

                await schedule_messages_to_delete(context=context,
                                                  messages={
                                                      update.effective_message.id: {
                                                          "chat_id": update.effective_chat.id,
                                                          "time": 2
                                                      }
                                                  })

                return ConversationState.SEND_LINK

            else:
                if "send_link_message" in context.chat_data:
                    await delete_message(context=context,
                                         chat_id=update.effective_chat.id,
                                         message_id=context.chat_data["send_link_message"])
                    del context.chat_data["send_link_message"]

                name = app_details.get('title')
                current_version = app_details.get('version')
                last_update = datetime.strptime(app_details.get('lastUpdatedOn'), '%b %d, %Y')
                app_id = app_details.get('appId')

                if name is None or current_version is None or last_update is None or app_id is None:
                    settings_logger.warning("Gathered App Detail is None. Check bot_data for reference.")

                context.chat_data["setting_app"] = {
                    "app_name": name,
                    "url": link,
                    "current_version": current_version,
                    "last_update": last_update.strftime("%d %B %Y"),
                    "appId": app_id
                }

                keyboard = [
                    [
                        InlineKeyboardButton(text="✅ Si", callback_data="app_name_from_link_correct"),
                        InlineKeyboardButton(text="❌ No", callback_data="app_name_from_link_not_correct")]
                ] if name else None

                text = f"❔ Il nome dell'applicazione è <b>{name}</b>?" \
                    if name else (f"⚠️ Il nome dell'applicazione è <code>None</code>. È possibile che ci sia "
                                  f"un problema di API o di struttura della pagina web.\n\n"
                                  f"🔸 Contatta @AleLntr per risolvere il problema, oppure <u>invia un altro link</u>.")

                message_id = await parse_conversation_message(context=context,
                                                              data={
                                                                  "chat_id": update.effective_chat.id,
                                                                  "message_id": -1,
                                                                  "text": text,
                                                                  "reply_markup": InlineKeyboardMarkup(
                                                                      keyboard) if keyboard else None
                                                              })

                context.chat_data["message_to_delete"] = message_id

                await schedule_messages_to_delete(context=context,
                                                  messages={
                                                      update.effective_message.id: {
                                                          "chat_id": update.effective_chat.id,
                                                          "time": 5
                                                      }
                                                  })

                return ConversationState.CONFIRM_APP_NAME if name else ConversationState.SEND_LINK

        else:
            if "send_link_message" in context.chat_data:
                await delete_message(context=context, chat_id=update.effective_chat.id,
                                     message_id=context.chat_data["send_link_message"])
                del context.chat_data["send_link_message"]

            keyboard = [
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro",
                                         callback_data=f"back_to_main_settings {not_cquery_message.id}"),
                    InlineKeyboardButton(text="🆘 Contatta @AleLntr", url='https://t.me/AleLntr')
                ]
            ]

            text = "❌ Non hai mandato un link valido o hai mandato più di un link nello stesso messaggio."

            message_id = await parse_conversation_message(context=context, data={
                "chat_id": update.effective_chat.id,
                "message_id": -1,
                "text": text,
                "reply_markup": InlineKeyboardMarkup(keyboard)
            })

            await schedule_messages_to_delete(context=context,
                                              messages={
                                                  int(not_cquery_message.id): {
                                                      "time": 2,
                                                      "chat_id": update.effective_chat.id,
                                                  }
                                              })

            context.chat_data["send_link_message"] = message_id

            return ConversationState.SEND_LINK

    if update.callback_query and update.callback_query.data == "app_name_from_link_not_correct":
        if "message_to_delete" in context.chat_data:
            del context.chat_data["message_to_delete"]

        if "send_link_message" in context.chat_data:
            await delete_message(context=context,
                                 chat_id=update.effective_chat.id,
                                 message_id=context.chat_data["send_link_message"])
            del context.chat_data["send_link_message"]

        text = ("⚠️ Se il nome non è corretto, è possibile che ci sia un problema con l'API di Google Play.\n\n"
                "🔸 Contatta @AleLntr o <u>invia un altro link</u>.")

        keyboard = [
            [
                InlineKeyboardButton(text="🆘 Scrivi ad @AleLntr", url="https://t.me/AleLntr")
            ],
            [
                InlineKeyboardButton(text="🔙 Torna Indietro",
                                     callback_data="back_to_settings")
            ]
        ]

        await parse_conversation_message(context=context, data={
            "chat_id": update.effective_chat.id,
            "message_id": update.effective_message.message_id,
            "text": text,
            "reply_markup": InlineKeyboardMarkup(keyboard)
        })

        return ConversationState.SEND_LINK


async def set_app(update: Update, context: CallbackContext):
    if update.callback_query and update.callback_query.data == "confirm_app_to_edit":
        if "edit_message" in context.chat_data:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=context.chat_data["edit_message"])
            del context.chat_data["edit_message"]
        ap = context.bot_data["apps"][context.chat_data["app_index_to_edit"]]
        context.chat_data["setting_app"] = {
            "title": ap["title"],
            "url": ap["url"],
            "current_version": ap["current_version"],
            "last_update": ap["last_update"],
            "appId": ap["appId"]
        }

        context.bot_data["editing"] = True

    if update.callback_query and (update.callback_query.data.startswith("edit_app_from_check") or
                                  update.callback_query.data.startswith("edit_app_from_add")):
        index = update.callback_query.data.split(" ")[1]
        context.chat_data["app_index_to_edit"] = index
        if update.callback_query.data.startswith("edit_app_from_check"):
            context.chat_data["from_check"] = True
        ap = context.bot_data["apps"][index]
        context.chat_data["setting_app"] = {
            "title": ap["title"],
            "url": ap["url"],
            "current_version": ap["current_version"],
            "last_update": ap["last_update"],
            "appId": ap["appId"]
        }

        context.bot_data["editing"] = True

    adding = False if "editing" in context.bot_data or (
            update.callback_query and update.callback_query.data.startswith("edit_app_from_check")
    ) else True

    if update.callback_query and (update.callback_query.data == "app_name_from_link_correct" or
                                  update.callback_query.data.startswith("interval_incorrect") or
                                  update.callback_query.data == "confirm_app_to_edit" or
                                  update.callback_query.data.startswith("edit_app_from_")):

        # inizio procedura di settaggio
        text = ("🪛 <b>App Set Up</b>\n\n"
                "🔸 <u>Intervallo di Controllo</u> – L'intervallo tra due aggiornamenti\n\n"
                "❔ <b>Format</b>\nFornisci una stringa nel formato ↙\n\n"
                "➡   <code>?m?d?h?min?s</code>\n\nsostituendo i <code>?</code> con i "
                "valori corrispondenti di:\n\n"
                "\t🔹 <code>m</code> – Mesi\n"
                "\t🔹 <code>d</code> – Giorni\n"
                "\t🔹 <code>h</code> – Ore\n"
                "\t🔹 <code>min</code> – Minuti\n"
                "\t🔹 <code>s</code> – Secondi\n\n"
                "Inserisci tutti i valori corrispondenti anche se nulli.\n\n "
                "<b>Esempio</b> 🔎 – <code>0m2d0h15min0s</code>\n\n"
                "🔸 Fornisci l'intervallo che desideri.")

        context.chat_data["message_to_delete"] = update.effective_message.id

        keyboard = [
            [InlineKeyboardButton(text="⚡️ Use Defaults", callback_data="set_default_values")]
        ] if adding else [
            [InlineKeyboardButton(text="⚡️ Use Defaults", callback_data="edit_set_default_values")]
        ]

        sleep(1)

        message_id = await parse_conversation_message(context=context,
                                                      data={
                                                          "chat_id": update.effective_chat.id,
                                                          "message_id": update.effective_message.id,
                                                          "text": text,
                                                          "reply_markup": InlineKeyboardMarkup(keyboard)
                                                      })
        if message_id != update.effective_message.id:
            context.chat_data["message_to_delete"] = message_id

        return ConversationState.SET_INTERVAL

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    sleep(1)

    if update.callback_query and update.callback_query.data == "set_default_values":
        context.bot_data["apps"][str(len(context.bot_data["apps"]) + 1)] = {
            "title": context.chat_data["setting_app"]["title"],
            "url": context.chat_data["setting_app"]["url"],
            "current_version": context.chat_data["setting_app"]["current_version"],
            "last_update": context.chat_data["setting_app"]["last_update"],
            "appId": context.chat_data["setting_app"]["appId"],
            "last_check": None,
            "suspended": False,
            "check_interval": context.bot_data["settings"]["default_check_interval"],
            "send_on_check": context.bot_data["settings"]["default_send_on_check"]
        }

        del context.chat_data["setting_app"]

        return await schedule_app_check(update, context)

    else:
        if update.callback_query and update.callback_query.data == "edit_set_default_values":
            index = context.chat_data["app_index_to_edit"]
            context.bot_data["apps"][index]["check_interval"] = context.bot_data["settings"]["default_check_interval"]
            context.bot_data["apps"][index]["send_on_check"] = context.bot_data["settings"]["default_send_on_check"]
            return await schedule_app_check(update, context)

    if not update.callback_query:
        try:
            # noinspection DuplicatedCode
            months = int(update.message.text.split('m')[0])
            days = int(update.message.text.split('d')[0].split('m')[1])
            hours = int(update.message.text.split('h')[0].split('d')[1])
            minutes = int(update.message.text.split('min')[0].split('h')[1])
            seconds = int(update.message.text.split('s')[0].split('min')[1])

        except ValueError:
            text = ("❌ <b>Usa il formato indicato</b>, non aggiungere, togliere o cambiare lettere."
                    "\n\n🔎 <code>#m#d#h#min#s</code>")
            message = await context.bot.send_message(chat_id=update.effective_chat.id,
                                                     text=text, parse_mode="HTML")

            await schedule_messages_to_delete(context=context, messages={
                str(message.id): {
                    "chat_id": update.effective_chat.id,
                    "time": 3
                }
            })

            return ConversationState.SET_INTERVAL
        else:
            if "message_to_delete" in context.chat_data:
                await schedule_messages_to_delete(context=context,
                                                  messages={
                                                      int(update.effective_message.id): {
                                                          "time": 2.5,
                                                          "chat_id": update.effective_chat.id
                                                      },
                                                      int(context.chat_data["message_to_delete"]): {
                                                          "time": 2,
                                                          "chat_id": update.effective_chat.id
                                                      }
                                                  })
                del context.chat_data["message_to_delete"]

            context.chat_data["setting_app"]["check_interval"] = {
                "input": {
                    "days": days,
                    "months": months,
                    "seconds": seconds,
                    "minutes": minutes,
                    "hours": hours
                },
                "timedelta": timedelta(days=days + months * 30, seconds=seconds, minutes=minutes, hours=hours)
            }

            # noinspection DuplicatedCode
            text = (f"❓ Conferma se l'intervallo indicato è corretto.\n\n"
                    f"▫️ <code>{months}</code> mesi\n"
                    f"▫️ <code>{days}</code> giorni\n"
                    f"▫️ <code>{hours}</code> ore\n"
                    f"▫️ <code>{minutes}</code> minuti\n"
                    f"▫️ <code>{seconds}</code> secondi")

            message = await context.bot.send_message(chat_id=update.effective_chat.id,
                                                     text=text, parse_mode="HTML")

            keyboard = [
                [
                    InlineKeyboardButton(text="✅ È corretto.",
                                         callback_data="interval_correct"),
                    InlineKeyboardButton(text="❌ Non è corretto.",
                                         callback_data="interval_incorrect")
                ],
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="back_to_settings")
                ]
            ]

            await context.bot.edit_message_reply_markup(chat_id=update.effective_chat.id,
                                                        message_id=message.id,
                                                        reply_markup=InlineKeyboardMarkup(keyboard))

            if "message_to_delete" in context.chat_data:
                await delete_message(context=context, chat_id=update.effective_chat.id,
                                     message_id=context.chat_data["message_to_delete"])
                del context.chat_data["message_to_delete"]

            return ConversationState.CONFIRM_INTERVAL

    if update.callback_query and update.callback_query.data.startswith("interval_correct"):
        await delete_message(context=context,
                             chat_id=update.effective_chat.id,
                             message_id=update.effective_message.id)

        text = ("🪛 <b>App Set Up</b>\n\n"
                "🔸 <u>Send On Check</u> – Scegli se ti verrà mandato un messaggio: <b>solo quando viene trovato"
                " un aggiornamento</b> di questa app (<code>False</code>) "
                "o <b>ad ogni controllo</b> (<code>True</code>)")

        keyboard = [
            [
                InlineKeyboardButton(text="✅ True", callback_data=f"send_on_check_true"),
                InlineKeyboardButton(text="❌ False", callback_data=f"send_on_check_false")
            ]
        ]

        await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                           action=ChatAction.TYPING)
        context.job_queue.run_once(callback=job_queue.scheduled_send_message,
                                   data={
                                       "chat_id": update.effective_chat.id,
                                       "text": text,
                                       "keyboard": keyboard
                                   },
                                   when=1.5)

        return ConversationState.SEND_ON_CHECK

    if update.callback_query and update.callback_query.data.startswith("send_on_check"):
        if adding:
            context.bot_data["apps"][str(len(context.bot_data["apps"]) + 1)] = {
                "title": context.chat_data["setting_app"]['title'],
                "url": context.chat_data["setting_app"]["url"],
                "current_version": context.chat_data["setting_app"]["current_version"],
                "last_update": context.chat_data["setting_app"]["last_update"],
                "appId": context.chat_data["setting_app"]["appId"],
                "last_check": None,
                "suspended": False
            }

            ap = context.bot_data["apps"][str(len(context.bot_data["apps"]))]
        else:
            ap = context.bot_data["apps"][context.chat_data["app_index_to_edit"]]

        ap["check_interval"] = context.chat_data["setting_app"]["check_interval"]

        ap["next_check"] = (datetime.now(pytz.timezone('Europe/Rome')) +
                            context.chat_data["setting_app"]["check_interval"]["timedelta"])

        ap["send_on_check"] = True if update.callback_query.data == "send_on_check_true" else False

        bot_logger.info(f"App {ap['title']} ({ap['appId']}) Settled Successfully -> "
                        f"Interval: "
                        f"{ap['check_interval']['input']['months']}months "
                        f"{ap['check_interval']['input']['days']}days "
                        f"{ap['check_interval']['input']['hours']}hours "
                        f"{ap['check_interval']['input']['minutes']}minutes "
                        f"{ap['check_interval']['input']['seconds']}seconds – Send On Check: "
                        f"{ap['send_on_check']}")

        if "setting_app" in context.chat_data:
            del context.chat_data["setting_app"]

    return await schedule_app_check(update, context)


async def edit_app(update: Update, context: CallbackContext):
    if update.callback_query and update.callback_query.data == "edit_app":
        if "edit_message" in context.chat_data:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=context.chat_data["edit_message"])
            del context.chat_data["edit_message"]

        if len(context.bot_data["apps"]) == 0:
            text = ("✏ <b>Edit App</b>\n\n"
                    "ℹ Non hai applicazioni nell'elenco.\n\n"
                    "🔸 Scegli un'opzione.")
            keyboard = [
                [
                    InlineKeyboardButton(text="➕ Aggiungi App", callback_data="add_app"),
                    InlineKeyboardButton(text="🔙 Torna indietro", callback_data="back_to_settings_no_apps")
                ]
            ]
            await parse_conversation_message(context=context,
                                             data={
                                                              "chat_id": update.effective_chat.id,
                                                              "text": text,
                                                              "message_id": update.effective_message.message_id,
                                                              "reply_markup": InlineKeyboardMarkup(keyboard)
                                                          })
            return ConversationHandler.END

        else:
            text = ("✏ <b>Edit App</b>\n\n"
                    "🗃 <b>Elenco Applicazioni</b>\n\n")

            for ap in context.bot_data["apps"]:
                a = context.bot_data["apps"][ap]
                text += (f"  {ap}. <i>{a['title']}</i>\n"
                         f"      <u>Check Interval</u> "
                         f"<code>{a['check_interval']['input']['months']}m</code>"
                         f"<code>{a['check_interval']['input']['days']}d</code>"
                         f"<code>{a['check_interval']['input']['hours']}h</code>"
                         f"<code>{a['check_interval']['input']['minutes']}min</code>"
                         f"<code>{a['check_interval']['input']['seconds']}s</code>\n"
                         f"      <u>Send On Check</u> <code>{a['send_on_check']}</code>\n\n")

            text += "🔸 Scegli un'applicazione digitando il <u>numero corrispondente</u> o il <u>nome</u>."

            message_id = await parse_conversation_message(context, data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "message_id": update.effective_message.message_id,
                "reply_markup": None
            })

        context.chat_data["edit_message"] = message_id

        return ConversationState.EDIT_SELECT_APP

    if not update.callback_query and update.effective_message:
        if "message_to_delete" in context.chat_data:
            await schedule_messages_to_delete(context=context,
                                              messages={
                                                  int(context.chat_data["message_to_delete"]): {
                                                      "chat_id": update.effective_chat.id,
                                                      "time": 2
                                                  }
                                              })

            del context.chat_data["message_to_delete"]

        app_names = create_edit_app_list(context.bot_data)
        message = update.effective_message

        if not message.text.strip().isnumeric():
            if (inpt := await input_name_fixer(message.text)) not in app_names:
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
                sleep(1)
                message_id = await parse_conversation_message(context=context,
                                                              data={
                                                                  "chat_id": update.effective_chat.id,
                                                                  "text": "🔴 <b>App Not Found</b>\n\n"
                                                                          "🔸 Scegli un'applicazione dell'elenco.",
                                                                  "message_id": -1,
                                                                  "reply_markup": False
                                                              })

                await schedule_messages_to_delete(context=context,
                                                  messages={
                                                      str(update.effective_message.id): {
                                                          "time": 2.5,
                                                          "chat_id": update.effective_chat.id
                                                      },
                                                      str(message_id): {
                                                          "time": 5,
                                                          "chat_id": update.effective_chat.id
                                                      }
                                                  })

                return ConversationState.EDIT_SELECT_APP

            context.chat_data["app_index_to_edit"] = await get_app_from_string(inpt, context=context)

        if (inpt := message.text.strip()).isnumeric():
            if int(message.text.strip()) > len(app_names) or int(message.text.strip()) < 0:
                text = "🔴 <b>Invalid Index</b>\n\n🔸 Fornisci un indice valido."

                message_id = await parse_conversation_message(context=context,
                                                              data={
                                                                  "chat_id": update.effective_chat.id,
                                                                  "text": text,
                                                                  "message_id": -1,
                                                                  "reply_markup": False
                                                              })

                await schedule_messages_to_delete(context=context,
                                                  messages={
                                                      str(update.effective_message.id): {
                                                          "time": 2.5,
                                                          "chat_id": update.effective_chat.id
                                                      },
                                                      str(message_id): {
                                                          "time": 5,
                                                          "chat_id": update.effective_chat.id
                                                      }
                                                  })

                return ConversationState.EDIT_SELECT_APP

            context.chat_data["app_index_to_edit"] = inpt

        await schedule_messages_to_delete(context=context,
                                          messages={
                                              update.effective_message.id: {
                                                  "chat_id": update.effective_chat.id,
                                                  "time": 2
                                              }
                                          })

        text = (f"🔵 <b>App Found</b>\n\n"
                f"▶️ <code>"
                f"{context.bot_data['apps'][str(context.chat_data['app_index_to_edit'])]['title']}"
                f"</code>\n\n"
                f"🔸 È l'applicazione che vuoi modificare?")

        keyboard = [
            [
                InlineKeyboardButton(text="⚪️ Si", callback_data="confirm_app_to_edit"),
                InlineKeyboardButton(text="⚫️ No", callback_data="edit_app")
            ]
        ]

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        sleep(1)
        await context.bot.send_message(chat_id=update.effective_chat.id,
                                       text=text,
                                       reply_markup=InlineKeyboardMarkup(keyboard),
                                       parse_mode='HTML')

        return ConversationState.EDIT_CONFIRM_APP


async def remove_app(update: Update, context: CallbackContext):
    if update.callback_query and update.callback_query.data == "delete_app":
        if "delete_app_message" in context.chat_data:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=context.chat_data["delete_app_message"])
            del context.chat_data["delete_app_message"]

        if len(context.bot_data["apps"]) == 0:
            context.bot_data["removing"] = True
            text = ("➖ <b>Remove App</b>\n\n"
                    "ℹ Non hai applicazioni nell'elenco.\n\n"
                    "🔸 Scegli un'opzione.")
            keyboard = [
                [
                    InlineKeyboardButton(text="➕ Aggiungi App", callback_data="add_app"),
                    InlineKeyboardButton(text="🔙 Torna indietro", callback_data="back_to_settings_no_apps")
                ]
            ]

            await parse_conversation_message(context=context, data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "message_id": update.effective_message.id,
                "reply_markup": InlineKeyboardMarkup(keyboard)
            })

            return ConversationHandler.END

        else:
            text = ("➖ <b>Remove App</b>\n\n"
                    "🗃 <b>Elenco Applicazioni</b>\n\n")

            for ap in context.bot_data["apps"]:
                a = context.bot_data["apps"][ap]
                text += f"  {ap}. <i>{a['title']}</i>\n"

            text += "\n🔸 Scegli un'applicazione da rimuovere indicando l'<u>indice</u> o il <u>nome</u>."
            message_id = await parse_conversation_message(context=context,
                                                          data={
                                                              "chat_id": update.effective_chat.id,
                                                              "text": text,
                                                              "message_id": update.effective_message.id,
                                                              "reply_markup": None
                                                          })

            context.chat_data["delete_app_message"] = message_id

        return ConversationState.DELETE_APP_SELECT

    if not update.callback_query:
        if "message_to_delete" in context.chat_data:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=context.chat_data["message_to_delete"])
            del context.chat_data["message_to_delete"]

        if (not update.message.text.strip().isnumeric() and
            (index := await get_app_from_string(update.message.text.strip().lower(), context))) or (
                (index := update.message.text.strip()).isnumeric() and 0 < int(index) <= len(context.bot_data["apps"])):
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=update.effective_message.id)
            ap = context.bot_data["apps"][index]
            suspended = ap["suspended"]
            context.chat_data["app_index_to_delete"] = index
            text = (f"🔵 <b>App Found</b>\n\n"
                    f"🔸 App Name: <code>{ap['title']}</code>\n\n"
                    f"🔹 Vuoi rimuovere questa applicazione?")

            keyboard = [
                [
                    InlineKeyboardButton(text="🚮 Si", callback_data="confirm_remove"),
                    InlineKeyboardButton(text="🚯 No", callback_data="delete_app")
                ],
                [
                    InlineKeyboardButton(text="⏸ Sospendi", callback_data=f"suspend_from_remove {index}")
                ]
            ] if not suspended else [
                [
                    InlineKeyboardButton(text="🚮 Si", callback_data="confirm_remove"),
                    InlineKeyboardButton(text="🚯 No", callback_data="delete_app")
                ]
            ]

            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            sleep(1)
            message = await context.bot.send_message(chat_id=update.effective_chat.id,
                                                     text=text,
                                                     reply_markup=InlineKeyboardMarkup(keyboard),
                                                     parse_mode='HTML')
            context.chat_data["message_to_delete"] = message.id

            return ConversationState.DELETE_APP_CONFIRM

        else:
            if (not (message := update.effective_message.text.strip().lower()).isnumeric() and
                    not await get_app_from_string(message, context)):
                text = ("🔴 <b>App Not Found</b>\n\n"
                        "🔸 Scegli un'applicazione da rimuovere indicando l'<u>indice</u> o il <u>nome</u>.")

                message_id = await parse_conversation_message(context=context,
                                                              data={
                                                                  "chat_id": update.effective_chat.id,
                                                                  "text": text,
                                                                  "message_id": -1,
                                                                  "reply_markup": None
                                                              })

                context.chat_data["message_to_delete"] = message_id

                return ConversationState.DELETE_APP_SELECT

            if ((message := update.effective_message.text.strip().lower()).isnumeric()
                    and int(message) < 0 or int(message) > len(context.bot_data["apps"])):
                text = "❌ Inserisci un indice valido"

                message_id = await parse_conversation_message(context=context,
                                                              data={
                                                                  "chat_id": update.effective_chat.id,
                                                                  "text": text,
                                                                  "message_id": -1,
                                                                  "reply_markup": None
                                                              })

                context.chat_data["message_to_delete"] = message_id

                return ConversationState.DELETE_APP_SELECT

    if update.callback_query and update.callback_query.data == "confirm_remove":
        if "delete_app_message" in context.chat_data:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=context.chat_data["delete_app_message"])
            del context.chat_data["delete_app_message"]
        if "message_to_delete" in context.chat_data:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=context.chat_data["message_to_delete"])
            del context.chat_data["message_to_delete"]

        app_name = context.bot_data["apps"][context.chat_data["app_index_to_delete"]]['title']
        app_id = context.bot_data["apps"][context.chat_data["app_index_to_delete"]]["appId"]

        for j in context.job_queue.get_jobs_by_name(app_name):
            j.schedule_removal()

        for ap in context.bot_data["apps"]:
            if int(ap) < int(context.chat_data["app_index_to_delete"]):
                continue
            elif int(ap) < len(context.bot_data["apps"]):
                context.bot_data["apps"][ap] = context.bot_data["apps"][str(int(ap) + 1)]
        del context.bot_data["apps"][str(len(context.bot_data["apps"]))]
        del context.chat_data["app_index_to_delete"]

        bot_logger.info(f"App {app_name} ({app_id}) deleted successfully")

        text = ("✔ <b>App Removed Successfully</b>\n\n"
                "🔸 Scegli un'opzione.")
        keyboard = [
            [
                InlineKeyboardButton(text="➖ Rimuovi Altra App", callback_data="delete_app"),
                InlineKeyboardButton(text="🔙 Torna indietro", callback_data="back_to_settings")
            ]
        ] if len(context.bot_data["apps"]) > 0 else [
            [
                InlineKeyboardButton(text="🔙 Torna indietro", callback_data="back_to_settings")
            ]
        ]

        await parse_conversation_message(context=context, data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "message_id": update.effective_message.id,
            "reply_markup": InlineKeyboardMarkup(keyboard)
        })

        return ConversationHandler.END


async def suspend_app(update: Update, context: CallbackContext):
    if update.callback_query:
        if (update.callback_query.data.startswith("suspend_app") or
                update.callback_query.data.startswith("suspend_from_remove")):
            if "delete_app_message" in context.chat_data:
                await delete_message(context=context, chat_id=update.effective_chat.id,
                                     message_id=context.chat_data["delete_app_message"])
                del context.chat_data["delete_app_message"]

            li = update.callback_query.data.split(" ")
            context.bot_data["apps"][str(li[1])]["suspended"] = True

            text = (f"⏸ <b>Sospendi Controlli App</b>\n\n"
                    f"🔹  App <code>{context.bot_data['apps'][li[1]]['title']}</code> "
                    f"sospesa: non riceverai più aggiornamenti.\n\n"
                    f"🔸 Puoi riattivarla dalle impostazioni.")

            keyboard = [
                [InlineKeyboardButton(text="🗑 Chiudi", callback_data=f"delete_message {update.effective_message.id}")]
            ] if update.callback_query.data.startswith("suspend_app") else [
                [InlineKeyboardButton(text="🔙 Torna Indietro",
                                      callback_data="back_to_settings_settled")]
            ]

            await parse_conversation_message(context=context, data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "message_id": update.effective_message.id,
                "reply_markup": InlineKeyboardMarkup(keyboard)
            })

            return (ConversationState.UNSUSPEND_APP if update.callback_query.data.startswith("suspend_app")
                    else ConversationHandler.END)

        elif update.callback_query.data == "unsuspend_app":
            text = ("⏯ <b>Riattiva Controlli App</b>\n\n"
                    "🔸 Dalla tastiera sotto, seleziona il nome dell'app che vuoi riattivare.")

            keyboard = []

            for ap in (a := context.bot_data["apps"]):
                if a[ap]["suspended"]:
                    keyboard.append([InlineKeyboardButton(text=f"{a[ap]['title']}",
                                                          callback_data=f"unsuspend_app {ap}")])

            keyboard.append([InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="back_to_settings")])

            await parse_conversation_message(context=context, data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "message_id": update.effective_message.id,
                "reply_markup": InlineKeyboardMarkup(keyboard)
            })

            return ConversationState.UNSUSPEND_APP

        if update.callback_query.data.startswith("unsuspend_app"):
            index = update.callback_query.data.split(" ")[1]
            (ap := context.bot_data["apps"][index])["suspended"] = False
            text = ("⏯ <b>Riattiva Controlli App</b>\n\n"
                    f"ℹ Controlli app <code>{ap['title']}</code> riattivati\n\n"
                    f"🔸 Scegli un'opzione.")

            suspended = False

            for ap in (a := context.bot_data["apps"]):
                if a[ap]["suspended"]:
                    suspended = True
                    break

            keyboard = [
                [
                    InlineKeyboardButton(text="⏯ Riattiva Altra App", callback_data="unsuspend_app"),
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="back_to_settings")
                ]
            ] if suspended else [
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="back_to_settings")
                ]
            ]

            await parse_conversation_message(context=context, data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "message_id": update.effective_message.id,
                "reply_markup": InlineKeyboardMarkup(keyboard)
            })

            return ConversationState.MANAGE_APPS


async def see_app_settings(update: Update, context: CallbackContext):
    if (index := update.callback_query.data.split(" ")[1]) in context.bot_data["apps"]:
        ap = context.bot_data["apps"][index]

        text = (f"🔍 <b>App Settings</b>\n\n"
                f"  🔹App Name: <code>{ap['title']}</code>\n"
                f"  🔹Check Interval: "
                f"<code>{ap['check_interval']['input']['months']}m</code>"
                f"<code>{ap['check_interval']['input']['days']}d</code>"
                f"<code>{ap['check_interval']['input']['hours']}h</code>"
                f"<code>{ap['check_interval']['input']['minutes']}min</code>"
                f"<code>{ap['check_interval']['input']['seconds']}s</code>\n"
                f"  🔹Send On Check: <code>{ap['send_on_check']}</code>\n\n"
                f"🔸 Scegli un'opzione.")

        message = await context.bot.send_message(chat_id=update.effective_chat.id,
                                                 text=text,
                                                 parse_mode='HTML')

        keyboard = [
            [
                InlineKeyboardButton(text="✏ Modifica", callback_data=f"edit_app_from_check {index}"),
                InlineKeyboardButton(text="🗑 Chiudi", callback_data=f"delete_message {message.id}")
            ]
        ]

        await context.bot.edit_message_reply_markup(chat_id=update.effective_chat.id,
                                                    message_id=message.id,
                                                    reply_markup=InlineKeyboardMarkup(keyboard))


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


async def schedule_messages_to_delete(context: CallbackContext, messages: dict):
    for message in messages:
        await check_dict_keys(messages[message], ["time", "chat_id"])
        time, chat_id = messages[message]["time"], messages[message]["chat_id"]

        context.job_queue.run_once(callback=job_queue.scheduled_delete_message,
                                   data={
                                       "message_id": int(message),
                                       "chat_id": chat_id
                                   },
                                   when=time)


async def get_app_details_with_link(link: str):
    res = requests.get(link)
    if res.status_code != 200:
        settings_logger.warning(f"Not able to gather link {link}: {res.reason}")
        return None
    try:
        id_app = link.split("id=")[1].split('&')[0]
        app_details = app(app_id=id_app)
    except IndexError as e:
        return e
    except NotFoundError as e:
        return e
    else:
        return app_details


async def delete_extemporary_message(update: Update, context: CallbackContext):
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id,
                                         message_id=int(update.callback_query.data.split(" ")[1]))
    except telegram.error.BadRequest as e:
        bot_logger.info(f"Not able to delete message: {e}")
        pass


async def get_app_from_string(string: str, context: CallbackContext):
    whitelist = set('abcdefghijklmnopqrstuvwxyz ')
    for a in context.bot_data["apps"]:
        if (string == ''.join(filter(whitelist.__contains__, context.bot_data["apps"][a]['title'].lower())).
                replace("  ", " ")):
            return a
    return None


async def input_name_fixer(string: str):
    whitelist = set('abcdefghijklmnopqrstuvwxyz ')
    return ''.join(filter(whitelist.__contains__, string.lower())).replace("  ", " ")


async def send_menage_apps_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("🗂 <b>Gestione Applicazioni</b>\n\n"
            "🔹Da questo menù, puoi visualizzare e gestire le applicazioni.")

    keyboard = [
        [
            InlineKeyboardButton(text="✏️ Modifica", callback_data="edit_app"),
            InlineKeyboardButton(text="➕ Aggiungi", callback_data="add_app"),
            InlineKeyboardButton(text="➖ Rimuovi", callback_data="delete_app")
        ],
        [
            InlineKeyboardButton(text="📄 Lista App", callback_data="list_apps")
        ],
        [
            InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="settings")
        ]
    ]

    for ap in (a := context.bot_data["apps"]):
        if a[ap]["suspended"]:
            keyboard[1].append(InlineKeyboardButton(text="⏯ Riattiva App", callback_data="unsuspend_app"))
            break

    await parse_conversation_message(context=context,
                                     data={
                                         "chat_id": update.effective_chat.id,
                                         "message_id": update.effective_message.message_id,
                                         "text": text,
                                         "reply_markup": InlineKeyboardMarkup(keyboard)}
                                     )

    if "edit_message" in context.chat_data:
        del context.chat_data["edit_message"]

    if "delete_app_message" in context.chat_data:
        del context.chat_data["delete_app_message"]

    if "editing" in context.bot_data:
        del context.bot_data["editing"]
    if "adding" in context.bot_data:
        del context.bot_data["adding"]
    if "removing" in context.bot_data:
        del context.bot_data["removing"]

    if update.callback_query and (update.callback_query.data == "back_to_settings_settled" or
                                  update.callback_query.data == "back_to_settings_no_apps"):
        return

    return ConversationState.MANAGE_APPS


def create_edit_app_list(bot_data: dict) -> list:
    whitelist = set('abcdefghijklmnopqrstuvwxyz ')
    app_names = []
    if "apps" in bot_data:
        for a in bot_data["apps"]:
            app_names.append(''.join(filter(whitelist.__contains__, str(bot_data["apps"][a]['title']).lower())).
                             replace("  ", " "))

    return app_names or []
