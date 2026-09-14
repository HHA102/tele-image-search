import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
from datetime import datetime
import imagehash
from pyrogram import Client, filters, compose
from pyrogram.types import Message

from config import API_ID, API_HASH, BOT_TOKEN
from database import init_db, get_all_images
from image_matcher import get_image_hash, compare_hashes
from scanner import register_user_handlers

# Khởi tạo 2 client: Bot để giao tiếp, User để quét
bot = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("user_session", api_id=API_ID, api_hash=API_HASH)

# Đăng ký các handler của User client
register_user_handlers(user)

@bot.on_message(filters.photo & filters.private)
async def handle_query_photo(client: Client, message: Message):
    status_msg = await message.reply("🔍 Đang tìm kiếm...")
    
    # Tải ảnh do user gửi tới bot
    file_path = await message.download()
    
    query_hash = get_image_hash(file_path)
    
    # Xóa file sau khi hash
    if os.path.exists(file_path):
        os.remove(file_path)
        
    if not query_hash:
        await status_msg.edit_text("❌ Lỗi khi xử lý ảnh query.")
        return
        
    # Lấy toàn bộ hash trong DB
    all_images = get_all_images()
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
        await status_msg.edit_text("❌ Không tìm thấy ảnh tương tự. Hãy đảm bảo User account của bạn đã nhận được ảnh từ các nhóm/channel (hoặc dùng lệnh .scan ở User account).")
        return
        
    response_text = f"✅ Tìm thấy {len(results)} ảnh tương tự\n\n"
    
    # Chỉ hiển thị top 10 kết quả tốt nhất
    for i, res in enumerate(results[:10], 1):
        dt_str = datetime.fromtimestamp(res["date"]).strftime('%d/%m/%Y %H:%M')
        response_text += f"{i}. {res['chat_title']}\n"
        response_text += f"   📅 {dt_str}\n"
        response_text += f"   🎯 Similarity: {res['similarity']:.1f}%\n"
        
        link_str = res["link"] if res["link"] else "Không có link (Nhóm kín)"
        response_text += f"   🔗 {link_str}\n\n"
        
    await status_msg.edit_text(response_text, disable_web_page_preview=True)

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    await message.reply("Xin chào! Hãy gửi cho tôi 1 bức ảnh để tôi tìm kiếm trong các nhóm/channel mà tài khoản của bạn đang quét.")

async def main():
    if not API_ID or not API_HASH or not BOT_TOKEN:
        print("Vui lòng cấu hình API_ID, API_HASH và BOT_TOKEN trong file .env")
        return

    # Khởi tạo Database
    init_db()
    
    print("Khởi động Bot và User Client...")
    # Chạy song song cả Bot và User Client
    await compose([bot, user])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Đã tắt bot.")

