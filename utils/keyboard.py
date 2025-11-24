"""Keyboard factories compatible with Telethon."""

from __future__ import annotations

from typing import List

from telethon import Button

KeyboardLayout = List[List[Button]]

START_KEYBOARD: KeyboardLayout = [
    [Button.text("🗑 حذف فایل", resize=True), Button.text("🗳 آپلود فایل", resize=True)],
    [Button.text("🗞 حذف کپشن", resize=True), Button.text("📝 تنظیم کپشن", resize=True)],
    [Button.text("🗝 حذف پسورد", resize=True), Button.text("🔐 تنظیم پسورد", resize=True)],
    [Button.text("📂 تاریخچه اپلود", resize=True), Button.text("🗂 شناسه پیگیری فایل", resize=True)],
    [Button.text("🎫 حساب کاربری", resize=True)],
    [Button.text("🛠 سازنده", resize=True)],
]

BACK_KEYBOARD: KeyboardLayout = [[Button.text("🔙 بازگشت", resize=True)]]

ADMIN_KEYBOARD: KeyboardLayout = [
    [Button.text("🎯 عضویت اجباری", resize=True)],
    [Button.text("📭 فوروارد همگانی", resize=True), Button.text("📬 پیام همگانی", resize=True)],
    [Button.text("❌ حذف ادمین", resize=True), Button.text("👥 نمایش لیست ادمین ها", resize=True), Button.text("👤 افزودن ادمین", resize=True)],
    [Button.text("📈آمار", resize=True), Button.text("🔌بک آپ", resize=True)],
]

JOIN_KEYBOARD: KeyboardLayout = [
    [Button.text("▪️ حذف کانال", resize=True), Button.text("▫️ اضافه کردن کانال", resize=True)],
    [Button.text("🔸 لیست کانال ها", resize=True)],
    [Button.text("🔙 بازگشت", resize=True)],
]

UPLOAD_SESSION_KEYBOARD: KeyboardLayout = [
    [Button.text("✅ اتمام ارسال فایل", resize=True)],
    [Button.text("❌ لغو و بازگشت", resize=True)],
]


def channel_join_btn(title: str, url: str) -> Button:
    """Return an inline join button.

    Args:
        title: Visible title presented to the user.
        url: Absolute invite link to the channel.

    Returns:
        Telethon inline button.
    """

    return Button.url(title, url)
