"""Every user-facing string. Handlers format these; they never inline Persian text."""
from __future__ import annotations

from core.enums import BroadcastAudience, BroadcastMode, MediaType

START = """👤 سلام {name}
🤖 به ربات آپلودر خوش امدید!

🏷 اپلود رایگان و دائم فایل ها بدون هیچ محدودیت زمانی !

🚦 شما میتوانید ( عکس , فیلم , گیف , استیکر و ... ) در ربات اپلود کنید همراه با نمایش تعداد دانلود های فایل شما ... !

▪️ شما میتوانید تا سقف یک گیگابایت (1GB) فایل اپلود کنید و لینک فایل خودتون رو دریافت کنید و برای دوستان خود ارسال کنید :

🔐 دقت کنید که میتوانید برای لینک فایل های خودتون رمز بگزارید تا هرکسی نتواند فایلتون رو دانلود کنه , برای دسترسی به فایل وقتی که کاربر با لینک دانلود وارد میشود ربات از او رمز رو درخواست میکند در صورت صحیح بودن رمزی که شما برای فایلتون انتخاب کردید فایل برایش ارسال میشود ... !

📤 همین الان یه فایل بفرس تا آپلود بشه و لذتشو ببر !
"""
ACCOUNT = """💭 حساب کاربری شما در ربات ما :
📤 تعداد فایل های اپلود شده توسط شما : **{links}**
👤 نام اکانت شما : `{name}`
🌟 یوزنیم اکانت شما : `{username}`

🤖@{bot}"""
CREATOR = "👤 سازنده ربات : @{username}"
NEED_JOIN = "برای حمایت از ربات لطفن در کانال های اسپانسر ما جوین شوید و سپس گزینه عضو شدم را بزنید🤗👇"
MAINTENANCE = "♻️ بازیابی در حال انجام است؛ کمی بعد دوباره تلاش کنید."
UNEXPECTED_ERROR = "❌ خطایی رخ داد؛ لطفاً دوباره تلاش کنید."
NO_ACCESS = "دسترسی ندارید."

# ---- asking for a link code ----
ASK_CODE_DELETE = "🗑 لطفا شناسه فایل خود را ارسال کنید ..."
ASK_CODE_CAPTION = "📝 لطفا شناسه فایل خود را ارسال کنید ..."
ASK_CODE_PASSWORD = "🔑 لطفا شناسه فایل خود را ارسال کنید ..."
ASK_CODE_TRACK = "🗂 لطفا شناسه فایل خود را ارسال کنید ..."
ASK_CAPTION = "📝 لطفا کپشن خود را ارسال کنید ..."
ASK_PASSWORD = "🔑 لطفا پسورد خود را ارسال کنید ..."
ASK_LINK_PASSWORD = "🔑 لطفا پسورد فایل را ارسال کنید ..."
INVALID_CODE = "❌ کد فایل نامعتبر است ! لطفا دوباره تلاش کنید:"
LINK_NOT_FOUND_RETRY = "❌ فایل یافت نشد ! لطفا دوباره تلاش کنید:"
LINK_NOT_FOUND = "❌ فایل یافت نشد !"
DELETED = """✅ فایل شما در صورت وجود با موفقیت حذف شد !
🔄 در صورت تمایل می توانید شناسه فایل دیگری ارسال کنید تا از ربات حذف شود و در غیر این صورت از کلید 🔙 بازگشت استفاده کنید"""
CAPTION_SET = "✅ کپشن با موفقیت ثبت شد !"
CAPTION_REMOVED = "✅ کپشن با موفقیت حذف شد !"
PASSWORD_SET = "✅ پسورد با موفقیت ثبت شد !"
PASSWORD_REMOVED = "✅ پسورد با موفقیت حذف شد !"
WRONG_PASSWORD = "❌ پسورد اشتباه است !"

# ---- download ----
LINK_EXPIRED = "⏰ زمان اعتبار این لینک به پایان رسیده است."
LINK_EXHAUSTED = "🚫 سقف دانلود این لینک پر شده است."
DELIVERY_FAILED = "❌ ارسال فایل ناموفق بود؛ لطفاً دوباره تلاش کنید."
DELIVERY_FOOTER = "\n👁 تعداد دانلود : {count}\n❌ این پیام بعد از {seconds} ثانیه حذف می شود\n\n@{bot}"

# ---- upload ----
UPLOAD_START = (
    "📤 فایل‌های خود را ارسال کنید (تکی یا گروهی)...\n\n"
    "💡 می‌توانید چندین فایل پشت سر هم بفرستید\n"
    "✅ بعد از ارسال همه فایل‌ها، دکمه 'اتمام ارسال' را بزنید"
)
UPLOAD_SAVED = """✅ فایل شما ذخیره شد! ({count} فایل)
💾 حجم کل: {size}

📤 فایل های بیشتری ارسال کنید یا از دکمه های زیر استفاده کنید:
• ✅ اتمام ارسال فایل → دریافت لینک اشتراک گذاری
• ❌ لغو و بازگشت → حذف همه و بازگشت به منوی اصلی"""
UPLOAD_UNSUPPORTED = "❌ فایل شما پشتیبانی نمیشود !"
UPLOAD_ALBUM_UNSUPPORTED = "❌ یکی از فایل‌های گروه شما پشتیبانی نمیشود! لطفاً فقط عکس، ویدیو، صوت یا سند ارسال کنید."
UPLOAD_NO_STORAGE = "❌ سرور ذخیره‌سازی تنظیم نشده است! لطفاً STORAGE_CHANNEL_ID را در .env تنظیم کنید."
UPLOAD_STORE_FAILED = "❌ خطا در ذخیره‌سازی فایل! لطفاً دوباره تلاش کنید."
UPLOAD_TOO_MANY = "❌ حداکثر {limit} فایل در هر لینک مجاز است؛ «✅ اتمام ارسال فایل» را بزنید."
UPLOAD_EMPTY = "❌ هیچ فایلی برای ذخیره یافت نشد!"
UPLOAD_ASK_LIMITS = (
    "🔐 محدودیت لینک را مشخص کنید.\n"
    "فرمت: `تعداد_روز تعداد_دانلود`\n"
    "نمونه: `7 3` (هفت روز یا سه دانلود؛ هرکدام زودتر برسد)\n"
    "برای حذف هرکدام، به‌جای آن `-` بگذارید؛ نمونه: `7 -`."
)
UPLOAD_LIMITS_FORMAT = "❌ فرمت نادرست است. نمونه: `7 3` یا `7 -` یا «بدون محدودیت»."
UPLOAD_LIMITS_POSITIVE = "❌ تعداد روز و دانلود باید عدد مثبت باشند."
UPLOAD_STILL_OPEN = (
    "فایل‌ها هنوز در جلسهٔ آپلود هستند؛ برای ادامه «✅ اتمام ارسال فایل» یا برای حذف «❌ لغو و بازگشت» را بزنید."
)
UPLOAD_SAVE_FAILED = "❌ خطا در ذخیره‌سازی نهایی! لطفاً دوباره تلاش کنید."
UPLOAD_CANCELLED = """❌ آپلود لغو شد!
🗑 {count} فایل از لیست حذف شدند.
🔙 به منوی اصلی برگشتید."""
UPLOAD_DONE = """🎉 فایل های شما با موفقیت آپلود شدند!

📊 خلاصه آپلود:
{summary}

💾 حجم کل: {size}

🔗 لینک اشتراک گذاری:
📥 {url}

💡 با این لینک تمام فایل‌ها به ترتیب ارسال می‌شوند!"""

# ---- link details ----
TRACK = """🗂 **اطلاعات فایل**

▪️ شناسه: `{code}`
{kind}
💾 حجم: {size}
🗞 کپشن: {caption}
🔐 رمز: {password}
👁 دانلود: {downloads} بار
⏰ اعتبار لینک: {expires}
🎯 سقف دانلود: {max_downloads}
🕓 تاریخ آپلود: {created}

📥 لینک اشتراک گذاری:
{url}"""
HISTORY_TITLE = "📂 **تاریخچه آپلود** (صفحه {page} از {pages} | {total} لینک)\n━━━━━━━━━━━━━━━━━━━━"
HISTORY_ITEM = """{index}. شناسه: `{code}`
• نوع: {kind}
• 💾 حجم: {size}
• 📅 تاریخ: {created}
• 👁 دانلود: {downloads} بار
• ⏰ اعتبار: {expires}
• 🎯 سقف دانلود: {max_downloads}
• 🔗 {url}"""
HISTORY_SEPARATOR = "\n────────────────────\n"
NO_EXPIRY = "بدون انقضا"
NO_LIMIT = "بدون محدودیت"
NONE = "ندارد"
HAS_PASSWORD = "دارد ✅"

MEDIA_LABELS: dict[MediaType, tuple[str, str]] = {
    MediaType.PHOTO: ("📷", "عکس"),
    MediaType.VIDEO: ("🎬", "ویدیو"),
    MediaType.ANIMATION: ("🎞", "گیف"),
    MediaType.AUDIO: ("🎧", "آهنگ"),
    MediaType.VOICE: ("🎤", "صوتی"),
    MediaType.STICKER: ("🏷", "استیکر"),
    MediaType.DOCUMENT: ("📄", "مدرک"),
}

# ---- admin ----
ADMIN_PANEL = "👤 سلام {name} \n🤖 به پنل ادمین خوش امدید !"
ASK_ADMIN_ID_ADD = "👤 لطفا آیدی عددی ادمین جدید را ارسال کنید ..."
ASK_ADMIN_ID_REMOVE = "👤 لطفا آیدی عددی ادمین را ارسال کنید ..."
INVALID_NUMERIC_ID = "❌ لطفا آیدی عددی معتبر ارسال کنید !"
ADMIN_ADDED = "✅ ادمین با موفقیت افزوده شد !"
ADMIN_REMOVED = "✅ ادمین با موفقیت حذف شد !"
USER_NOT_FOUND = "❌ کاربر یافت نشد !"
ADMIN_LIST_TITLE = "👥 لیست ادمین ها : \n\n"
ADMIN_LIST_ITEM = "👤 {name} \n🆔 {user_id} \n\n"
STATS = (
    "📊 آمار ربات\n\n"
    "👥 کاربران: {s.total_users:,}\n"
    "🆕 کاربر جدید ۲۴ ساعت اخیر: {s.new_today:,}\n"
    "📈 رشد هفتگی: {s.week_growth:+,}\n"
    "📤 فایل‌ها: {s.total_links:,} (امروز: {s.links_today:,})\n"
    "👁 دانلودها: {s.downloads:,}\n"
    "🔗 بازدید لینک امروز: {s.views_today:,}\n"
    "📨 ارسال‌های همگانی: {s.broadcasts:,}\n"
    "✅ نرخ موفقیت ارسال: {s.delivery_rate:.1f}%"
)
ASK_USER_LOG_ID = "📜 شناسهٔ عددی کاربر را ارسال کنید."
INVALID_USER_ID = "❌ شناسهٔ عددی معتبر نیست."
USER_LOG_EMPTY = "📜 لاگ کاربر `{user_id}`\n\nهنوز هیچ لینک فایلی را مشاهده نکرده است."
USER_LOG_UNKNOWN = "❌ کاربری با این شناسه در دیتابیس پیدا نشد."
USER_LOG_TITLE = (
    "📜 لاگ بازدید کاربر `{user_id}`\n📅 ثبت‌نام: {created}\n🟢 آخرین فعالیت: {active}\n"
    "🔗 {total:,} لینک یکتا | صفحه {page} از {pages}\n━━━━━━━━━━━━━━━━━━━━"
)
USER_LOG_ITEM = "{index}. کد: `{code}`\n   👁 مشاهده: {views:,} بار\n   🕓 آخرین بازدید: {last_viewed}"

# ---- mandatory channels ----
JOIN_PANEL = "👤 سلام {name} \n🤖 به پنل عضویت اجباری خوش امدید !"
CHANNEL_LIST_TITLE = "📃 لیست کانال های عضویت اجباری شما :\n"
CHANNEL_LIST_ITEM = "🔗 لینک کانال : {link}\n🧷 آیدی عددی کانال : {ref}\n"
NO_CHANNELS = "❌ هیچ کانالی یافت نشد !"
ASK_CHANNEL_ADD = """💠اگر میخواهید روی کانال خصوصی جوین اجباری بزارید
لینک کانال رو در خط اول و
ایدی عددی کانال رو در خط دوم وارد کنید
رای بدست اوردن ایدی عددی کانال ی پیام کانال رو برای ربات @userinfobot فروارد کنید
مثال:

https://t.me/joinchat/AAAAAFaBB5ttFuBMdxMJJw
-12345678910

--------
اگر می خواهید برای کانال عمومی جوین اجباری بزارید

لطفا آیدی کانال مورد نظر را با @ ارسال کنید

👈🏻 توجه : ربات باید مدیر کانال مورد نظر باشد!
"""
CHANNEL_FORMAT = "❌ قالب ورودی نادرست است؛ لینک و آیدی عددی را در دو خط، یا آیدی عمومی را با @ بفرستید."
CHANNEL_UNREACHABLE = "❌ ربات به این کانال دسترسی ندارد؛ ربات را مدیر کانال کنید و دوباره تلاش کنید."
CHANNEL_EXISTS = "❌ این کانال قبلاً اضافه شده است."
CHANNEL_ADDED = "✅ کانال با موفقیت اضافه شد !"
ASK_CHANNEL_REMOVE = "🔗 لطفا آیدی عددی کانال را ارسال کنید ..."
CHANNEL_REMOVED = "✅ کانال با موفقیت حذف شد !"
CHANNEL_NOT_FOUND = "❌ کانال یافت نشد !"

# ---- global caption ----
CAPTION_PANEL = """👤 سلام {name}
🗞 به پنل کپشن عمومی خوش امدید !

📝 کپشن عمومی فعلی:
{caption}

🖇 نمایش کپشن اختصاصی فایل‌ها: {status}"""
CAPTION_UNSET = "تنظیم نشده"
CAPTION_ON = "🟢 روشن"
CAPTION_OFF = "🔴 خاموش"
ASK_GLOBAL_CAPTION = "📝 لطفا متن کپشن عمومی را ارسال کنید ..."
GLOBAL_CAPTION_SET = "✅ کپشن عمومی با موفقیت ثبت شد !"
GLOBAL_CAPTION_REMOVED = "✅ کپشن عمومی با موفقیت حذف شد !"

# ---- broadcast ----
ASK_BROADCAST_FORWARD = "📭 لطفا پیام خود را ارسال کنید ..."
ASK_BROADCAST_COPY = "📬 لطفا پیام خود را ارسال کنید ..."
BROADCAST_NO_ALBUM = "❌ آلبوم در ارسال همگانی پشتیبانی نمی‌شود."
ASK_AUDIENCE = "🎯 مخاطبان این ارسال را انتخاب کنید:"
INVALID_AUDIENCE = "❌ یکی از گزینه‌های مخاطبان را انتخاب کنید."
ASK_BROADCAST_CHANNEL = "📢 شناسه یا یوزرنیم کانال را بفرستید؛ مانند `@channel` یا `-100...`."
BROADCAST_CHANNEL_INVALID = "❌ کانال بررسی نشد؛ شناسه را دوباره بفرستید."
BROADCAST_EMPTY = "❌ هیچ مخاطبی برای این دسته‌بندی پیدا نشد."
BROADCAST_PREVIEW = (
    "🔎 پیش‌نمایش ارسال همگانی\n\n"
    "📨 نوع: {mode}\n"
    "🎯 مخاطب: {audience}\n"
    "👥 تعداد دریافت‌کننده: {count:,}{note}\n\n"
    "پیام موردنظر در پیام قبلی شماست. ارسال را تأیید یا زمان‌بندی کنید."
)
BROADCAST_CHANNEL_NOTE = "\n(عضویت در کانال هنگام ارسال بررسی می‌شود)"
BROADCAST_QUEUED = "✅ ارسال در صف قرار گرفت؛ گزارش پیشرفت برای شما ارسال می‌شود."
BROADCAST_QUEUED_BUSY = "⏳ یک ارسال همگانی دیگر در حال انجام است؛ این ارسال پس از آن آغاز می‌شود."
ASK_SCHEDULE = "🗓 زمان ارسال را با فرمت `YYYY-MM-DD HH:MM` و ساعت ایران بفرستید.\nنمونه: `2026-08-05 09:30`"
INVALID_SCHEDULE = "❌ زمان نامعتبر است یا در گذشته قرار دارد."
BROADCAST_SCHEDULED = "✅ ارسال برای {when} زمان‌بندی شد."
BROADCAST_CANCEL_REQUESTED = "⏳ درخواست لغو ثبت شد؛ ارسال‌های در صف متوقف می‌شوند."
BROADCAST_CANCELLED = "✅ ارسال لغو شد."
BROADCAST_STARTED = "⏳ ارسال آغاز شد: ۰ از {total:,}\nبرای توقف، «❌ لغو ارسال» را بزنید."
BROADCAST_PROGRESS = "⏳ ارسال در حال انجام است: {done:,} از {total:,}\n✅ موفق: {ok:,}\n❌ ناموفق: {failed:,}"
BROADCAST_FINISHED = "{label}\n✅ موفق: {ok:,}\n❌ ناموفق: {failed:,}\n📊 پردازش‌شده: {done:,} از {total:,}"
BROADCAST_DONE_LABEL = "✅ ارسال پایان یافت"
BROADCAST_CANCELLED_LABEL = "⛔ ارسال لغو شد"
BROADCAST_FAILED = "❌ ارسال همگانی با خطا متوقف شد."
BROADCAST_REPORT = "📄 گزارش کامل ارسال همگانی"
BROADCAST_OK = "موفق"
BROADCAST_ERROR = "ناموفق"
MODE_LABELS = {BroadcastMode.FORWARD: "فوروارد", BroadcastMode.COPY: "کپی پیام"}
AUDIENCE_LABELS = {
    BroadcastAudience.ALL: "همه کاربران",
    BroadcastAudience.NEW: "کاربران جدید",
    BroadcastAudience.ACTIVE: "کاربران فعال",
    BroadcastAudience.INACTIVE: "کاربران غیرفعال",
    BroadcastAudience.CHANNEL: "اعضای کانال",
}

# ---- backups ----
BACKUP_STARTED = "⏳ ساخت بک‌آپ آغاز شد؛ فایل پس از آماده شدن ارسال می‌شود."
FULL_BACKUP_CAPTION = "📤 دامپ کامل دیتابیس ربات (schema و داده‌ها)"
FULL_BACKUP_FAILED = "❌ مشکلی در ایجاد بک آپ رخ داده است !"
DATA_BACKUP_CAPTION = "📦 بک‌آپ فقط داده‌ها؛ قابل بازیابی روی PostgreSQL و SQLite"
DATA_BACKUP_FAILED = "❌ ساخت بک‌آپ داده‌ها ناموفق بود."
ASK_RESTORE_FILE = (
    "بک‌آپ دادهٔ ربات (`jsonl.gz`) را ارسال کنید؛ بک‌آپ‌های نسخهٔ قبلی ربات هم پذیرفته می‌شوند.\n"
    "پس از بررسی فایل، تعداد رکوردها نمایش داده می‌شود. با تأیید شما داده‌های فعلی جایگزین می‌شوند."
)
RESTORE_NEED_DOCUMENT = "لطفاً فایل بک‌آپ را به صورت document ارسال کنید."
RESTORE_TOO_LARGE = "❌ حجم بک‌آپ بیش از حد مجاز است."
RESTORE_CHECKING = "⏳ فایل دریافت شد و در حال بررسی است..."
RESTORE_PREVIEW = (
    "فایل بررسی شد. نسخهٔ قالب بک‌آپ: {version}\n{counts}\n\n"
    "با تأیید، تمام داده‌های فعلی ربات جایگزین می‌شوند. یک نسخهٔ ایمنی از داده‌های فعلی نیز ذخیره می‌شود."
)
RESTORE_EXPIRED = "پیش‌نمایش منقضی شده است؛ بک‌آپ را دوباره ارسال کنید."
RESTORE_BROADCAST_RUNNING = "❌ ابتدا ارسال همگانی فعال را تمام یا لغو کنید."
RESTORE_RUNNING = "⏳ بازیابی آغاز شد؛ پس از پایان به شما اطلاع داده می‌شود."
RESTORE_DONE = "✅ بازیابی انجام شد. این فایل نسخهٔ ایمنیِ داده‌های قبل از بازیابی است."
RESTORE_FAILED = "❌ بازیابی ناموفق بود؛ داده‌های فعلی حفظ شدند."
RESTORE_INVALID = "❌ {reason}"


def media_summary(type_counts: dict[MediaType, int]) -> str:
    return "\n".join(
        f"{MEDIA_LABELS[media_type][0]} {MEDIA_LABELS[media_type][1]}: {count}"
        for media_type, count in type_counts.items()
    )


def media_kind(type_counts: dict[MediaType, int]) -> str:
    """"📷 عکس" for one item, "📦 آلبوم (3 فایل | 2 عکس, 1 ویدیو)" for several."""
    total = sum(type_counts.values())
    if total == 1:
        icon, label = MEDIA_LABELS[next(iter(type_counts))]
        return f"{icon} {label}"
    parts = ", ".join(f"{count} {MEDIA_LABELS[kind][1]}" for kind, count in type_counts.items())
    return f"📦 آلبوم ({total} فایل | {parts})"


def file_size(size: int) -> str:
    for unit, scale in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size >= scale:
            return f"{size / scale:.1f} {unit}"
    return f"{size} B"
