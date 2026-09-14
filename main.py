import asyncio

# Khởi tạo event loop cố định tương thích với Python 3.12 & 3.13
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

import os
import time
import logging
from datetime import datetime
import imagehash
from pyrogram import Client, filters, compose
from pyrogram.types import Message
from pyrogram.errors import FloodWait

from config import API_ID, API_HASH, BOT_TOKEN
from database import init_db, get_all_images, get_db_stats, is_image_indexed, save_image_metadata
from image_matcher import get_image_hash, compare_hashes
from scanner import register_user_handlers, is_image_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Khởi tạo 2 client: Bot để giao tiếp & quét nhóm công khai, User để quét kênh kín
bot = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("user_session", api_id=API_ID, api_hash=API_HASH)

# Đăng ký các handler của User client
register_user_handlers(user)

image_filter = filters.photo | filters.create(lambda _, __, m: is_image_message(m))

# ==========================================
# 1. TÌM KIẾM ẢNH QUA BOT (CHAT RIÊNG)
# ==========================================

@bot.on_message(image_filter & filters.private)
async def handle_query_photo(client: Client, message: Message):
    user_name = message.from_user.first_name if message.from_user else "Người dùng"
    logger.info(f"Nhận được ảnh tìm kiếm từ: {user_name} (ID: {message.from_user.id if message.from_user else 'Unknown'})")
    status_msg = await message.reply("🔍 Đang tải ảnh và tính toán tìm kiếm...")
    
    file_path = None
    try:
        file_path = await message.download()
        if not file_path:
            await status_msg.edit_text("❌ Không thể tải ảnh về máy chủ.")
            return

        query_hash = get_image_hash(file_path)
    except Exception as e:
        logger.error(f"Lỗi tải/hash ảnh: {e}")
        await status_msg.edit_text(f"❌ Lỗi xử lý ảnh: {e}")
        return
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        
    if not query_hash:
        await status_msg.edit_text("❌ Không thể trích xuất đặc trưng (hash) từ ảnh này.")
        return
        
    all_images = get_all_images()
    logger.info(f"So sánh với {len(all_images)} ảnh trong Database...")
    results = []
    
    for row in all_images:
        msg_id, chat_id, chat_title, date_ts, link, db_phash = row
        try:
            db_hash_obj = imagehash.hex_to_hash(db_phash)
            similarity = compare_hashes(query_hash, db_hash_obj)
            
            # Ngưỡng tương đồng 85%
            if similarity >= 85.0:
                results.append({
                    "chat_title": chat_title,
                    "date": date_ts,
                    "link": link,
                    "similarity": similarity
                })
        except Exception:
            continue
            
    # Sắp xếp kết quả giảm dần theo độ tương đồng
    results = sorted(results, key=lambda x: x["similarity"], reverse=True)
    
    if not results:
        msg_count = len(all_images)
        await status_msg.edit_text(
            f"❌ Không tìm thấy ảnh tương tự (Ngưỡng ≥ 85%).\n\n"
            f"📊 Dữ liệu hiện có: <b>{msg_count}</b> ảnh trong Database.\n\n"
            f"💡 <i>Gợi ý: Hãy thêm bot vào các nhóm và gõ <code>/scan</code> để lưu thêm ảnh vào hệ thống!</i>"
        )
        return
        
    response_text = f"✅ Tìm thấy {len(results)} ảnh tương tự:\n\n"
    
    # Chỉ hiển thị top 10 kết quả tốt nhất
    for i, res in enumerate(results[:10], 1):
        dt_str = datetime.fromtimestamp(res["date"]).strftime('%d/%m/%Y %H:%M')
        response_text += f"{i}. <b>{res['chat_title']}</b>\n"
        response_text += f"   📅 {dt_str}\n"
        response_text += f"   🎯 Tương đồng: {res['similarity']:.1f}%\n"
        
        link_str = f"<a href='{res['link']}'>Mở tin nhắn</a>" if res["link"] else "Không có link (Nhóm kín)"
        response_text += f"   🔗 {link_str}\n\n"
        
    await status_msg.edit_text(response_text, disable_web_page_preview=True)

# ==========================================
# 2. TỰ ĐỘNG GHI NHẬN ẢNH MỚI TRONG NHÓM
# ==========================================

@bot.on_message(image_filter & (filters.group | filters.channel))
async def bot_index_new_photo(client: Client, message: Message):
    if is_image_indexed(message.id, message.chat.id):
        return

    file_path = None
    try:
        file_path = await message.download()
        if not file_path:
            return
            
        phash = get_image_hash(file_path)
        if phash:
            chat_title = message.chat.title or "Unknown Group"
            save_image_metadata(
                message_id=message.id,
                chat_id=message.chat.id,
                chat_title=chat_title,
                date=int(message.date.timestamp()),
                link=message.link,
                phash=str(phash)
            )
            logger.info(f"[Bot Group] Đã lưu ảnh mới từ nhóm '{chat_title}' (Msg ID: {message.id})")
    except Exception as e:
        logger.error(f"[Bot Group] Lỗi khi index ảnh: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

# ==========================================
# 3. LỆNH /scan QUÉT LỊCH SỬ NHÓM BẰNG BOT
# ==========================================

@bot.on_message(filters.command(["scan", "scan@Img_ha_bot"]) & (filters.group | filters.channel))
async def bot_group_scan(client: Client, message: Message):
    scan_limit = 0
    parts = message.text.strip().split()
    if len(parts) > 1 and parts[1].isdigit():
        scan_limit = int(parts[1])
        status_msg = await message.reply(f"🔄 Đang quét tối đa {scan_limit} tin nhắn gần nhất chứa ảnh...")
    else:
        status_msg = await message.reply("🔄 Bắt đầu quét **TOÀN BỘ** ảnh trong nhóm này...")

    count_new = 0
    count_skipped = 0
    total_checked = 0
    chat_id = message.chat.id
    last_edit_time = time.time()
    
    try:
        async for msg in client.get_chat_history(chat_id, limit=scan_limit):
            total_checked += 1
            if is_image_message(msg):
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
                        logger.warning(f"Telegram FloodWait {fw.value}s")
                        await asyncio.sleep(fw.value)
                    except Exception as e:
                        logger.error(f"Lỗi tải ảnh msg {msg.id}: {e}")
                    finally:
                        if file_path and os.path.exists(file_path):
                            try:
                                os.remove(file_path)
                            except Exception:
                                pass

            # Cập nhật tiến độ sau mỗi 5 giây
            if time.time() - last_edit_time >= 5:
                try:
                    await status_msg.edit_text(
                        f"🔄 **Đang quét lịch sử nhóm...**\n\n"
                        f"• Tin nhắn đã duyệt: **{total_checked}**\n"
                        f"• Ảnh mới đã lưu: **{count_new}**\n"
                        f"• Ảnh đã có trong DB: **{count_skipped}**"
                    )
                    last_edit_time = time.time()
                except Exception:
                    pass

        await status_msg.edit_text(
            f"✅ **ĐÃ HOÀN TẤT QUÉT NHÓM!**\n\n"
            f"• Tổng tin nhắn đã duyệt: **{total_checked}**\n"
            f"• Lưu thành công: **{count_new}** ảnh mới vào Database\n"
            f"• Bỏ qua: **{count_skipped}** ảnh đã tồn tại"
        )
    except FloodWait as fw:
        await asyncio.sleep(fw.value)
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Lỗi khi bot quét nhóm: {e}")
        if "CHAT_ADMIN_REQUIRED" in err_msg or "admin" in err_msg.lower():
            await status_msg.edit_text(
                "⚠️ **Cần cấp quyền Admin cho Bot!**\n\n"
                "Để Bot có thể đọc lịch sử tin nhắn cũ của nhóm, vui lòng thêm Bot làm **Quản trị viên (Admin)** của nhóm nhé."
            )
        else:
            await status_msg.edit_text(f"❌ Lỗi khi quét: {e}")

# ==========================================
# 4. CHÀO MỪNG KHI BOT ĐƯỢC THÊM VÀO NHÓM
# ==========================================

@bot.on_message(filters.new_chat_members)
async def welcome_bot(client: Client, message: Message):
    for new_member in message.new_chat_members:
        if new_member.is_self:
            await message.reply(
                "👋 **Xin chào cả nhóm!** Tôi là bot tìm kiếm và nhận diện ảnh.\n\n"
                "📸 Tôi sẽ tự động ghi nhận các hình ảnh mới gửi vào nhóm để phục vụ tìm kiếm.\n"
                "🔍 **Cách quét lịch sử cũ**: Gõ lệnh `/scan` (nên set Admin cho bot để quét mượt mà).\n"
                "🔎 **Tìm nguồn gốc ảnh**: Nhắn tin riêng cho tôi [@Img_ha_bot] và gửi ảnh cần tra cứu!"
            )

# ==========================================
# 5. CÁC LỆNH CƠ BẢN: /start & /stats
# ==========================================

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    try:
        total_images, total_chats, _ = get_db_stats()
        user_name = message.from_user.first_name if message.from_user else ""
        await message.reply(
            f"👋 Xin chào <b>{user_name}</b>!\n\n"
            f"📸 <b>Tìm kiếm ảnh:</b> Gửi trực tiếp 1 bức ảnh vào đây để tìm nguồn gốc xuất hiện trên các nhóm/kênh.\n\n"
            f"👥 <b>Thêm vào nhóm:</b> Bạn có thể thêm tôi vào bất kỳ nhóm nào và gõ <code>/scan</code> để quét toàn bộ ảnh của nhóm đó vào hệ thống!\n\n"
            f"📊 Thống kê: Đang lưu <b>{total_images}</b> ảnh từ <b>{total_chats}</b> nhóm/kênh.\n\n"
            f"💡 Lệnh: <code>/stats</code> để xem chi tiết kho dữ liệu."
        )
    except Exception as e:
        logger.error(f"Lỗi start_command: {e}")

@bot.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    try:
        total_images, total_chats, top_chats = get_db_stats()
        text = (
            f"📊 <b>THỐNG KÊ DỮ LIỆU HIỆN CÓ</b>\n\n"
            f"🖼️ Tổng số ảnh đã lưu: <b>{total_images}</b> ảnh\n"
            f"👥 Tổng số nhóm/kênh: <b>{total_chats}</b> nhóm\n"
        )
        if top_chats:
            text += "\n🏆 <b>Top nhóm lưu nhiều ảnh nhất:</b>\n"
            for i, (title, count) in enumerate(top_chats, 1):
                text += f"{i}. <b>{title}</b>: {count} ảnh\n"
        else:
            text += "\n<i>(Chưa có ảnh nào trong Database. Dùng lệnh /scan ở nhóm để nạp ảnh nhé!)</i>"
        await message.reply(text)
    except Exception as e:
        logger.error(f"Lỗi stats_command: {e}")

@bot.on_message(filters.text & filters.private & ~filters.command(["start", "stats"]))
async def handle_other_text(client: Client, message: Message):
    await message.reply("📸 Vui lòng gửi cho tôi một **bức ảnh** để tìm kiếm, hoặc gửi `/stats` để xem thống kê dữ liệu!")

# ==========================================
# 6. HÀM MAIN KHỞI CHẠY
# ==========================================

async def main():
    if not API_ID or not API_HASH or not BOT_TOKEN:
        print("Vui lòng cấu hình API_ID, API_HASH và BOT_TOKEN trong file .env")
        return

    # Khởi tạo Database
    init_db()
    
    logger.info("Đang khởi động Bot và User Client...")
    await compose([bot, user])

if __name__ == "__main__":
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\nĐã tắt bot.")
