import datetime
from dotenv import load_dotenv
import os
import pytz

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application
import telegram
from google_play_scraper import app
from google_play_scraper.exceptions import NotFoundError

import logging
from logging import handlers

job_queue_logger = logging.getLogger("job_queue_logger")
job_queue_logger.setLevel(logging.WARN)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = handlers.RotatingFileHandler(filename="logs/job_queue.log",
                                            maxBytes=1024, backupCount=1)
file_handler.setFormatter(formatter)
job_queue_logger.addHandler(file_handler)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
job_queue_logger.addHandler(console_handler)

load_dotenv()
WHO = os.getenv("OWNER_ID")


async def scheduled_send_message(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    if "chat_id" not in data or "text" not in data:
        job_queue_logger.warning("'chat_id' or 'message_id' are missing in Job data.")
        raise Exception("Missing 'chat_id' or 'message_id' in job data.")

    if "message_id" in data:
        try:
            await context.bot.delete_message(chat_id=data["chat_id"], message_id=data["message_id"])
        except telegram.error.BadRequest as e:
            job_queue_logger.warning(f"Failed to delete message: {e}.")

    if "keyboard" in data:
        if "close_button" in data:
            check = isinstance(data["close_button"][0], list)
            close_buttons = []
            if check:
                for button in data["close_button"]:
                    close_button = data["keyboard"]
                    for i in button:
                        if i > len(close_button):
                            job_queue_logger.error("Close button id is greater than the number of buttons in"
                                                   " the keyboard.")
                            raise telegram.error.BadRequest("Close button id is greater than the number of buttons in "
                                                            "the keyboard.")
                        close_button = close_button[i - 1]
                    close_buttons.append(close_button)
            else:
                close_button = data["keyboard"]
                for i in data["close_button"]:
                    if i > len(close_button):
                        job_queue_logger.error("Close button id is greater than the number of buttons in the keyboard.")
                        raise telegram.error.BadRequest("Close button id is greater than the number of buttons in "
                                                        "the keyboard.")
                    close_button = close_button[i - 1]
                close_buttons.append(close_button)

    try:
        web_preview = (not data["web_preview"] if "web_preview" in data else None)
        if "close_button" in data:
            message = await context.bot.send_message(chat_id=data["chat_id"],
                                                     text=data["text"],
                                                     parse_mode="HTML",
                                                     disable_web_page_preview=web_preview)
            # noinspection PyUnboundLocalVariable
            for counter, button in enumerate(close_buttons, start=1):
                # noinspection PyUnboundLocalVariable
                close_buttons[counter - 1] = InlineKeyboardButton(text=close_buttons[counter - 1].text,
                                                                  callback_data=close_buttons[counter - 1].
                                                                  callback_data.format(message.id))
            # noinspection PyUnboundLocalVariable
            if check:
                for counter, button in enumerate(data["close_button"], start=1):
                    button_to_change = data["keyboard"]
                    parent = None
                    for i in button:
                        parent = button_to_change
                        button_to_change = button_to_change[i - 1]
                    final_index = button[-1] - 1
                    # noinspection PyUnboundLocalVariable
                    parent[final_index] = close_buttons[counter - 1]
            else:
                button_to_change = data["keyboard"]
                parent = None
                for i in data["close_button"]:
                    parent = button_to_change
                    button_to_change = button_to_change[i - 1]
                final_index = data["close_button"][-1] - 1
                # noinspection PyUnboundLocalVariable
                parent[final_index] = close_buttons[0]

            reply_markup = InlineKeyboardMarkup(data["keyboard"])
            await context.bot.edit_message_reply_markup(chat_id=data["chat_id"], message_id=message.id,
                                                        reply_markup=reply_markup)
        else:
            await context.bot.send_message(chat_id=data["chat_id"], text=data["text"], parse_mode="HTML",
                                           reply_markup=(InlineKeyboardMarkup(data["keyboard"])
                                                         if "keyboard" in data else None),
                                           disable_web_page_preview=web_preview)

    except telegram.error.TelegramError as e:
        job_queue_logger.error(f'Not able to perform scheduled action: {e}')


async def scheduled_edit_message(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    if "chat_id" not in data or "text" not in data or "message_id" not in data:
        job_queue_logger.warning("'chat_id' or 'message_id' or 'message_id' are missing in Job data.")
        raise Exception("Missing 'chat_id' or 'message_id' in job data.")

    message = await context.bot.send_message(text=".", chat_id=data["chat_id"])
    await context.bot.delete_message(chat_id=data["chat_id"], message_id=message.id)

    try:
        await context.bot.edit_message_text(text=data["text"],
                                            chat_id=data["chat_id"],
                                            message_id=data["message_id"],
                                            reply_markup=(InlineKeyboardMarkup(data["keyboard"]))
                                            if "keyboard" in data else None,
                                            parse_mode="HTML")
    except telegram.error.TelegramError as e:
        job_queue_logger.error(f'Not able to perform scheduled action: {e}')


async def scheduled_delete_message(context: ContextTypes.DEFAULT_TYPE):
    if "message_id" not in context.job.data or "chat_id" not in context.job.data:
        job_queue_logger.error("Missing message_id or chat_id in job data")
        raise Exception("Missing 'message_id' or 'chat_id' in job data.")

    try:
        await context.bot.delete_message(chat_id=context.job.data["chat_id"],
                                         message_id=context.job.data["message_id"])
    except telegram.error.BadRequest as e:
        job_queue_logger.warning(f'Not able to perform scheduled action: {e}')


async def scheduled_app_check(context: ContextTypes.DEFAULT_TYPE):
    if ("chat_data" not in context.job.data or "app_id" not in context.job.data or "app_link" not in context.job.data
            or "app_index" not in context.job.data):
        job_queue_logger.error("'app_id' or 'app_link' or 'app_index' are missing in Job data.")
        return

    cd = context.job.data["chat_data"]

    if (ap := cd["apps"][context.job.data["app_index"]])["suspended"]:
        job_queue_logger.info(f"Check Suspended for app {ap['app_name']}.")
        return

    if (res := requests.get(context.job.data["app_link"])).status_code != 200:
        job_queue_logger.error(f"Not Able to Get Link {context.job.data['app_link']}: {res.reason}")
        return

    try:
        app_details = app(app_id=context.job.data["app_id"])
    except NotFoundError as e:
        job_queue_logger.error(f"App '{context.job.data['app_id']}' not found: {e}")
    else:
        index = context.job.data["app_index"]
        ap = cd["apps"][index]
        ap["last_check"] = datetime.datetime.now(pytz.timezone('Europe/Rome'))
        ap["next_check"] = datetime.datetime.now(pytz.timezone('Europe/Rome')) + ap["check_interval"]["timedelta"]
        new_version = app_details.get("version")
        update_date = datetime.datetime.strptime(app_details.get("lastUpdatedOn"), '%b %d, %Y')

        if isinstance(ap["last_update"], datetime.datetime):
            check = (new_version != ap["current_version"] or
                     update_date.strftime("%d %B %Y") != ap["last_update"].strftime("%d %B %Y"))
        else:
            check = (new_version != ap["current_version"] or
                     update_date.strftime("%d %B %Y") != ap["last_update"])

        text = None

        if check:
            text = (f"🚨 <b>New Update Found</b>\n\n"
                    f"   🔹App Name: <code>{ap['app_name']}</code>\n"
                    f"   🔹Registered Version: <code>{ap['current_version']}</code>\n"
                    f"   🔹New Version: {new_version}\n"
                    f"   🔹Updated On: <code>{ap['last_update']}</code>\n\n"
                    f"🔸Scegli un'opzione") if new_version != 'Varies with device' else (
                f"🚨 <b>New Update Found</b>\n\n"
                f"   🔹App Name: <code>{ap['app_name']}</code>\n"
                f"   🔹Registered Version: ⚠️ <code>{ap['current_version']}</code>\n"
                f"   🔹New Version: {new_version}\n"
                f"   🔹Updated On: <code>{ap['last_update']}</code>\n\n"
                f"   ▪️Next Check: <code>{ap['next_check'].strftime('%d %B %Y – %H:%M:%S')}</code>\n\n"
                f"ℹ Potrebbe essere che l'aggiornamento non riguardi il client di interesse perché la versione"
                f" dipende dal dispositivo.\n\n"
                f"🔸Scegli un'opzione"
            )

            last_check = {
                "time": ap["last_check"],
                "app_name": ap["app_name"],
                "current_version": ap["current_version"],
                "new_version": new_version,
                "update_found": True
            }

            ap["current_version"] = new_version
            ap["last_update"] = update_date.strftime("%d %B %Y")

        elif ap["send_on_check"]:
            text = (f"👁‍🗨 <b>Check Performed</b> – No Updates Found\n\n"
                    f"   🔹App Name: <code>{ap['app_name']}</code>\n"
                    f"   🔹Registered Version: <code>{ap['current_version']}</code>\n"
                    f"   🔹Updated On: <code>{ap['last_update']}</code>\n"
                    f"   ▪️Next Check: <code>{ap['next_check'].strftime('%d %B %Y – %H:%M:%S')}</code>\n\n"
                    f"🔸Scegli un'opzione")

            last_check = {
                "time": ap["last_check"],
                "app_name": ap["app_name"],
                "current_version": ap["current_version"],
                "update_found": False
            }

        if text:
            if len(lc := cd["last_checks"]) == 10:
                lc.pop(0)

            # entro nell'if solo se text != None
            # noinspection PyUnboundLocalVariable
            lc.append(last_check)

            message = await context.bot.send_message(
                chat_id=WHO,
                text=text,
                parse_mode="HTML"
            )

            keyboard = [
                [
                    InlineKeyboardButton(text="🪛 Imp. App", callback_data=f"edit_from_job {index}"),
                    InlineKeyboardButton(text="🌐 Vai al Play Store", url=ap["app_link"])
                ],
                [
                    InlineKeyboardButton(text="⏸ Sospendi Controlli", callback_data=f"suspend_app {index}")
                ],
                [
                    InlineKeyboardButton(text="🗑 Cancella Messaggio",
                                         callback_data=f"delete_message {message.id}")
                ]
            ]

            await context.bot.edit_message_reply_markup(chat_id=WHO,
                                                        message_id=message.id,
                                                        reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            job_queue_logger.info("No message is sent cause of app settings.")


async def reschedule(ap: Application, cd: dict):
    if "apps" in cd:
        li = []
        for a in cd["apps"]:
            i = cd["apps"][a]
            try:
                if i["next_check"] - datetime.datetime.now(pytz.timezone('Europe/Rome')) < datetime.timedelta(0):
                    ap.job_queue.run_once(callback=scheduled_app_check,
                                          data={
                                              "app_id": i["app_id"],
                                              "app_link": i["app_link"],
                                              "app_index": a
                                          },
                                          when=1,
                                          name=i["app_name"])
                    ap.job_queue.run_repeating(callback=scheduled_app_check,
                                               interval=i["check_interval"]["timedelta"],
                                               data={
                                                   "app_id": i["app_id"],
                                                   "app_link": i["app_link"],
                                                   "app_index": a
                                               },
                                               name=i["app_name"])
                else:
                    ap.job_queue.run_once(callback=scheduled_app_check,
                                          data={
                                              "app_id": i["app_id"],
                                              "app_link": i["app_link"],
                                              "app_index": a
                                          },
                                          when=i["next_check"],
                                          name=i["app_name"])
                    ap.job_queue.run_repeating(callback=scheduled_app_check,
                                               interval=i["check_interval"]["timedelta"],
                                               data={
                                                   "app_id": i["app_id"],
                                                   "app_link": i["app_link"],
                                                   "app_index": a
                                               },
                                               first=i["next_check"] + i["check_interval"]["timedelta"],
                                               name=i["app_name"])
            except KeyError:
                li.append(a)

        for i in li:
            del cd["apps"][i]
