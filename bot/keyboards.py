"""Reply keyboards and every button label.

Labels are constants so a handler and its keyboard can never drift apart: a
typo would be a NameError, not a button that silently does nothing.
"""
from __future__ import annotations

from telethon import Button


class Btn:
    # ---- user menu ----
    UPLOAD = "🗳 آپلود فایل"
    DELETE = "🗑 حذف فایل"
    SET_CAPTION = "📝 تنظیم کپشن"
    UNSET_CAPTION = "🗞 حذف کپشن"
    SET_PASSWORD = "🔐 تنظیم پسورد"
    UNSET_PASSWORD = "🗝 حذف پسورد"
    TRACK = "🗂 شناسه پیگیری فایل"
    HISTORY = "📂 تاریخچه اپلود"
    ACCOUNT = "🎫 حساب کاربری"
    CREATOR = "🛠 سازنده"
    BACK = "🔙 بازگشت"
    # ---- upload session ----
    FINISH_UPLOAD = "✅ اتمام ارسال فایل"
    CANCEL_UPLOAD = "❌ لغو و بازگشت"
    NO_LIMIT = "بدون محدودیت"
    # ---- admin panel ----
    JOIN_PANEL = "🎯 عضویت اجباری"
    CAPTION_PANEL = "🗞 کپشن عمومی"
    FORWARD_ALL = "📭 فوروارد همگانی"
    COPY_ALL = "📬 پیام همگانی"
    REMOVE_ADMIN = "❌ حذف ادمین"
    LIST_ADMINS = "👥 نمایش لیست ادمین ها"
    ADD_ADMIN = "👤 افزودن ادمین"
    STATS = "📈آمار"
    FULL_BACKUP = "🔌بک آپ"
    USER_LOG = "📜 لاگ کاربر"
    DATA_BACKUP = "📦 بک‌آپ داده‌ها"
    RESTORE = "♻️ بازیابی بک‌آپ"
    CONFIRM_RESTORE = "✅ تأیید بازیابی"
    # ---- mandatory channels ----
    LIST_CHANNELS = "🔸 لیست کانال ها"
    ADD_CHANNEL = "▫️ اضافه کردن کانال"
    REMOVE_CHANNEL = "▪️ حذف کانال"
    # ---- global caption ----
    SET_GLOBAL_CAPTION = "✏️ تنظیم کپشن عمومی"
    UNSET_GLOBAL_CAPTION = "🗑 حذف کپشن عمومی"
    TOGGLE_FILE_CAPTIONS = "🔁 روشن/خاموش کپشن فایل‌ها"
    # ---- broadcast ----
    AUDIENCE_ALL = "👥 همه کاربران"
    AUDIENCE_NEW = "🆕 کاربران جدید"
    AUDIENCE_ACTIVE = "🟢 کاربران فعال"
    AUDIENCE_INACTIVE = "⚪ کاربران غیرفعال"
    AUDIENCE_CHANNEL = "📢 اعضای کانال"
    SEND_NOW = "✅ ارسال فوری"
    SCHEDULE = "🗓 زمان‌بندی ارسال"
    CANCEL_BROADCAST = "❌ لغو ارسال"
    JOINED = "✅ عضو شدم"


def _keyboard(*rows: tuple[str, ...]) -> list[list[Button]]:
    return [[Button.text(label, resize=True) for label in row] for row in rows]


MAIN = _keyboard(
    (Btn.DELETE, Btn.UPLOAD),
    (Btn.UNSET_CAPTION, Btn.SET_CAPTION),
    (Btn.UNSET_PASSWORD, Btn.SET_PASSWORD),
    (Btn.HISTORY, Btn.TRACK),
    (Btn.ACCOUNT,),
    (Btn.CREATOR,),
)
BACK = _keyboard((Btn.BACK,))
UPLOAD_SESSION = _keyboard((Btn.FINISH_UPLOAD,), (Btn.CANCEL_UPLOAD,))
UPLOAD_LIMITS = _keyboard((Btn.NO_LIMIT,), (Btn.BACK,))
ADMIN = _keyboard(
    (Btn.JOIN_PANEL, Btn.CAPTION_PANEL),
    (Btn.FORWARD_ALL, Btn.COPY_ALL),
    (Btn.REMOVE_ADMIN, Btn.LIST_ADMINS, Btn.ADD_ADMIN),
    (Btn.STATS, Btn.FULL_BACKUP),
    (Btn.USER_LOG,),
    (Btn.DATA_BACKUP, Btn.RESTORE),
)
JOIN_PANEL = _keyboard((Btn.REMOVE_CHANNEL, Btn.ADD_CHANNEL), (Btn.LIST_CHANNELS,), (Btn.BACK,))
CAPTION_PANEL = _keyboard(
    (Btn.SET_GLOBAL_CAPTION, Btn.UNSET_GLOBAL_CAPTION), (Btn.TOGGLE_FILE_CAPTIONS,), (Btn.BACK,)
)
BROADCAST_AUDIENCE = _keyboard(
    (Btn.AUDIENCE_ALL, Btn.AUDIENCE_NEW),
    (Btn.AUDIENCE_ACTIVE, Btn.AUDIENCE_INACTIVE),
    (Btn.AUDIENCE_CHANNEL,),
    (Btn.BACK,),
)
BROADCAST_CONFIRM = _keyboard((Btn.SEND_NOW, Btn.SCHEDULE), (Btn.CANCEL_BROADCAST,))
RESTORE_CONFIRM = _keyboard((Btn.CONFIRM_RESTORE,), (Btn.BACK,))


def pager(prefix: str, page: int, page_count: int) -> list[list[Button]] | None:
    """◀️/▶️ inline navigation; the callback data is ``<prefix>:<page>``."""
    row = []
    if page > 0:
        row.append(Button.inline("◀️ قبلی", data=f"{prefix}:{page - 1}".encode()))
    if page + 1 < page_count:
        row.append(Button.inline("بعدی ▶️", data=f"{prefix}:{page + 1}".encode()))
    return [row] if row else None
