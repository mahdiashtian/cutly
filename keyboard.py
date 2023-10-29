from pyrogram.types import (ReplyKeyboardMarkup)

start_btn = ReplyKeyboardMarkup(
    [
        ["🗑 حذف فایل", "🗳 آپلود فایل"],
        ["🗞 حذف کپشن", "📝 تنظیم کپشن"],
        ["🗝 حذف پسورد", "🔐 تنظیم پسورد"],
        ["📂 تاریخچه اپلود", "🗂 کد پیگیری فایل"],
        ["🎫 حساب کاربری"],
        ["🛠 سازنده"]
    ], resize_keyboard=True
)

back_btn = ReplyKeyboardMarkup(
    [["🔙 بازگشت"]], resize_keyboard=True
)

admin_btn = ReplyKeyboardMarkup(
    [
        ["🎯 عضویت اجباری"],
        ["📭 فوروارد همگانی", "📬 پیام همگانی"],
        ["❌ حذف ادمین", "👥 نمایش لیست ادمین ها", "👤 افزودن ادمین"],
        ["📈آمار", "🔌بک آپ"]
    ]
)
