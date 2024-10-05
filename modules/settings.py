import os
import re
import shutil
from logging import handlers
from time import sleep

import pytz
import requests
from telegram import MessageEntity
from telegram.constants import InlineKeyboardButtonLimit

from decorators import send_action
from utils import *
from job_queue import reschedule

settings_logger = logging.getLogger("settings_logger")
settings_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = handlers.RotatingFileHandler(filename="logs/settings.log",
                                            maxBytes=1024 * 1024 * 10, backupCount=1)
file_handler.setFormatter(formatter)
settings_logger.addHandler(file_handler)

bot_logger = logging.getLogger("bot_logger")


@send_action(ChatAction.TYPING)
async def set_defaults(update: Update, context: CallbackContext):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    if update.callback_query and update.callback_query.data == "edit_default_settings":
        await delete_message(context=context, chat_id=update.effective_chat.id,
                             message_id=update.effective_message.message_id)
        inp = context.chat_data["settings"]["default_check_interval"]["input"]
        text = (f"🔧 <b>Impostazioni di Default</b>\n\n"
                f"  🔹 <u>Default Interval</u> "
                f"<code>{inp['months']}m{inp['days']}d{inp['hours']}h{inp['minutes']}min{inp['seconds']}s</code>\n"
                f"  🔹 <u>Default Send On Check</u> "
                f"<code>{context.chat_data['settings']['default_send_on_check']}</code>\n")
        if await is_owner_or_admin(context, update.effective_user.id):
            text += "  🔹<u>Default Permissions</u>\n"

            for permissions in (p := context.chat_data["permissions"]):
                text += (f"     🔸<i>{' '.join(w.capitalize() for w in permissions.split("_"))}</i> – "
                         f"<code>{p[permissions]}</code>\n")

        text += "\n 🔸 Confermi di voler cambiare queste impostazioni?"

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
            context.chat_data["settings"]["default_check_interval"]["input"] = {
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
            keyboard = [
                [
                    InlineKeyboardButton(text="✅ È corretto", callback_data="interval_correct {}"),
                    InlineKeyboardButton(text="❌ Non è corretto", callback_data="interval_incorrect {}")
                ]
            ]

            await send_message_with_typing_action(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "keyboard": keyboard,
                "close_button": [[1, 1], [1, 2]]
            }, context=context)

            return 2

    if update.callback_query and update.callback_query.data.startswith("interval_correct"):
        i = context.chat_data["settings"]["default_check_interval"]["input"]
        bot_logger.info(f"Default Interval -> Setting Completed: "
                        f"{i['months']}m{i['days']}d{i['hours']}h{i['minutes']}min{i['seconds']}s")

        if len(li := update.callback_query.data.split(" ")) > 1:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=int(li[1]))

        text = ("🔧 <b>Setting Default Values</b>\n\n"
                "➡ <u>Default Send On Check</u> – Scegli se, di default, ti verrà mandato un messaggio <b>solo "
                "quando viene trovato un aggiornamento</b> (<code>False</code>) o <b>ad ogni controllo</b>"
                " (<code>True</code>)."
                "\n\n🔹Potrai cambiare questa impostazione in seguito.")

        keyboard = [
            [
                InlineKeyboardButton(text="✅ True", callback_data="default_send_on_check_true {}"),
                InlineKeyboardButton(text="❌ False", callback_data="default_send_on_check_false {}")
            ]
        ]

        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "close_button": [[1, 1], [1, 2]]
        }, context=context)

        return 3

    if update.callback_query and update.callback_query.data.startswith("default_send_on_check"):
        if len(li := update.callback_query.data.split(" ")) > 1:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=int(li[1]))

        if update.callback_query.data.startswith("default_send_on_check_true"):
            context.chat_data["settings"]["default_send_on_check"] = True
        else:
            context.chat_data["settings"]["default_send_on_check"] = False

        bot_logger.info(f"Default Send On Check -> Setting Completed: "
                        f"{context.chat_data['settings']['default_send_on_check']}")
        if await is_owner_or_admin(context, update.effective_user.id):
            text = "🔐 <b>Setting Default Permissions</b>\n\n"

            context.chat_data["temp"]["new_permissions"] = {}

            np = context.chat_data["temp"]["new_permissions"]

            for permission in context.chat_data["permissions"]:
                if permission != "can_manage_users":
                    np[permission] = None

            for permission in np:
                if permission != "can_manage_users":
                    text += (f"🔹 <b>{' '.join(w.capitalize() for w in permission.split("_"))}</b> "
                             f"– {context.bot_data['settings']['permissions'][permission]['permission_set_text']}")
                if not context.chat_data["first_boot"]:
                    text += f"\n\n⚠ Se torni indietro adesso, i permessi di default non verranno cambiati."

                keyboard = [
                    [
                        InlineKeyboardButton(text="✅ True", callback_data="set_default_permission_true " + permission),
                        InlineKeyboardButton(text="❌ False", callback_data="set_default_permission_false " + permission)
                    ]
                ]

                if not context.chat_data["first_boot"]:
                    keyboard.append([InlineKeyboardButton(
                        text="🔙 Torna indietro",
                        callback_data="default_settings_completed")])
                await send_message_with_typing_action(data={
                    "chat_id": update.effective_chat.id,
                    "text": text,
                    "keyboard": keyboard,
                    "message_id": update.effective_message.id
                }, context=context)
                return 4
        else:
            i = context.chat_data["settings"]["default_check_interval"]["input"]
            text = (f"☑️ <b>Setting Completed</b>\n\n"
                    f"🔸 <u>Default Interval</u> – "
                    f"<code>{i['months']}m"
                    f"{i['days']}d"
                    f"{i['hours']}h"
                    f"{i['minutes']}min"
                    f"{i['seconds']}s</code>\n"
                    f"🔸 <u>Default Send On Check</u> – "
                    f"<code>{str(context.chat_data['settings']['default_send_on_check'])}"
                    f"</code>\n")
            keyboard = [
                [InlineKeyboardButton(text="⏭ Procedi", callback_data="default_setting_finished {}")]
            ]
            await send_message_with_typing_action(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "keyboard": keyboard,
                "message_id": update.effective_message.id,
                "close_button": [1, 1]
            }, context=context)

            if context.chat_data["first_boot"]:
                context.chat_data["first_boot"] = False
            return ConversationHandler.END


    if update.callback_query and (update.callback_query.data.startswith("set_default_permission")
                                  or update.callback_query.data == "default_settings_completed"):
        i = context.chat_data["settings"]["default_check_interval"]["input"]
        if "true" in update.callback_query.data:
            context.chat_data["temp"]["new_permissions"][update.callback_query.data.split(" ")[1]] = True
        elif "false" in update.callback_query.data:
            context.chat_data["temp"]["new_permissions"][update.callback_query.data.split(" ")[1]] = False
        
        if update.callback_query.data != "default_settings_completed":
            for permission in (np := context.chat_data["temp"]["new_permissions"]):
                if np[permission] is None:
                    text = ("🔐 <b>Setting Default Permissions</b>\n\n"
                            f"🔹 <b>{' '.join(w.capitalize() for w in permission.split("_"))}</b> "
                            f"– {np[permission]['permission_set_text']}\n\n"
                            f"⚠ Se torni indietro adesso, i permessi di default non verranno cambiati.")
                    keyboard = [
                        [
                            InlineKeyboardButton(text="✅ True",
                                                 callback_data="set_default_permission_true " + permission),
                            InlineKeyboardButton(text="❌ False",
                                                 callback_data="set_default_permission_false " + permission)
                        ],
                        [
                            InlineKeyboardButton(text="🔙 Torna indietro", callback_data="default_settings_completed")
                        ]
                    ]
                    await send_message_with_typing_action(data={
                        "chat_id": update.effective_chat.id,
                        "text": text,
                        "keyboard": keyboard,
                        "message_id": update.effective_message.id
                    }, context=context)
                    return 4

        if update.callback_query.data != "default_settings_completed":
            context.chat_data["permissions"] = context.chat_data["temp"]["new_permissions"]
            context.chat_data["permissions"]["can_manage_users"] = False
            
        del context.chat_data["temp"]["new_permissions"]

        bot_logger.info(f"Default Setting Completed.")

        text = (f"☑️ <b>Setting Completed</b>\n\n"
                f"🔸 <u>Default Interval</u> – "
                f"<code>{i['months']}m"
                f"{i['days']}d"
                f"{i['hours']}h"
                f"{i['minutes']}min"
                f"{i['seconds']}s</code>\n"
                f"🔸 <u>Default Send On Check</u> – "
                f"<code>{str(context.chat_data['settings']['default_send_on_check'])}"
                f"</code>\n")
        if await is_owner_or_admin(context, update.effective_user.id):
            text += "🔸 <u>Default Permissions</u>\n"

            for permissions in (p := context.chat_data["permissions"]):
                text += (f"     🔹<i>{' '.join(w.capitalize() for w in permissions.split("_"))}</i> – "
                         f"<code>{p[permissions]}</code>\n")
        
        text += "\n"

        keyboard = [
            [InlineKeyboardButton(text="⏭ Procedi", callback_data="default_setting_finished {}")]
        ]

        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id,
            "close_button": [1, 1]
        }, context=context)

        if context.chat_data["first_boot"]:
            context.chat_data["first_boot"] = False
        return ConversationHandler.END


async def change_settings(update: Update, context: CallbackContext):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    text = ("⚙ <b>Settings Panel</b>\n\n🔹Da qui puoi cambiare le impostazioni di default e gestire le applicazioni "
            "monitorate.\n\n🔸 Scegli un'opzione.")

    keyboard = await get_functions_keyboard(update, context)

    await parse_conversation_message(context=context,
                                     data={
                                         "chat_id": update.effective_chat.id,
                                         "message_id": update.effective_message.message_id,
                                         "text": text,
                                         "reply_markup": InlineKeyboardMarkup(keyboard)}
                                     )

    return (ConversationState.CHANGE_SETTINGS if (update.callback_query.data != "cancel_edit_settings"
                                                  and update.callback_query.data != "from_backup_restore"
                                                  and update.callback_query.data != "from_user_managing")
            else ConversationHandler.END)


async def menage_apps(update: Update, context: CallbackContext):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

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

            if await is_there_suspended_app(context.chat_data["apps"]):
                keyboard[1].append(InlineKeyboardButton(text="⏯ Riattiva App", callback_data="unsuspend_app"))

            await parse_conversation_message(context=context,
                                             data={
                                                 "chat_id": update.effective_chat.id,
                                                 "message_id": update.effective_message.message_id,
                                                 "text": text,
                                                 "reply_markup": InlineKeyboardMarkup(keyboard)}
                                             )

            return ConversationState.MANAGE_APPS

        if update.callback_query.data == "list_apps" or update.callback_query.data == "go_back_to_list_apps":
            if len(context.chat_data["apps"]) == 0:
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
                for a in context.chat_data["apps"]:
                    text += (f"  {a}. {context.chat_data['apps'][a]['app_name']}\n"
                             f"    <code>Interval</code> {context.chat_data['apps'][a]['check_interval']}\n"
                             f"    <code>Send On Check</code> {context.chat_data['apps'][a]['send_on_check']}\n"
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


async def backup_and_restore(update: Update, context: CallbackContext):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    if not await is_allowed_user_function(user_id=update.effective_chat.id,
                                    users=context.bot_data["users"],
                                    permission='can_manage_backups'):
        await send_not_allowed_function_message(update, context)
        return

    cd = context.chat_data
    removed = False
    text = "💾 <b>Backup & Ripristino</b>\n\n"
    if update.callback_query and update.callback_query.data == "backup_restore":
        new_backups = await check_for_backups(update.effective_chat.id)

        if len(new_backups) < len(cd["backups"]):
            removed = True

        cd["backups"] = new_backups

        if len(cd["backups"]) == 0:
            text += "ℹ️ Non hai nessun backup.\n\n"
            if removed:
                text += "⚠ Alcuni file di backup non sono più presenti. @Linxay potrebbe averli rimossi\n\n"
            text += "🔸 Scegli un'opzione."
        else:
            text += f"ℹ️ Hai {len(cd['backups'])} file(s) di backup.\n\n🔍 <b>Informazioni</b>\n\n"
            for backup in cd["backups"]:
                b = cd["backups"][backup]
                text += f"      {backup}. <code>{b["file_name"]}</code>\n"
            if removed:
                text += "\n⚠ Alcuni file di backup non sono più presenti. @Linxay potrebbe averli rimossi\n"
            text += ("\n🔸 Per <b>visualizzare</b>, <b>ripristinare</b> o <b>cancellare</b> un backup, "
                     "scrivi l'indice corrispondente. Altrimenti, scegli un'opzione.")

        keyboard = [
            [
                InlineKeyboardButton(text="➕ Crea Backup", callback_data="create_backup")
            ],
            [
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="from_backup_restore")
            ]
        ]

        if await is_owner_or_admin(context, update.effective_chat.id):
            keyboard.insert(1, [InlineKeyboardButton(
                text=f"🔢 Cambia Backup Massimi ({context.bot_data['settings']['max_backups']})",
                callback_data="change_max_backups")
            ])

        if removed:
            keyboard.insert(1, InlineKeyboardButton(text="🆘 Contatta @Linxay", url="https://t.me/Linxay"))

        message_id = await parse_conversation_message(context=context, data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "reply_markup": InlineKeyboardMarkup(keyboard),
            "message_id": update.effective_message.id
        })

        cd["message_to_delete"] = message_id

        return ConversationState.BACKUP_MENU

    if update.message:
        if "max_backups" in cd["temp"]:
            if not (new := update.effective_message.text).isnumeric() or int(new) <= 0:
                text += "❌ Specifica un numero positivo"
                keyboard = [
                    [
                        InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="backup_restore")
                    ]
                ]
                await send_message_with_typing_action(data={
                    "chat_id": update.effective_chat.id,
                    "text": text,
                    "keyboard": keyboard,
                    "message_id": update.effective_message.id
                }, context=context)
                return ConversationState.EDIT_MAX_BACKUPS
            context.bot_data["settings"]["max_backups"] = int(new)

            text += "✅ Numero backups modificato correttamente\n\n"

        inp = int(''.join(filter(set('0123456789').__contains__, update.message.text)))
        if inp > (max_index := len(cd["backups"])):
            text = f"❌ Fornisci un indice valido, compreso tra 1 e {max_index}"
            message = await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
            await schedule_messages_to_delete(context=context, messages={
                message.id: {
                    "chat_id": update.effective_chat.id,
                    "time": 1.5
                },
                update.effective_message.id: {
                    "chat_id": update.effective_chat.id,
                    "time": 2.5
                }
            })
            return ConversationState.BACKUP_MENU

        if "message_to_delete" in cd:
            await delete_message(context=context, chat_id=update.effective_chat.id, message_id=cd["message_to_delete"])
            del cd["message_to_delete"]

        fl = cd["backups"][inp]
        path = "backups/" + str(update.effective_chat.id) + "/" + fl["file_name"]
        if not os.path.isfile(path):
            text += ("❌ Il file non è stato trovato. È possibile che @Linxay lo abbia eliminato. "
                     "Il file verrà tolto dall'elenco.\n\n"
                     "🔸 Scegli un'opzione")
            keyboard = [
                [
                    InlineKeyboardButton(text="🆘 Contatta @Linxay", url="https://t.me/Linxay"),
                    InlineKeyboardButton(text="🔙 Torna indietro", callback_data="backup_restore")
                ]
            ]
            await send_message_with_typing_action(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "keyboard": keyboard,
                "message_id": update.effective_message.id
            }, context=context)
            del cd["backups"][inp]
            return ConversationState.BACKUP_MENU

        text += (f"📁 File Name: <code>{fl['file_name']}</code>\n\n"
                 f"🔸 Scegli un'opzione")
        keyboard = [
            [
                InlineKeyboardButton(text="🗄 Scarica il file",
                                     callback_data="download_backup_file " + path),
                InlineKeyboardButton(text="♻️ Cancella il backup", callback_data="delete_backup " + path)
            ],
            [
                InlineKeyboardButton(text="🔄️ Ripristina Backup", callback_data="restore_backup " + path)
            ],
            [
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="backup_restore")
            ]
        ]
        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id
        }, context=context)

        return ConversationState.BACKUP_SELECTED

    if update.callback_query and update.callback_query.data == "create_backup":
        if not os.path.isdir(user_folder := ("backups/" + str(update.effective_user.id))):
            os.makedirs(user_folder)
        if len(cd["backups"]) >= context.bot_data["settings"]["max_backups"]:
            text += "⚠ Hai raggiunto il numero massimo di file di backup. Prima rimuovine uno."
            keyboard = [
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="backup_restore")
                ]
            ]
            await send_message_with_typing_action(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "keyboard": keyboard,
                "message_id": update.effective_message.id
            }, context=context)
            return
        filename = datetime.now(pytz.timezone("Europe/Rome")).strftime("%d_%m_%Y_%H_%M_%S") + ".yml"
        cd["backups"][len(cd["backups"]) + 1] = {}
        cd["backups"][len(cd["backups"])]["file_name"] = filename
        cd["backups"][len(cd["backups"])]["backup_time"] = datetime.now(pytz.timezone("Europe/Rome"))

        if not await yaml_dict_dumper(cd, path := (user_folder + "/" + filename)):
            del cd["backups"][len(cd["backups"])]

            text += ("❌ <u>Il file di backup non è stato creato a cause di un errore</u>\n\n"
                     "Contatta @AleLntr per assitenza."
                     "🔸 Scegli un'opzione.")
            keyboard = [
                [
                    InlineKeyboardButton(text="🆘 Contatta @AleLntr", url="https://t.me/AleLntr")
                ],
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="back_to_main_menu")
                ]
            ]

            await send_message_with_typing_action(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "keyboard": keyboard,
                "message_id": update.effective_message.id
            }, context=context)

            return ConversationState.CHANGE_SETTINGS
        else:
            text += ("☑️ <i>Backup creato con successo</i>\n\n"
                     f"📂 File: <code>{filename}</code>\n\n"
                     "🔸 Scegli un'opzione")
            keyboard = [
                [
                    InlineKeyboardButton(text="🗄 Scarica il file",
                                         callback_data="download_backup_file " + path),
                    InlineKeyboardButton(text="📄 Lista backups", callback_data="backup_restore")
                ],
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="from_backup_restore")
                ]
            ]

            await send_message_with_typing_action(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "keyboard": keyboard,
                "message_id": update.effective_message.id
            }, context=context)

            return ConversationState.BACKUP_COMPLETED

    if update.callback_query and update.callback_query.data.startswith("download_backup_file"):
        keyboard = [
            [
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="backup_restore")
            ]
        ]
        text = ("🗃 <b>Ecco il file</b>\n\n"
                "⚠️ @Linxay può vedere e gestire questo file in ogni momento.\n\n"
                "🔸 Scegli un'opzione")

        path = update.callback_query.data.split(" ")[1]

        await send_message_with_typing_action(data={
            "file_path": path,
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id
        }, context=context, action=ChatAction.UPLOAD_DOCUMENT)

        return ConversationState.CHANGE_SETTINGS

    if update.callback_query and update.callback_query.data.startswith("delete_backup"):
        path = update.callback_query.data.split(" ")[1]
        file_name = path.split("/")[-1]
        text += (f"📁 File Name: <code>{file_name}</code>\n\n"
                 "❓ Confermi la rimozione di questo file? Se confermi, non potrai più recuperarlo.")

        keyboard = [
            [
                InlineKeyboardButton(text="🚮 Elimina", callback_data="confirm_delete_backup " + path)
            ],
            [
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="backup_restore")
            ]
        ]

        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id
        }, context=context)

        return ConversationState.BACKUP_DELETE

    if update.callback_query and update.callback_query.data.startswith("confirm_delete_backup"):
        path = update.callback_query.data.split(" ")[1]
        filename = path.split("/")[-1]
        keyboard = [
            [
                InlineKeyboardButton(text="🆘 Contatta @Linxay", url="https://t.me/Linxay"),
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="backup_restore")
            ]
        ]
        try:
            os.remove(path)
            for k, v in cd["backups"].items():
                if v["file_name"] == filename:
                    for k1, v1 in cd["backups"].items():
                        if k1 >= k:
                            cd["backups"][k] = cd["backups"][k1]
                            k += 1
                    del cd["backups"][len(cd["backups"])]
                    break
        except FileNotFoundError:
            text += ("❌ Il file non è stato trovato. È possibile che @Linxay lo abbia già rimosso.\n\n"
                     "🔸 Scegli un'opzione")
        except OSError as e:
            settings_logger.error(f"OSError: {e}; non è possibile cancellare il file.")
            text += ("❌ Non è stato possibile cancellare il file a causa di un errore del sistema operativo.\n\n"
                     "🔸 Scegli un'opzione")
        else:
            keyboard = [
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="backup_restore")
                ]
            ]
            text += "☑️ Il file è stato rimosso con successo."

        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id
        }, context=context)

        return ConversationState.BACKUP_DELETE

    if update.callback_query and update.callback_query.data.startswith("restore_backup"):
        path = update.callback_query.data.split(" ")[1]
        file_name = path.split("/")[-1]
        text += (f"📁 File Name: <code>{file_name}</code>\n\n"
                 "ℹ️ Le tue <b>applicazioni</b> e le tue <b>impostazioni</b>, compresi gli ultimi check, "
                 "verranno <u>sostituite</u> con quelle contenute nel file.\n\n"
                 "❔ Desideri procedere?")
        keyboard = [
            [
                InlineKeyboardButton(text="🔄️ Ripristina", callback_data="confirm_restore_backup " + path)
            ],
            [
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="backup_restore")
            ]
        ]
        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id
        }, context=context)

        return ConversationState.BACKUP_RESTORE

    if update.callback_query and update.callback_query.data.startswith("confirm_restore_backup"):
        if not (new_cd := await yaml_dict_loader(update.callback_query.data.split(" ")[1])):
            text += ("❌ Qualcosa è andato storto nel processo di ripristino. Nessuna modifica è stata applicata.\n\n"
                     "🔸 Scegli un'opzione")
            keyboard = [
                [
                    InlineKeyboardButton(text="🆘 Contatta @Linxay", url="https://t.me/Linxay"),
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="backup_restore")
                ]
            ]
        else:
            (cd := context.chat_data).update(new_cd)
            await reschedule(context, cd, True)
            text += ("✅ <i>Backup correttamente ripristinato</i>\n\n"
                     "🔸 Scegli un'opzione")
            keyboard = [
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="backup_restore")
                ],
                [
                    InlineKeyboardButton(text="🔙 Menù Impostazioni", callback_data="from_backup_restore")
                ]
            ]
        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id
        }, context=context)

        return

    if update.callback_query and update.callback_query.data == "change_max_backups":
        text += "🔸 Specifica il nuovo numero"
        keyboard = [
            [
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="backup_restore")
            ]
        ]
        cd["temp"]["max_backups"] = True

        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id
        }, context=context)

        return ConversationState.EDIT_MAX_BACKUPS


async def manage_users_and_permissions(update: Update, context: CallbackContext):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    if not await is_allowed_user_function(user_id=update.effective_chat.id,
                                          users=context.bot_data["users"],
                                          permission='can_manage_users'):
        await send_not_allowed_function_message(update, context)
        return

    cd = context.chat_data
    bd = context.bot_data

    text = "👤 <b>Gestione Utenti & Permessi</b>\n\n"

    if update.callback_query and update.callback_query.data == "user_managing":
        text += ("🔹 Da questa sezione puoi gestire e visualizzare gli utenti ed i relativi permessi.\n\n"
                 "ℹ️ Oltre ad <b>aggiungere</b> o <b>rimuovere</b> un utente per abilitarlo all'uso di questo bot, "
                 "potrai anche specificare <b>quali funzioni</b> un utente potrà usare.\n\n"
                 "🔸 Scegli come usare questo enorme ed ineluttabile potere.")
        keyboard = [
            [
                InlineKeyboardButton(text="➕ Aggiungi Utente", callback_data="add_allowed_user"),
                InlineKeyboardButton(text="➖ Rimuove Utente", callback_data="remove_allowed_user")
            ],
            [
                InlineKeyboardButton(text="✏️ Modifica Utente", callback_data="edit_user_permissions"),
                InlineKeyboardButton(text="📜 Lista Utenti", callback_data="list_users_permissions")
            ],
            [
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="settings")
            ]
        ]
        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id
        }, context=context)
        return ConversationState.USERS_MANAGING_MENU

    # AGGIUNTA UTENTE
    if update.callback_query and update.callback_query.data == "add_allowed_user":
        text += ("⚠️ Non potrò fare alcuna verifica sull'esistenza degli ID che aggiungi.\n\n"
                 "🔸 Indica l'ID utente che vuoi aggiungere.")
        keyboard = [
            [
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing"),
            ]
        ]
        cd["temp"]["message_to_delete"] = await parse_conversation_message(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "reply_markup": InlineKeyboardMarkup(keyboard),
            "message_id": update.effective_message.id
        }, context=context)
        cd["temp"]["adding_user"] = True
        return ConversationState.ADD_USER

    if not update.callback_query:
        if "user_label" in cd["temp"]:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=cd["temp"]["message_to_delete"])
            del cd["temp"]["message_to_delete"]

            label = update.effective_message.text
            cd["temp"]["user_label"] = label
            text += (f"🏷 <code>{label}</code>\n\n"
                     f"🔸 Confermi questo tag per l'ID <code>{cd['temp']['adding_user']}</code>?")
            keyboard = [
                [
                    InlineKeyboardButton(text="✅ Usa tag", callback_data="confirm_label"),
                    InlineKeyboardButton(text="✍ Riscrivi", callback_data="rewrite_label")
                ]
            ]
            await send_message_with_typing_action(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "keyboard": keyboard,
                "message_id": update.effective_message.id
            }, context=context)

            return ConversationState.CONFIRM_LABEL

        if "adding_user" in cd["temp"]:
            uid = ''.join(update.effective_message.text.split(" "))

            if not uid.isnumeric():
                text += ("❌ L'ID deve contenere solamente cifre.\n\n"
                         "🔸 Rimanda lo user ID")
                keyboard = [
                    [
                        InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
                    ]
                ]

                await send_message_with_typing_action(data={
                    "chat_id": update.effective_chat.id,
                    "text": text,
                    "keyboard": keyboard
                }, context=context)

                return ConversationState.ADD_USER

            await schedule_messages_to_delete(messages={
                cd["temp"]["message_to_delete"]: {
                    "chat_id": update.effective_chat.id,
                    "time": 1
                },
                update.effective_message.id: {
                    "chat_id": update.effective_chat.id,
                    "time": 1
                }
            }, context=context)
            del cd["temp"]["message_to_delete"]

            text += (f"🔍 Verifica la correttezza dell'ID: <code>{uid}</code>\n\n"
                     f"🔸 Confermi di voler aggiungere questo utente?")
            keyboard = [
                [
                    InlineKeyboardButton(text="☑️ Confermo", callback_data="confirm_user " + uid),
                    InlineKeyboardButton(text="✖️ Non confermo", callback_data="add_allowed_user")
                ]
            ]

            await send_message_with_typing_action(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "keyboard": keyboard,
            }, context=context)

            return ConversationState.CONFIRM_USER

        if "removing_user" in cd["temp"]:
            if "message_to_delete" in cd["temp"]:
                await delete_message(context=context,
                                     chat_id=update.effective_chat.id,
                                     message_id=cd["temp"]["message_to_delete"])
                del cd["temp"]["message_to_delete"]

            usr = bd["users"]["allowed"].get((uinp := int(re.sub(r'\D', '', update.effective_message.text))))
            if not usr:
                text += "❌ Non ho trovato l'ID. Riscrivilo."
                keyboard = [
                    [
                        InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
                    ]
                ]
                message_id = await parse_conversation_message(data={
                    "chat_id": update.effective_chat.id,
                    "text": text,
                    "reply_markup": InlineKeyboardMarkup(keyboard),
                    "message_id": update.effective_message.id
                }, context=context)

                cd["message_to_delete"] = message_id
                return ConversationState.REMOVE_OR_EDIT_USER

            text += f"🔸 Confermi di voler rimuovere <code>{uinp}</code> (🏷 <i>{usr['label']}</i>)?"
            keyboard = [
                [
                    InlineKeyboardButton(text="🚮 Rimuovi", callback_data="remove_allowed_user " + str(uinp)),
                    InlineKeyboardButton(text="🔙 No", callback_data="remove_allowed_user")
                ]
            ]
            await send_message_with_typing_action(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "keyboard": keyboard,
                "message_id": update.effective_message.id
            }, context=context)

            del cd["temp"]["removing_user"]

            return ConversationState.CONFIRM_REMOVE_USER

        if "editing_user" in cd["temp"]:
            if "message_to_delete" in cd["temp"]:
                await delete_message(context=context,
                                     chat_id=update.effective_chat.id,
                                     message_id=cd["temp"]["message_to_delete"])
                del cd["temp"]["message_to_delete"]

            usr = bd["users"]["allowed"].get((uinp := int(re.sub(r'\D', '', update.effective_message.text))))
            if not usr:
                text += "❌ Non ho trovato l'ID. Riscrivilo."
                keyboard = [
                    [
                        InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
                    ]
                ]
                message_id = await parse_conversation_message(data={
                    "chat_id": update.effective_chat.id,
                    "text": text,
                    "reply_markup": InlineKeyboardMarkup(keyboard),
                    "message_id": update.effective_message.id
                }, context=context)

                cd["message_to_delete"] = message_id
                return ConversationState.REMOVE_OR_EDIT_USER

            text += f"🔐 <b>Permessi di 🏷 {usr['label']}</b>\n"
            for permission in (bdu := usr["permissions"]):
                text += (f"  🔹 <i>{' '.join(w.capitalize() for w in permission.split('_'))}</i>: "
                         f"<code>{bdu[permission]}</code>\n")
            text += f"\n🔸 Confermi di voler modificare i permessi di <code>{uinp}</code>?"
            keyboard = [
                [
                    InlineKeyboardButton(text="✏ Modifica", callback_data="edit_allowed_user " + str(uinp)),
                    InlineKeyboardButton(text="🔙 No", callback_data="edit_user_permissions")
                ]
            ]
            await send_message_with_typing_action(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "keyboard": keyboard,
                "message_id": update.effective_message.id
            }, context=context)

            del cd["temp"]["editing_user"]

            return ConversationState.CONFIRM_EDIT_USER


    if update.callback_query and (update.callback_query.data.startswith("confirm_user")
                                  or update.callback_query.data == "rewrite_label"):
        if update.callback_query.data.startswith("confirm_user"):
            cd["temp"]["adding_user"] = update.callback_query.data.split(" ")[1]

        text += ("🔸 A chi appartiene questo ID?\n\n"
                 "🔍 <u>Alcuni Esempi</u>: <i>Mia Madre</i>, <i>Schiavo #1</i>")
        keyboard = [
            [
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
            ]
        ]
        cd["temp"]["message_to_delete"] = await parse_conversation_message(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "reply_markup": InlineKeyboardMarkup(keyboard),
            "message_id": update.effective_message.id
        }, context=context)
        cd["temp"]["user_label"] = True
        return ConversationState.ADD_USER_LABEL

    if update.callback_query.data and update.callback_query.data == "confirm_label":
        bd["users"]["allowed"][(uinp := int(cd["temp"]["adding_user"]))] = {
            "permissions": {},
            "label": cd["temp"]["user_label"]
        }
        for permission in bd["settings"]["permissions"]:
            bd["users"]["allowed"][uinp]["permissions"][permission] = None

        del cd["temp"]["user_label"]

        cd["temp"]["adding_user"] = uinp

        return await set_user_permissions(update, context)


    if update.callback_query and (update.callback_query.data.startswith("set_permission")
                                  or update.callback_query.data == "set_default_permissions"):
        if "editing_user" in cd["temp"]:
            usr = bd["users"]["allowed"][int(cd["temp"]["editing_user"])]
        else:
            usr = bd["users"]["allowed"][int(cd["temp"]["adding_user"])]

        if "editing_user" in cd["temp"]:
            text += (f"✅ <i>Utente <code>{cd['temp']['editing_user']}</code> modificato correttamente</i>\n\n"
                     f"🔑 <b>Permessi</b>\n")
        else:
            text += (f"✅ <i>Utente <code>{cd['temp']['adding_user']}</code> aggiunto correttamente</i>\n\n"
                 f"🔑 <b>Permessi</b>\n")
        for permission in usr["permissions"]:
            pf = ' '.join([i.capitalize() for i in permission.split("_")])
            text += f"     🔹<u>{pf}</u>: <code>{usr['permissions'][permission]}</code>\n"

        text += "\n🔸 Scegli un'opzione"
        if "adding_user" in cd["temp"]:
            keyboard = [
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing"),
                    InlineKeyboardButton(text="➕ Aggiungi altro utente", callback_data="add_allowed_user"),
                ]
            ]
        else:
            keyboard = [
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing"),
                    InlineKeyboardButton(text="✏ Modifica altro utente", callback_data="edit_user_permissions"),
                ]
            ]
        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id
        }, context=context)

        if "adding_user" in cd["temp"]:
            del cd["temp"]["adding_user"]

        return ConversationState.USERS_MANAGING_MENU

    # RIMOZIONE UTENTE
    if update.callback_query and (update.callback_query.data == "remove_allowed_user"
                                  or update.callback_query.data == "edit_user_permissions"):
        text += "📄 <b>Utenti Aggiunti</b>\n\n"
        if len(bd["users"]["allowed"]) > 0:
            for usr in bd["users"]["allowed"]:
                text += f"🏷 <i>{bd['users']['allowed'][usr]['label']}</i> (<code>{usr}</code>)\n"
            text += ("\n🔸 Fornisci l'ID di un utente\n\n"
                     "💡 <b>Tip</b>: puoi copiarlo toccandolo")
            keyboard = [
                [
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
                ]
            ]
        else:
            text += "ℹ Non hai aggiunto alcun utente"
            keyboard = [
                [
                    InlineKeyboardButton(text="➕ Aggiungi Utente", callback_data="add_allowed_user"),
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
                ]
            ]
            await parse_conversation_message(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "reply_markup": InlineKeyboardMarkup(keyboard),
                "message_id": update.effective_message.id
            }, context=context)

            return ConversationState.USERS_MANAGING_MENU


        message_id = await parse_conversation_message(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "reply_markup": InlineKeyboardMarkup(keyboard),
            "message_id": update.effective_message.id
        }, context=context)

        cd["temp"]["message_to_delete"] = message_id
        if update.callback_query.data == "remove_allowed_user":
            cd["temp"]["removing_user"] = True
        else:
            cd["temp"]["editing_user"] = True

        return ConversationState.REMOVE_OR_EDIT_USER

    if update.callback_query and (update.callback_query.data.startswith("remove_allowed_user")
                                  and not update.callback_query.data == "remove_allowed_user"):
        user_id = int(update.callback_query.data.split(" ")[1])
        del bd["users"]["allowed"][user_id]

        text += "✅ Utente rimosso correttamente. Non potrà più usare questo bot.\n\n"

        backups = await check_for_backups(user_id)

        if len(backups) > 0:
            text += (f"🔹 L'utente che hai rimosso aveva {len(backups)} file di backup.\n\n"
                     "🔸 Vuoi rimuovere tali file?")
            keyboard = [
                [
                    InlineKeyboardButton(text="🚮 Rimuovi", callback_data=f"delete_backup_files {user_id}"),
                    InlineKeyboardButton(text="🆗 Mantieni", callback_data="user_managing")
                ]
            ]

            await send_message_with_typing_action(data={
                "chat_id": update.effective_chat.id,
                "text": text,
                "keyboard": keyboard,
                "message_id": update.effective_message.id
            }, context=context)

            return ConversationState.DELETE_USER_BACKUPS

        text += "🔸 Scegli un'opzione"
        keyboard = [
            [
                InlineKeyboardButton(text="➖ Rimuovi altro utente", callback_data="remove_allowed_user"),
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
            ]
        ]

        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id
        }, context=context)


        return ConversationState.USERS_MANAGING_MENU

    if update.callback_query and update.callback_query.data.startswith("delete_backup_files"):
        try:
            shutil.rmtree(f"backups/{update.callback_query.data.split(' ')[-1]}")
            text += "✅ Backups rimossi con successo"
            keyboard = [
                [
                    InlineKeyboardButton(text="➖ Rimuovi altro utente", callback_data="remove_allowed_user"),
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
                ]
            ]
        except FileNotFoundError:
            text += "⚠ La cartella non è stata trovata"
            keyboard = [
                [
                    InlineKeyboardButton(text="➖ Rimuovi altro utente", callback_data="remove_allowed_user"),
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
                ]
            ]
        except PermissionError:
            text += "⚠ Non ho i permessi per rimuovere la cartella di file"
            keyboard = [
                [
                    InlineKeyboardButton(text="🆘 Contatta @AleLntr", url="https://t.me/AleLntr")
                ],
                [
                    InlineKeyboardButton(text="➖ Rimuovi altro utente", callback_data="remove_allowed_user"),
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
                ]
            ]
        except OSError as e:
            bot_logger.error(f"Errore durante il tentativo di rimozione di file dalla cartella backup: {e}")
            text += "⚠ Non sono riuscito a cancellare i file. Controlla 'settings.log'."
            keyboard = [
                [
                    InlineKeyboardButton(text="🆘 Contatta @AleLntr", url="https://t.me/AleLntr")
                ],
                [
                    InlineKeyboardButton(text="➖ Rimuovi altro utente", callback_data="remove_allowed_user"),
                    InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
                ]
            ]

        text += "\n\n🔸 Scegli un'opzione"

        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard,
            "message_id": update.effective_message.id
        }, context=context)

        return ConversationState.USERS_MANAGING_MENU


    # MODIFICA UTENTE
    if update.callback_query and update.callback_query.data.startswith("edit_allowed_user"):
        usr = bd["users"]["allowed"].get((uinp := int(update.callback_query.data.split(" ")[1])))
        for permission in bd["settings"]["permissions"]:
            usr["permissions"][permission] = None
        cd["temp"]["editing_user"] = uinp
        return await set_user_permissions(update, context)

    # LISTA UTENTI
    if update.callback_query and update.callback_query.data == "list_users_permissions":
        return await list_users_permissions(update, context)


async def list_users_permissions(update: Update, context: CallbackContext):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    users = context.bot_data["users"]

    text = ("📜 <b>Utenti e Permessi</b>\n\n"
            "🔹 <i>Proprietario</i>: @AleLntr\n"
            "🔹 <i>Padrone</i>: @Linxay\n\n")

    if len(users["allowed"]) > 0:
        for user in users["allowed"]:
            text += f"🔸 🏷 <i>{users["allowed"][user]['label']}</i> – <code>{user}</code>\n"
            for permission in users["allowed"][user]["permissions"]:
                text += (f"     🔹<b>{' '.join(w.capitalize() for w in permission.split('_'))}</b>: "
                         f"<code>{users["allowed"][user]["permissions"][permission]}</code>\n")
            text += "\n\n"

        text += "ℹ <i>Proprietario</i> e <i>Padrone</i> hanno sempre tutti i permessi."

        keyboard = [
            [
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
            ]
        ]
    else:
        text += "⚠ Non hai ancora aggiunto nessun utente"
        keyboard = [
            [
                InlineKeyboardButton(text="➕ Aggiungi Utente", callback_data="add_allowed_user"),
                InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="user_managing")
            ]
        ]

    await send_message_with_typing_action(data={
        "chat_id": update.effective_chat.id,
        "text": text,
        "keyboard": keyboard,
        "message_id": update.effective_message.id
    }, context=context)

    return ConversationState.USERS_MANAGING_MENU


async def set_user_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    cd = context.chat_data
    bd = context.bot_data
    data = update.callback_query.data
    if "adding_user" in cd["temp"]:
        usr = bd["users"]["allowed"][cd["temp"]["adding_user"]]
    else:
        usr = bd["users"]["allowed"][cd["temp"]["editing_user"]]

    default_settled = False

    if update.callback_query:
        if "true" in data:
            usr["permissions"][data.split(" ")[1]] = True
        elif "false" in data:
            usr["permissions"][data.split(" ")[1]] = False
        elif data == "set_default_permissions":
            for permission in usr["permissions"]:
                usr["permissions"][permission] = cd["settings"]["default_permissions"][permission]
                default_settled = True

    if not default_settled:
        text = ("👤 <b>Gestione Utenti e Permessi</b>\n\n"
                "🔏 <b>Impostazione Permessi Utente</b>\n\n")

        for permission in (d := usr["permissions"]):
            await check_dict_keys(bd["settings"]["permissions"][permission],
                                  ["permission_set_text", "button_text", "button_data"])
            if permission == "can_manage_users":
                usr["permissions"][permission] = False

            if d[permission] is None:
                pf = ' '.join([i.capitalize() for i in permission.split("_")])
                question = bd["settings"]["permissions"][permission]["permission_set_text"]
                text += f"🔹 <b>{pf}</b> – {question}"
                keyboard = [
                    [
                        InlineKeyboardButton(text="✅ True", callback_data="set_permission_true " + permission),
                        InlineKeyboardButton(text="❌ False", callback_data="set_permission_false " + permission)

                    ],
                    [
                        InlineKeyboardButton(text="⚡️ Use Defaults", callback_data="set_default_permissions")
                    ]
                ]
                await send_message_with_typing_action(data={
                    "chat_id": update.effective_chat.id,
                    "text": text,
                    "keyboard": keyboard,
                    "message_id": update.effective_message.id
                }, context=context)

                return ConversationState.SET_PERMISSION

    return await manage_users_and_permissions(update, context)


async def close_menu(update: Update, context: CallbackContext):
    await delete_message(context=context, chat_id=update.effective_chat.id,
                         message_id=int(update.callback_query.data.split(" ")[1]))

    return ConversationHandler.END


async def list_apps(update: Update, context: CallbackContext):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    text = "🗃 <b>App List</b>\n\n"

    if len(context.chat_data["apps"]) == 0:
        text += ("ℹ Nessuna app aggiunta.\n\n"
                 "🔸 Scegli un'opzione.")

    else:
        for a in context.chat_data["apps"]:
            ap = context.chat_data["apps"][a]
            text += (f"  {a}. <i>{ap['app_name']}</i>\n"
                     f"     🔸<u>App ID</u>: <code>{ap['app_id']}</code>\n"
                     f"     🔸<u>App Link</u>: <a href=\"{ap['app_link']}\">link 🔗</a>\n"
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

    await send_message_with_typing_action(data={
        "chat_id": update.effective_chat.id,
        "text": text,
        "message_id": update.effective_message.id,
        "keyboard": keyboard,
        "web_preview": False
    }, context=context)

    return ConversationState.LIST_APPS


async def list_last_checks(update: Update, context: CallbackContext):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    await delete_message(context=context, chat_id=update.effective_chat.id, message_id=update.effective_message.id)
    text = "📜 <b>Last Checks</b>\n\n"
    keyboard = [
        [
            InlineKeyboardButton(text="🔙 Torna Indietro", callback_data="back_to_main_menu")
        ]
    ]

    if len(context.chat_data["last_checks"]) == 0:
        text += "🔸 Nessun controllo effettuato."

    else:
        for check in context.chat_data["last_checks"]:
            text += (f"🔸<b> {check['app_name']}</b>\n"
                     f"🔹 Time: <code>{datetime.strftime(check['time'], '%d %B %Y – %H:%M:%S')}</code>\n")
            if check["update_found"]:
                text += (f"▫ Update Found ➡ Upgraded from <code>{check['current_version']}</code> "
                         f"to <code>{check['new_version']}</code>")
            else:
                text += f"▪ Update Not Found ➡ <code>Current Version: {check['current_version']}</code>"
            text += "\n\n"

        text += "ℹ I controlli di eventuali app sospese non sono in lista."

    await send_message_with_typing_action(data={
        "chat_id": update.effective_chat.id,
        "message_id": update.effective_message.id,
        "text": text,
        "keyboard": keyboard
    }, context=context)

    return ConversationState.CHANGE_SETTINGS


async def add_app(update: Update, context: CallbackContext):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    if update.callback_query and update.callback_query.data == "add_app":
        text = "➕ <b>Add App</b>\n\n"

        if len(context.chat_data["apps"]) != 0:
            text += "🗃 <u>Elenco</u>\n\n"
            for ap in context.chat_data["apps"]:
                text += f"  {ap}. {context.chat_data['apps'][ap]['app_name']}\n"

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

            for ap in (a := context.chat_data["apps"]):
                if a[ap]["app_id"] == app_details.get('appId'):
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
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    cd = context.chat_data
    if update.callback_query and update.callback_query.data == "confirm_app_to_edit":
        if "edit_message" in cd:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=cd["edit_message"])
            del cd["edit_message"]
        ap = cd["apps"][int(cd["app_index_to_edit"])]
        cd["setting_app"] = {
            "app_name": ap["app_name"],
            "app_link": ap["app_link"],
            "current_version": ap["current_version"],
            "last_update": ap["last_update"],
            "app_id": ap["app_id"]
        }

        cd["editing"] = True

    if update.callback_query and (update.callback_query.data.startswith("edit_app_from_check") or
                                  update.callback_query.data.startswith("edit_app_from_add")):
        index = update.callback_query.data.split(" ")[1]
        cd["app_index_to_edit"] = int(index)
        if update.callback_query.data.startswith("edit_app_from_check"):
            cd["from_check"] = True
        ap = cd["apps"][int(index)]
        cd["setting_app"] = {
            "title": ap["app_name"],
            "url": ap["app_link"],
            "current_version": ap["current_version"],
            "last_update": ap["last_update"],
            "appId": ap["app_id"]
        }

        cd["editing"] = True

    adding = False if "editing" in cd or (
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

        cd["message_to_delete"] = update.effective_message.id

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
            cd["message_to_delete"] = message_id

        return ConversationState.SET_INTERVAL

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    sleep(1)

    if update.callback_query and update.callback_query.data == "set_default_values":
        cd["apps"][len(cd["apps"]) + 1] = {
            "app_name": cd["setting_app"]["app_name"],
            "app_link": cd["setting_app"]["url"],
            "current_version": cd["setting_app"]["current_version"],
            "last_update": cd["setting_app"]["last_update"],
            "app_id": cd["setting_app"]["appId"],
            "last_check": None,
            "suspended": False,
            "check_interval": cd["settings"]["default_check_interval"],
            "send_on_check": cd["settings"]["default_send_on_check"]
        }

        del cd["setting_app"]

        return await schedule_app_check(cd, True, update, context)

    else:
        if update.callback_query and update.callback_query.data == "edit_set_default_values":
            index = int(cd["app_index_to_edit"])
            cd["apps"][index]["check_interval"] = cd["settings"]["default_check_interval"]
            cd["apps"][index]["send_on_check"] = cd["settings"]["default_send_on_check"]
            return await schedule_app_check(cd, True, update, context)

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
            if "message_to_delete" in cd:
                await schedule_messages_to_delete(context=context,
                                                  messages={
                                                      int(update.effective_message.id): {
                                                          "time": 2.5,
                                                          "chat_id": update.effective_chat.id
                                                      },
                                                      int(cd["message_to_delete"]): {
                                                          "time": 2,
                                                          "chat_id": update.effective_chat.id
                                                      }
                                                  })
                del cd["message_to_delete"]

            cd["setting_app"]["check_interval"] = {
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

            if "message_to_delete" in cd:
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

        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard
        }, context=context)

        return ConversationState.SEND_ON_CHECK

    if update.callback_query and update.callback_query.data.startswith("send_on_check"):
        if adding:
            cd["apps"][len(cd["apps"]) + 1] = {
                "app_name": cd["setting_app"]["app_name"],
                "app_link": cd["setting_app"]["url"],
                "current_version": cd["setting_app"]["current_version"],
                "last_update": cd["setting_app"]["last_update"],
                "app_id": cd["setting_app"]["appId"],
                "last_check": None,
                "suspended": False
            }

            ap = cd["apps"][len(cd["apps"])]
        else:
            ap = cd["apps"][int(cd["app_index_to_edit"])]

        ap["check_interval"] = cd["setting_app"]["check_interval"]

        ap["next_check"] = (datetime.now(pytz.timezone('Europe/Rome')) +
                            cd["setting_app"]["check_interval"]["timedelta"])

        ap["send_on_check"] = True if update.callback_query.data == "send_on_check_true" else False

        bot_logger.info(f"App {ap['app_name']} ({ap['app_id']}) Settled Successfully -> "
                        f"Interval: "
                        f"{ap['check_interval']['input']['months']}months "
                        f"{ap['check_interval']['input']['days']}days "
                        f"{ap['check_interval']['input']['hours']}hours "
                        f"{ap['check_interval']['input']['minutes']}minutes "
                        f"{ap['check_interval']['input']['seconds']}seconds – Send On Check: "
                        f"{ap['send_on_check']}")

        if "setting_app" in cd:
            del cd["setting_app"]

    return await schedule_app_check(cd, True, update, context)


async def edit_app(update: Update, context: CallbackContext):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    cd = context.chat_data
    if update.callback_query and update.callback_query.data == "edit_app":
        if "edit_message" in cd:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=cd["edit_message"])
            del cd["edit_message"]

        if len(cd["apps"]) == 0:
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

            for ap in cd["apps"]:
                a = cd["apps"][ap]
                text += (f"  {ap}. <i>{a['app_name']}</i>\n"
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

        cd["edit_message"] = message_id

        return ConversationState.EDIT_SELECT_APP

    if not update.callback_query and update.effective_message:
        if "message_to_delete" in cd:
            await schedule_messages_to_delete(context=context,
                                              messages={
                                                  int(cd["message_to_delete"]): {
                                                      "chat_id": update.effective_chat.id,
                                                      "time": 2
                                                  }
                                              })

            del cd["message_to_delete"]

        app_names = create_edit_app_list(cd)
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

            cd["app_index_to_edit"] = await get_app_from_string(inpt, context=context)

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

            cd["app_index_to_edit"] = inpt

        await schedule_messages_to_delete(context=context,
                                          messages={
                                              update.effective_message.id: {
                                                  "chat_id": update.effective_chat.id,
                                                  "time": 2
                                              }
                                          })

        text = (f"🔵 <b>App Found</b>\n\n"
                f"▶️ <code>"
                f"{cd['apps'][int(cd['app_index_to_edit'])]['app_name']}"
                f"</code>\n\n"
                f"🔸 È l'applicazione che vuoi modificare?")

        keyboard = [
            [
                InlineKeyboardButton(text="⚪️ Si", callback_data="confirm_app_to_edit"),
                InlineKeyboardButton(text="⚫️ No", callback_data="edit_app")
            ]
        ]

        await send_message_with_typing_action(data={
            "chat_id": update.effective_chat.id,
            "text": text,
            "keyboard": keyboard
        }, context=context)

        return ConversationState.EDIT_CONFIRM_APP


async def remove_app(update: Update, context: CallbackContext):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    cd = context.chat_data
    if update.callback_query and update.callback_query.data == "delete_app":
        if "delete_app_message" in cd:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=cd["delete_app_message"])
            del cd["delete_app_message"]

        if len(cd["apps"]) == 0:
            cd["removing"] = True
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

            for ap in cd["apps"]:
                a = cd["apps"][ap]
                text += f"  {ap}. <i>{a['app_name']}</i>\n"

            text += "\n🔸 Scegli un'applicazione da rimuovere indicando l'<u>indice</u> o il <u>nome</u>."
            message_id = await parse_conversation_message(context=context,
                                                          data={
                                                              "chat_id": update.effective_chat.id,
                                                              "text": text,
                                                              "message_id": update.effective_message.id,
                                                              "reply_markup": None
                                                          })

            cd["delete_app_message"] = message_id

        return ConversationState.DELETE_APP_SELECT

    if not update.callback_query:
        if "message_to_delete" in cd:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=cd["message_to_delete"])
            del cd["message_to_delete"]

        if (not update.message.text.strip().isnumeric() and
            (index := await get_app_from_string(update.message.text.strip().lower(), context))) or (
                (index := update.message.text.strip()).isnumeric() and 0 < int(index) <= len(cd["apps"])):
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=update.effective_message.id)
            ap = cd["apps"][int(index)]
            suspended = ap["suspended"]
            cd["app_index_to_delete"] = int(index)
            text = (f"🔵 <b>App Found</b>\n\n"
                    f"🔸 App Name: <code>{ap['app_name']}</code>\n\n"
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
            cd["message_to_delete"] = message.id

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

                cd["message_to_delete"] = message_id

                return ConversationState.DELETE_APP_SELECT

            if ((message := update.effective_message.text.strip().lower()).isnumeric()
                    and int(message) < 0 or int(message) > len(cd["apps"])):
                text = "❌ Inserisci un indice valido"

                message_id = await parse_conversation_message(context=context,
                                                              data={
                                                                  "chat_id": update.effective_chat.id,
                                                                  "text": text,
                                                                  "message_id": -1,
                                                                  "reply_markup": None
                                                              })

                cd["message_to_delete"] = message_id

                return ConversationState.DELETE_APP_SELECT

    if update.callback_query and update.callback_query.data == "confirm_remove":
        if "delete_app_message" in cd:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=cd["delete_app_message"])
            del cd["delete_app_message"]
        if "message_to_delete" in cd:
            await delete_message(context=context, chat_id=update.effective_chat.id,
                                 message_id=cd["message_to_delete"])
            del cd["message_to_delete"]

        app_name = cd["apps"][cd["app_index_to_delete"]]['app_name']
        app_id = cd["apps"][cd["app_index_to_delete"]]["app_id"]

        for j in context.job_queue.get_jobs_by_name(app_name):
            j.schedule_removal()

        for ap in cd["apps"]:
            if int(ap) < int(cd["app_index_to_delete"]):
                continue
            elif int(ap) < len(cd["apps"]):
                cd["apps"][ap] = cd["apps"][int(ap) + 1]
        del cd["apps"][len(cd["apps"])]
        del cd["app_index_to_delete"]

        bot_logger.info(f"App {app_name} ({app_id}) deleted successfully")

        text = ("✔ <b>App Removed Successfully</b>\n\n"
                "🔸 Scegli un'opzione.")
        keyboard = [
            [
                InlineKeyboardButton(text="➖ Rimuovi Altra App", callback_data="delete_app"),
                InlineKeyboardButton(text="🔙 Torna indietro", callback_data="back_to_settings")
            ]
        ] if len(cd["apps"]) > 0 else [
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
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    cd = context.chat_data
    if update.callback_query:
        if (update.callback_query.data.startswith("suspend_app") or
                update.callback_query.data.startswith("suspend_from_remove")):
            if "delete_app_message" in cd:
                await delete_message(context=context, chat_id=update.effective_chat.id,
                                     message_id=cd["delete_app_message"])
                del cd["delete_app_message"]

            li = update.callback_query.data.split(" ")

            if cd["apps"][int(li[1])]["suspended"]:
                text = (f"⏸ <b>Sospendi Controlli App</b>\n\n"
                        f"🔹 L'app <code>{cd['apps'][int(li[1])]['app_name']}</code> era già sospesa.\n\n"
                        f"🔸 Puoi riattivarla dalle impostazioni.")
            else:
                cd["apps"][int(li[1])]["suspended"] = True

                text = (f"⏸ <b>Sospendi Controlli App</b>\n\n"
                        f"🔹  App <code>{cd['apps'][int(li[1])]['app_name']}</code> "
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

            for ap in (a := cd["apps"]):
                if a[ap]["suspended"]:
                    keyboard.append([InlineKeyboardButton(text=f"{a[ap]['app_name']}",
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
            (ap := cd["apps"][int(index)])["suspended"] = False
            text = ("⏯ <b>Riattiva Controlli App</b>\n\n"
                    f"ℹ Controlli app <code>{ap['app_name']}</code> riattivati\n\n"
                    f"🔸 Scegli un'opzione.")

            suspended = False

            for ap in (a := cd["apps"]):
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
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    cd = context.chat_data
    if (index := int(update.callback_query.data.split(" ")[1])) in cd["apps"]:
        ap = cd["apps"][index]

        text = (f"🔍 <b>App Settings</b>\n\n"
                f"  🔹App Name: <code>{ap['app_name']}</code>\n"
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
    for a in context.chat_data["apps"]:
        if (string == ''.join(filter(whitelist.__contains__, context.chat_data["apps"][a]['app_name'].lower())).
                replace("  ", " ")):
            return a
    return None


async def input_name_fixer(string: str):
    whitelist = set('abcdefghijklmnopqrstuvwxyz ')
    return ''.join(filter(whitelist.__contains__, string.lower())).replace("  ", " ")


async def send_menage_apps_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed_user(user_id=update.effective_chat.id, users=context.bot_data["users"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ You are not allowed to use this bot.")
        return

    cd = context.chat_data
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

    for ap in (a := cd["apps"]):
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

    if "edit_message" in cd:
        del cd["edit_message"]

    if "delete_app_message" in cd:
        del cd["delete_app_message"]

    if "editing" in cd:
        del cd["editing"]
    if "adding" in cd:
        del cd["adding"]
    if "removing" in cd:
        del cd["removing"]

    if update.callback_query and (update.callback_query.data == "back_to_settings_settled" or
                                  update.callback_query.data == "back_to_settings_no_apps"):
        return

    return ConversationState.MANAGE_APPS


async def is_owner_or_admin(context: ContextTypes.DEFAULT_TYPE, user_id: str | int) -> bool:
    return int(user_id) == context.bot_data["users"]["owner"] or int(user_id) == context.bot_data["users"]["admin"]


async def check_for_backups(user_id: int | str) -> dict:
    file_dict = {}
    try:
        file_list = [f for f in os.listdir(f'backups/{user_id}') if os.path.isfile(f'backups/{user_id}/{f}')]
    except FileNotFoundError:
        file_list = []

    for counter, el in enumerate(file_list, start=1):
        file_dict[int(counter)] = {
            "file_name": el,
            "backup_time": datetime.strptime(el, "%d_%m_%Y_%H_%M_%S.yml")
        }

    return file_dict


async def check_number_backups_for_users(context: ContextTypes.DEFAULT_TYPE) -> list:
    max_b = context.bot_data["settings"]["max_backups"]

    for root, dirs, files in os.walk('backups/'):
        backups = [os.path.join(root, f) for f in files if f.endswith(".yml")]



def create_edit_app_list(chat_data: dict) -> list:
    whitelist = set('abcdefghijklmnopqrstuvwxyz ')
    app_names = []
    if "apps" in chat_data:
        for a in chat_data["apps"]:
            app_names.append(''.join(filter(whitelist.__contains__, str(chat_data["apps"][a]['app_name']).lower())).
                             replace("  ", " "))

    return app_names or []
