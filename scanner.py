import asyncio
import os
import time
import logging
from pyrogram import filters, Client
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from database import save_image_metadata, get_db_stats, is_image_indexed
from image_matcher import get_image_hash

logger = logging.getLogger(__name__)

def is_image_message(message: Message) -> bool:
    if message.photo:
        return True
    if message.document:
        if message.document.mime_type and message.document.mime_type.startswith("image/"):
            return True
        if message.document.file_name and message.document.file_name.lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        ):
            return True
    return False

def register_user_handlers(user: Client):
    # Lắng nghe ảnh mới ở các nhóm và channel (real-time)
    @user.on_message((filters.group | filters.channel) & filters.create(lambda _, __, m: is_image_message(m)))
    async def index_new_photo(client: Client, message: Message):
        if is_image_indexed(message.id, message.chat.id):
            return

        file_path = None
        try:
            file_path = await message.download()
            if not file_path:
                return
                
            phash = get_image_hash(file_path)
            if phash:
                chat_title = message.chat.title or "Unknown Chat"
                save_image_metadata(
                    message_id=message.id,
                    chat_id=message.chat.id,
                    chat_title=chat_title,
                    date=int(message.date.timestamp()),
                    link=message.link,
                    phash=str(phash)
                )
                logger.info(f"Đã lưu ảnh mới từ nhóm '{chat_title}' (Msg ID: {message.id})")
        except Exception as e:
            logger.error(f"Lỗi khi index ảnh mới: {e}")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

    # Lệnh cho User client để quét thủ công lịch sử: .scan (quét tất cả) hoặc .scan <số lượng>
    @user.on_message(filters.command("scan", prefixes=".") & filters.me)
    async def manual_scan(client: Client, message: Message):
        # Kiểm tra nếu người dùng truyền số lượng cụ thể: .scan 500
        scan_limit = 0  # 0 trong Pyrogram có nghĩa là quét toàn bộ lịch sử không giới hạn
        parts = message.text.strip().split()
        if len(parts) > 1 and parts[1].isdigit():
            scan_limit = int(parts[1])
            await message.edit_text(f"🔄 Đang quét tối đa {scan_limit} tin nhắn gần nhất...")
        else:
            await message.edit_text("🔄 Bắt đầu quét **TOÀN BỘ** ảnh trong nhóm/kênh này...")

        count_new = 0
        count_skipped = 0
        total_checked = 0
        chat_id = message.chat.id
        last_edit_time = time.time()
        
        try:
            async for msg in client.get_chat_history(chat_id, limit=scan_limit):
                total_checked += 1
                
                if is_image_message(msg):
                    # Nếu ảnh đã được lưu rồi thì bỏ qua ngay để tăng tốc tối đa
                    if is_image_indexed(msg.id, chat_id):
                        count_skipped += 1
                    else:
                        file_path = None
                        try:
                            file_path = await msg.download()
                            if file_path:
                                phash = get_image_hash(file_path)
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
                                    count_new += 1
                        except FloodWait as fw:
                            logger.warning(f"Telegram yêu cầu đợi {fw.value}s (FloodWait)")
                            await asyncio.sleep(fw.value)
                        except Exception as dl_err:
                            logger.error(f"Lỗi tải ảnh msg {msg.id}: {dl_err}")
                        finally:
                            if file_path and os.path.exists(file_path):
                                os.remove(file_path)

                # Cập nhật tiến độ mỗi 5 giây một lần để tránh spam edit
                if time.time() - last_edit_time >= 5:
                    try:
                        await message.edit_text(
                            f"🔄 **Đang quét toàn bộ nhóm...**\n\n"
                            f"• Tin nhắn đã kiểm tra: **{total_checked}**\n"
                            f"• Ảnh mới đã lưu: **{count_new}**\n"
                            f"• Ảnh cũ đã có trong DB: **{count_skipped}**"
                        )
                        last_edit_time = time.time()
                    except Exception:
                        pass

            await message.edit_text(
                f"✅ **ĐÃ HOÀN TẤT QUÉT!**\n\n"
                f"• Tổng tin nhắn đã duyệt: **{total_checked}**\n"
                f"• Lưu thành công: **{count_new}** ảnh mới\n"
                f"• Bỏ qua: **{count_skipped}** ảnh đã tồn tại trong DB"
            )
            logger.info(f"Quét hoàn tất: lưu {count_new} ảnh mới, {count_skipped} ảnh trùng từ chat {chat_id}")
        except FloodWait as fw:
            await asyncio.sleep(fw.value)
        except Exception as e:
            logger.error(f"Lỗi khi quét: {e}")
            await message.edit_text(f"❌ Lỗi khi quét: {e}")

    # Lệnh kiểm tra thống kê nhanh cho Userbot
    @user.on_message(filters.command("stats", prefixes=".") & filters.me)
    async def manual_stats(client: Client, message: Message):
        total_images, total_chats, top_chats = get_db_stats()
        text = (
            f"📊 **THỐNG KÊ DỮ LIỆU**\n\n"
            f"🖼️ Tổng số ảnh đã lưu: **{total_images}**\n"
            f"👥 Số nhóm/kênh: **{total_chats}**\n"
        )
        if top_chats:
            text += "\n🏆 **Top nhóm nhiều ảnh:**\n"
            for i, (title, count) in enumerate(top_chats, 1):
                text += f"{i}. {title}: {count} ảnh\n"
        await message.edit_text(text)
