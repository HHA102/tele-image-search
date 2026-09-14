import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
from pyrogram import filters, Client
from pyrogram.types import Message
from database import save_image_metadata
from image_matcher import get_image_hash

def register_user_handlers(user: Client):
    # Lắng nghe ảnh mới ở các nhóm và channel
    @user.on_message(filters.photo & (filters.group | filters.channel))
    async def index_new_photo(client: Client, message: Message):
        file_path = await message.download()
        if not file_path:
            return
            
        phash = get_image_hash(file_path)
        
        # Xóa file sau khi tính hash
        if os.path.exists(file_path):
            os.remove(file_path)
            
        if phash:
            chat_title = message.chat.title or "Unknown Chat"
            # Lưu metadata vào DB
            save_image_metadata(
                message_id=message.id,
                chat_id=message.chat.id,
                chat_title=chat_title,
                date=int(message.date.timestamp()),
                link=message.link,
                phash=str(phash)
            )

    # Lệnh cho User client để quét thủ công lịch sử của nhóm hiện tại
    @user.on_message(filters.command("scan", prefixes=".") & filters.me)
    async def manual_scan(client: Client, message: Message):
        await message.edit_text("🔄 Đang quét tối đa 200 tin nhắn gần nhất chứa ảnh...")
        count = 0
        chat_id = message.chat.id
        
        try:
            async for msg in client.get_chat_history(chat_id, limit=200):
                if msg.photo:
                    file_path = await msg.download()
                    if not file_path:
                        continue
                        
                    phash = get_image_hash(file_path)
                    
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        
                    if phash:
                        chat_title = msg.chat.title or "Unknown Chat"
                        save_image_metadata(
                            message_id=msg.id,
                            chat_id=msg.chat.id,
                            chat_title=chat_title,
                            date=int(msg.date.timestamp()),
                            link=msg.link,
                            phash=str(phash)
                        )
                        count += 1
            await message.edit_text(f"✅ Đã quét xong! Lưu thành công {count} ảnh từ nhóm này vào DB.")
        except Exception as e:
            await message.edit_text(f"❌ Lỗi khi quét: {e}")

