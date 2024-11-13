import asyncio
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.errors.exceptions.bad_request_400 import ChannelInvalid, ChatAdminRequired, UsernameInvalid, UsernameNotModified
from info import ADMINS, LOG_CHANNEL, CHANNELS
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils import temp, get_readable_time
import time

lock = asyncio.Lock()

@Client.on_callback_query(filters.regex(r'^index'))
async def index_files(bot, query):
    _, ident, chat, lst_msg_id, skip = query.data.split("#")
    if ident == 'yes':
        msg = query.message
        await msg.edit("<b>Indexing started...</b>")
        try:
            chat = int(chat)
        except ValueError:
            chat = chat
        await index_files_to_db(int(lst_msg_id), chat, msg, bot, int(skip))
    elif ident == 'cancel':
        temp.CANCEL = True
        await query.message.edit("Trying to cancel Indexing...")

@Client.on_message(filters.command('index') & filters.private & filters.incoming & filters.user(ADMINS))
async def send_for_index(bot, message):
    if lock.locked():
        return await message.reply('Wait until the previous process completes.')

    prompt_msg = await message.reply("Please forward the last message or send the last message link.")
    
    # Adding a delay to wait for response, with a timeout to handle cases if the user doesn't respond
    try:
        response_msg = await bot.listen(chat_id=message.chat.id, timeout=60)
        await prompt_msg.delete()
        
        if response_msg.text and response_msg.text.startswith("https://t.me"):
            # Process link
            msg_link = response_msg.text.split("/")
            last_msg_id = int(msg_link[-1])
            chat_id = msg_link[-2]
            if chat_id.isnumeric():
                chat_id = int(("-100" + chat_id))
                
        elif response_msg.forward_from_chat and response_msg.forward_from_chat.type == enums.ChatType.CHANNEL:
            last_msg_id = response_msg.forward_from_message_id
            chat_id = response_msg.forward_from_chat.username or response_msg.forward_from_chat.id
        else:
            await message.reply('This is not a forwarded message or valid link.')
            return

        try:
            chat = await bot.get_chat(chat_id)
        except Exception as e:
            return await message.reply(f'Error retrieving chat: {e}')

        if chat.type != enums.ChatType.CHANNEL:
            return await message.reply("I can only index messages from channels.")

        skip_msg = await message.reply("Please send the number of messages to skip.")
        skip_response = await bot.listen(chat_id=message.chat.id, timeout=60)
        await skip_msg.delete()
        
        try:
            skip = int(skip_response.text)
        except ValueError:
            return await message.reply("The skip number is invalid.")

        buttons = [[
            InlineKeyboardButton('YES', callback_data=f'index#yes#{chat_id}#{last_msg_id}#{skip}')
        ], [
            InlineKeyboardButton('CLOSE', callback_data='close_data'),
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply(f'Do you want to index the {chat.title} channel?\nTotal Messages: <code>{last_msg_id}</code>', reply_markup=reply_markup)

    except asyncio.TimeoutError:
        await message.reply("Request timed out. Please try again.")

@Client.on_message(filters.command('channel'))
async def channel_info(bot, message):
    if message.from_user.id not in ADMINS:
        await message.reply('Only the bot owner can use this command.')
        return
    ids = CHANNELS
    if not ids:
        return await message.reply("No channels are set in the configuration.")
    text = '**Indexed Channels:**\n\n'
    for id in ids:
        chat = await bot.get_chat(id)
        text += f'{chat.title}\n'
    text += f'\n**Total:** {len(ids)}'
    await message.reply(text)

async def index_files_to_db(lst_msg_id, chat, msg, bot, skip):
    start_time = time.time()
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    current = skip
    
    async with lock:
        try:
            async for message in bot.iter_messages(chat, lst_msg_id, skip):
                time_taken = get_readable_time(time.time() - start_time)
                if temp.CANCEL:
                    temp.CANCEL = False
                    await msg.edit(f"Indexing Canceled!\nCompleted in {time_taken}\n\nSaved <code>{total_files}</code> files.\nDuplicates Skipped: <code>{duplicate}</code>\nDeleted Messages: <code>{deleted}</code>\nNon-Media Skipped: <code>{no_media + unsupported}</code>\nUnsupported Media: <code>{unsupported}</code>\nErrors: <code>{errors}</code>")
                    return
                current += 1
                if current % 100 == 0:
                    btn = [[
                        InlineKeyboardButton('CANCEL', callback_data=f'index#cancel#{chat}#{lst_msg_id}#{skip}')
                    ]]
                    await msg.edit_text(text=f"Processed: <code>{current}</code>\nSaved: <code>{total_files}</code>\nDuplicates: <code>{duplicate}</code>\nDeleted: <code>{deleted}</code>\nNon-Media: <code>{no_media + unsupported}</code>\nUnsupported Media: <code>{unsupported}</code>\nErrors: <code>{errors}</code>", reply_markup=InlineKeyboardMarkup(btn))
                    await asyncio.sleep(2)
                
                if message.empty:
                    deleted += 1
                    continue
                elif not message.media:
                    no_media += 1
                    continue
                elif message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.DOCUMENT]:
                    unsupported += 1
                    continue

                media = getattr(message, message.media.value, None)
                if not media:
                    unsupported += 1
                    continue
                elif media.mime_type not in ['video/mp4', 'video/x-matroska']:
                    unsupported += 1
                    continue

                media.caption = message.caption
                sts = await save_file(media)
                if sts == 'suc':
                    total_files += 1
                elif sts == 'dup':
                    duplicate += 1
                elif sts == 'err':
                    errors += 1
        except FloodWait as e:
            await asyncio.sleep(e.x)
        except Exception as e:
            await msg.reply(f'Indexing canceled due to Error: {e}')
        else:
            time_taken = get_readable_time(time.time() - start_time)
            await msg.edit(f'Successfully indexed <code>{total_files}</code> files.\nCompleted in {time_taken}\n\nDuplicates: <code>{duplicate}</code>\nDeleted: <code>{deleted}</code>\nNon-Media Skipped: <code>{no_media + unsupported}</code>\nUnsupported Media: <code>{unsupported}</code>\nErrors: <code>{errors}</code>')
