#!/usr/bin/env python3
"""
🎓 بوت تلغرام ذكي لمساعدة الطلاب
يستخدم 8 نماذج ذكاء اصطناعي متكاملة
"""

import logging
import asyncio
import json
import sqlite3
import requests
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError
import PyPDF2
import docx
import io
import sympy as sp
from scipy import optimize, integrate
import numpy as np

logging.basicConfig(
    format='%(asctime)s - [%(levelname)s] - %(name)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# تعطيل رسائل httpx المزعجة
logging.getLogger("httpx").setLevel(logging.WARNING)

# تسجيل بدء البوت
logger.info("=" * 50)
logger.info("🚀 بدء تشغيل البوت التعليمي")
logger.info("=" * 50)

# ضع التوكن الخاص بك هنا مباشرة
TELEGRAM_BOT_TOKEN = "7848268331:AAFL061-98fzllsZlbpYxLO0otYxGT1-TW4"

if not TELEGRAM_BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN غير محدد!")
    import sys
    sys.exit(1)

ADMIN_ID = int(os.getenv("ADMIN_ID", "7401831506"))
if ADMIN_ID == 0:
    logger.warning("⚠️ ADMIN_ID غير محدد - لن تتمكن من استخدام لوحة التحكم")

SUPER_ADMINS = [ADMIN_ID]
ADMINS = []

try:
    extra_admins_str = os.getenv("EXTRA_ADMINS", "")
    if extra_admins_str:
        ADMINS = [int(x.strip()) for x in extra_admins_str.split(",") if x.strip()]
        logger.info(f"✅ تم إضافة {len(ADMINS)} أدمن إضافي")
except Exception as e:
    logger.error(f"❌ خطأ في قراءة EXTRA_ADMINS: {e}")

ALL_ADMINS = list(set(SUPER_ADMINS + ADMINS))

def is_super_admin(user_id: int) -> bool:
    """
    التحقق من صلاحيات الأدمن العام (للوصول إلى لوحة التحكم العامة)
    
    Args:
        user_id: معرف المستخدم
    
    Returns:
        True إذا كان المستخدم أدمن عام
    """
    return user_id in ALL_ADMINS

def is_group_admin(user_id: int, group_id: int) -> bool:
    """
    التحقق من صلاحيات أدمن المجموعة
    
    Args:
        user_id: معرف المستخدم
        group_id: معرف المجموعة
    
    Returns:
        True إذا كان المستخدم أدمن عام أو أدمن المجموعة
    """
    # الأدمن العام لديه صلاحيات في جميع المجموعات
    if user_id in ALL_ADMINS:
        return True
    
    # التحقق من أدمن المجموعة من قاعدة البيانات
    return db.is_group_admin(user_id, group_id)

REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@boyta28")

SUBSCRIPTION_LIMITS = {
    'free': {
        'daily_images': 10,
        'daily_videos': 3,
        'daily_messages': 100
    },
    'premium': {
        'daily_images': 100,
        'daily_videos': 30,
        'daily_messages': 1000
    }
}

# استخدام threading.Lock لضمان عدم التعارض في الذاكرة المؤقتة
import threading

in_memory_users = {}
in_memory_conversations = defaultdict(list)
user_rate_limit = {}
memory_lock = threading.Lock()

class Database:
    """إدارة قاعدة البيانات"""

    def __init__(self, use_database=True):
        self.use_database = use_database
        self.lock = threading.Lock()  # قفل للعمليات الحرجة
        if self.use_database:
            try:
                logger.info("🗄️ محاولة الاتصال بقاعدة البيانات...")
                self.conn = sqlite3.connect('bot_database.db', check_same_thread=False)
                self.create_tables()
                logger.info("✅ تم الاتصال بقاعدة البيانات بنجاح")
            except Exception as e:
                logger.error(f"❌ فشل الاتصال بقاعدة البيانات: {type(e).__name__} - {str(e)}")
                logger.warning("⚠️ التبديل إلى الذاكرة المؤقتة")
                self.use_database = False
                self.conn = None
        else:
            logger.info("💾 استخدام الذاكرة المؤقتة فقط")
            self.conn = None

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_banned INTEGER DEFAULT 0,
                is_muted INTEGER DEFAULT 0,
                message_count INTEGER DEFAULT 0,
                joined_at TEXT,
                last_activity TEXT,
                subscription_tier TEXT DEFAULT 'free',
                daily_quota_used INTEGER DEFAULT 0,
                daily_video_quota INTEGER DEFAULT 0,
                last_quota_reset TEXT,
                preferred_language TEXT DEFAULT 'ar',
                last_message_time REAL DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY,
                total_messages INTEGER DEFAULT 0,
                total_users INTEGER DEFAULT 0,
                last_updated TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                user_id INTEGER,
                chat_id INTEGER,
                message TEXT,
                response TEXT,
                timestamp TEXT
            )
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO stats (id, total_messages, total_users)
            VALUES (1, 0, 0)
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_settings (
                group_id INTEGER PRIMARY KEY,
                group_name TEXT,
                auto_moderation INTEGER DEFAULT 1,
                delete_profanity INTEGER DEFAULT 1,
                warn_on_profanity INTEGER DEFAULT 1,
                max_warnings INTEGER DEFAULT 3,
                added_at TEXT,
                last_updated TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                group_id INTEGER,
                reason TEXT,
                warned_at TEXT,
                warned_by INTEGER
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_admins (
                group_id INTEGER,
                user_id INTEGER,
                added_at TEXT,
                added_by INTEGER,
                permissions TEXT DEFAULT 'moderate',
                PRIMARY KEY (group_id, user_id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS profanity_detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                group_id INTEGER,
                message_text TEXT,
                detected_words TEXT,
                action_taken TEXT,
                detected_at TEXT
            )
        ''')
        
        self.conn.commit()

    def add_or_update_user(self, user_id: int, username: str, first_name: str):
        if not self.use_database or not self.conn:
            with memory_lock:
                if user_id not in in_memory_users:
                    in_memory_users[user_id] = {
                        'username': username,
                        'first_name': first_name,
                        'message_count': 1
                    }
                else:
                    in_memory_users[user_id]['message_count'] += 1
            return
        try:
            with self.lock:
                cursor = self.conn.cursor()
                now = datetime.now().isoformat()
                cursor.execute('''
                    INSERT INTO users (user_id, username, first_name, joined_at, last_activity, message_count)
                    VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(user_id) DO UPDATE SET
                        username = excluded.username,
                        first_name = excluded.first_name,
                        last_activity = excluded.last_activity,
                        message_count = message_count + 1
                ''', (user_id, username, first_name, now, now))
                self.conn.commit()
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")

    def add_conversation(self, user_id: int, message: str, response: str, chat_id: int = 0):
        if not self.use_database or not self.conn:
            with memory_lock:
                key = (user_id, chat_id)
                in_memory_conversations[key].append((message, response))
                if len(in_memory_conversations[key]) > 10:
                    in_memory_conversations[key] = in_memory_conversations[key][-10:]
            return
        try:
            with self.lock:
                cursor = self.conn.cursor()
                now = datetime.now().isoformat()
                cursor.execute('''
                    INSERT INTO conversations (user_id, chat_id, message, response, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, chat_id, message, response, now))
                self.conn.commit()

                cursor.execute('''
                    DELETE FROM conversations WHERE user_id = ? AND chat_id = ? AND timestamp NOT IN (
                        SELECT timestamp FROM conversations WHERE user_id = ? AND chat_id = ?
                        ORDER BY timestamp DESC LIMIT 10
                    )
                ''', (user_id, chat_id, user_id, chat_id))
                self.conn.commit()
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")

    def get_conversation_history(self, user_id: int, chat_id: int = 0, limit: int = 5) -> list:
        if not self.use_database or not self.conn:
            key = (user_id, chat_id)
            history = in_memory_conversations.get(key, [])
            return history[-limit:] if history else []
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT message, response FROM conversations 
                WHERE user_id = ? AND chat_id = ?
                ORDER BY timestamp DESC LIMIT ?
            ''', (user_id, chat_id, limit))
            results = cursor.fetchall()
            return list(reversed(results))
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")
            return []

    def check_and_reset_quota(self, user_id: int):
        """التحقق وإعادة تعيين الحصة اليومية"""
        if not self.use_database or not self.conn:
            if user_id in in_memory_users:
                user = in_memory_users[user_id]
                last_reset = datetime.fromisoformat(user.get('last_quota_reset', datetime.now().isoformat()))
                now = datetime.now()
                if (now - last_reset).days >= 1:
                    user['daily_quota_used'] = 0
                    user['daily_video_quota'] = 0
                    user['last_quota_reset'] = now.isoformat()
            return

        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT last_quota_reset FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if result:
                last_reset = datetime.fromisoformat(result[0]) if result[0] else datetime.now()
                now = datetime.now()
                if (now - last_reset).days >= 1:
                    cursor.execute('''
                        UPDATE users SET daily_quota_used = 0, daily_video_quota = 0, last_quota_reset = ?
                        WHERE user_id = ?
                    ''', (now.isoformat(), user_id))
                    self.conn.commit()
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")

    def get_user_quota(self, user_id: int) -> Dict[str, Any]:
        """الحصول على معلومات حصة المستخدم"""
        if not self.use_database or not self.conn:
            if user_id in in_memory_users:
                user = in_memory_users[user_id]
                return {
                    'tier': user.get('subscription_tier', 'free'),
                    'daily_used': user.get('daily_quota_used', 0),
                    'daily_video_used': user.get('daily_video_quota', 0)
                }
            return {'tier': 'free', 'daily_used': 0, 'daily_video_used': 0}

        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT subscription_tier, daily_quota_used, daily_video_quota
                FROM users WHERE user_id = ?
            ''', (user_id,))
            result = cursor.fetchone()
            if result:
                return {
                    'tier': result[0] or 'free',
                    'daily_used': result[1] or 0,
                    'daily_video_used': result[2] or 0
                }
            return {'tier': 'free', 'daily_used': 0, 'daily_video_used': 0}
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")
            return {'tier': 'free', 'daily_used': 0, 'daily_video_used': 0}

    def increment_quota(self, user_id: int, quota_type: str = 'image'):
        """زيادة عداد الحصة"""
        if not self.use_database or not self.conn:
            if user_id in in_memory_users:
                if quota_type == 'video':
                    in_memory_users[user_id]['daily_video_quota'] = in_memory_users[user_id].get('daily_video_quota', 0) + 1
                else:
                    in_memory_users[user_id]['daily_quota_used'] = in_memory_users[user_id].get('daily_quota_used', 0) + 1
            return

        try:
            cursor = self.conn.cursor()
            if quota_type == 'video':
                cursor.execute('''
                    UPDATE users SET daily_video_quota = daily_video_quota + 1
                    WHERE user_id = ?
                ''', (user_id,))
            else:
                cursor.execute('''
                    UPDATE users SET daily_quota_used = daily_quota_used + 1
                    WHERE user_id = ?
                ''', (user_id,))
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")

    def get_all_user_ids(self) -> List[int]:
        """الحصول على جميع معرفات المستخدمين (فقط المستخدمين غير المحظورين)"""
        if not self.use_database or not self.conn:
            return list(in_memory_users.keys())
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT user_id FROM users WHERE is_banned = 0 OR is_banned IS NULL')
            user_ids = [row[0] for row in cursor.fetchall()]
            logger.info(f"Found {len(user_ids)} active users for broadcast")
            return user_ids
        except Exception as e:
            logger.error(f"Failed to get user IDs: {e}")
            return []

    def set_preferred_language(self, user_id: int, language: str):
        """تعيين اللغة المفضلة للمستخدم"""
        if not self.use_database or not self.conn:
            if user_id in in_memory_users:
                in_memory_users[user_id]['preferred_language'] = language
            return
        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE users SET preferred_language = ? WHERE user_id = ?', (language, user_id))
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")

    def get_preferred_language(self, user_id: int) -> str:
        """الحصول على اللغة المفضلة للمستخدم"""
        if not self.use_database or not self.conn:
            return in_memory_users.get(user_id, {}).get('preferred_language', 'ar')
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT preferred_language FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result[0] if result and result[0] else 'ar'
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")
            return 'ar'

    def is_banned(self, user_id: int) -> bool:
        if not self.use_database or not self.conn:
            return False
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result and result[0] == 1
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")
            return False

    def is_muted(self, user_id: int) -> bool:
        if not self.use_database or not self.conn:
            return False
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT is_muted FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result and result[0] == 1
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")
            return False

    def ban_user(self, user_id: int):
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")

    def unban_user(self, user_id: int):
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")

    def mute_user(self, user_id: int):
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE users SET is_muted = 1 WHERE user_id = ?', (user_id,))
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")

    def unmute_user(self, user_id: int):
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE users SET is_muted = 0 WHERE user_id = ?', (user_id,))
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")

    def get_stats(self) -> Dict[str, Any]:
        if not self.use_database or not self.conn:
            return {
                'total_users': 0,
                'banned_users': 0,
                'muted_users': 0,
                'total_messages': 0
            }
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
            banned_users = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) FROM users WHERE is_muted = 1')
            muted_users = cursor.fetchone()[0]

            cursor.execute('SELECT SUM(message_count) FROM users')
            total_messages = cursor.fetchone()[0] or 0

            return {
                'total_users': total_users,
                'banned_users': banned_users,
                'muted_users': muted_users,
                'total_messages': total_messages
            }
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")
            return {
                'total_users': 0,
                'banned_users': 0,
                'muted_users': 0,
                'total_messages': 0
            }
    
    def add_group(self, group_id: int, group_name: str):
        """إضافة مجموعة جديدة"""
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT OR REPLACE INTO group_settings 
                (group_id, group_name, added_at, last_updated)
                VALUES (?, ?, ?, ?)
            ''', (group_id, group_name, now, now))
            self.conn.commit()
            logger.info(f"✅ تم إضافة المجموعة: {group_name} ({group_id})")
        except Exception as e:
            logger.error(f"خطأ في إضافة المجموعة: {e}")
    
    def get_group_settings(self, group_id: int) -> Dict[str, Any]:
        """الحصول على إعدادات المجموعة"""
        if not self.use_database or not self.conn:
            return {
                'auto_moderation': 1,
                'delete_profanity': 1,
                'warn_on_profanity': 1,
                'max_warnings': 3
            }
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT auto_moderation, delete_profanity, warn_on_profanity, max_warnings
                FROM group_settings WHERE group_id = ?
            ''', (group_id,))
            result = cursor.fetchone()
            if result:
                return {
                    'auto_moderation': result[0],
                    'delete_profanity': result[1],
                    'warn_on_profanity': result[2],
                    'max_warnings': result[3]
                }
            return {
                'auto_moderation': 1,
                'delete_profanity': 1,
                'warn_on_profanity': 1,
                'max_warnings': 3
            }
        except Exception as e:
            logger.error(f"خطأ في الحصول على إعدادات المجموعة: {e}")
            return {
                'auto_moderation': 1,
                'delete_profanity': 1,
                'warn_on_profanity': 1,
                'max_warnings': 3
            }
    
    def update_group_settings(self, group_id: int, **kwargs):
        """تحديث إعدادات المجموعة"""
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            now = datetime.now().isoformat()
            updates = []
            values = []
            for key, value in kwargs.items():
                if key in ['auto_moderation', 'delete_profanity', 'warn_on_profanity', 'max_warnings']:
                    updates.append(f"{key} = ?")
                    values.append(value)
            
            if updates:
                updates.append("last_updated = ?")
                values.append(now)
                values.append(group_id)
                
                query = f"UPDATE group_settings SET {', '.join(updates)} WHERE group_id = ?"
                cursor.execute(query, values)
                self.conn.commit()
                logger.info(f"✅ تم تحديث إعدادات المجموعة {group_id}")
        except Exception as e:
            logger.error(f"خطأ في تحديث إعدادات المجموعة: {e}")
    
    def add_warning(self, user_id: int, group_id: int, reason: str, warned_by: int):
        """إضافة تحذير للمستخدم"""
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO user_warnings (user_id, group_id, reason, warned_at, warned_by)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, group_id, reason, now, warned_by))
            self.conn.commit()
            logger.info(f"✅ تم إضافة تحذير للمستخدم {user_id} في المجموعة {group_id}")
        except Exception as e:
            logger.error(f"خطأ في إضافة تحذير: {e}")
    
    def get_user_warnings(self, user_id: int, group_id: int) -> int:
        """الحصول على عدد تحذيرات المستخدم في المجموعة"""
        if not self.use_database or not self.conn:
            return 0
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM user_warnings 
                WHERE user_id = ? AND group_id = ?
            ''', (user_id, group_id))
            return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"خطأ في الحصول على التحذيرات: {e}")
            return 0
    
    def clear_warnings(self, user_id: int, group_id: int):
        """مسح تحذيرات المستخدم"""
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                DELETE FROM user_warnings WHERE user_id = ? AND group_id = ?
            ''', (user_id, group_id))
            self.conn.commit()
            logger.info(f"✅ تم مسح تحذيرات المستخدم {user_id}")
        except Exception as e:
            logger.error(f"خطأ في مسح التحذيرات: {e}")
    
    def log_profanity_detection(self, user_id: int, group_id: int, message_text: str, 
                                detected_words: str, action_taken: str):
        """تسجيل كشف الكلام البذيء"""
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO profanity_detections 
                (user_id, group_id, message_text, detected_words, action_taken, detected_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, group_id, message_text, detected_words, action_taken, now))
            self.conn.commit()
        except Exception as e:
            logger.error(f"خطأ في تسجيل كشف الكلام البذيء: {e}")
    
    def is_group_admin(self, user_id: int, group_id: int) -> bool:
        """التحقق من كون المستخدم أدمن في المجموعة"""
        if user_id in ALL_ADMINS:
            return True
        if not self.use_database or not self.conn:
            return False
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM group_admins 
                WHERE group_id = ? AND user_id = ?
            ''', (group_id, user_id))
            return cursor.fetchone()[0] > 0
        except Exception as e:
            logger.error(f"خطأ في التحقق من الأدمن: {e}")
            return False
    
    def add_group_admin(self, group_id: int, user_id: int, added_by: int, permissions: str = 'moderate'):
        """إضافة أدمن للمجموعة"""
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT OR REPLACE INTO group_admins 
                (group_id, user_id, added_at, added_by, permissions)
                VALUES (?, ?, ?, ?, ?)
            ''', (group_id, user_id, now, added_by, permissions))
            self.conn.commit()
            logger.info(f"✅ تم إضافة أدمن {user_id} للمجموعة {group_id}")
        except Exception as e:
            logger.error(f"خطأ في إضافة أدمن: {e}")
    
    def remove_group_admin(self, group_id: int, user_id: int):
        """إزالة أدمن من المجموعة"""
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                DELETE FROM group_admins WHERE group_id = ? AND user_id = ?
            ''', (group_id, user_id))
            self.conn.commit()
            logger.info(f"✅ تم إزالة أدمن {user_id} من المجموعة {group_id}")
        except Exception as e:
            logger.error(f"خطأ في إزالة أدمن: {e}")

db = Database(use_database=True)

def check_rate_limit(user_id: int) -> Tuple[bool, float]:
    """فحص حد المعدل للمستخدم لمنع الإرسال المتكرر - thread-safe"""
    with memory_lock:
        current_time = time.time()
        if user_id in user_rate_limit:
            last_time, count = user_rate_limit[user_id]
            if current_time - last_time < 2:
                if count >= 3:
                    wait_time = 2 - (current_time - last_time)
                    return False, wait_time
                user_rate_limit[user_id] = (last_time, count + 1)
            else:
                user_rate_limit[user_id] = (current_time, 1)
        else:
            user_rate_limit[user_id] = (current_time, 1)
        return True, 0

def get_context_key(user_id: int, chat_id: int) -> str:
    """الحصول على مفتاح السياق لفصل البيانات بين المحادثات الخاصة والمجموعات"""
    return f"{user_id}_{chat_id}"

async def check_channel_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE, chat_id: int = None) -> bool:
    """التحقق من اشتراك المستخدم في القناة - مع دعم المجموعات"""
    if chat_id and chat_id < 0:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except TelegramError as e:
        logger.error(f"Error checking membership: {e}")
        return False

async def send_subscription_required_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال رسالة طلب الاشتراك"""
    keyboard = [
        [InlineKeyboardButton("📢 اشترك في القناة", url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}")],
        [InlineKeyboardButton("✅ تحققت من الاشتراك", callback_data="check_subscription")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = """
⚠️ **للاستخدام البوت يجب الاشتراك في القناة أولاً!**

📢 القناة: {}

بعد الاشتراك، اضغط على "تحققت من الاشتراك" للمتابعة
    """.format(REQUIRED_CHANNEL)

    if update.callback_query:
        await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)

class FileProcessor:
    """معالجة الملفات المختلفة"""

    @staticmethod
    async def extract_text_from_pdf(file_content: bytes) -> str:
        """استخراج النص من ملف PDF"""
        try:
            pdf_file = io.BytesIO(file_content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)

            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"

            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            return ""

    @staticmethod
    async def extract_text_from_docx(file_content: bytes) -> str:
        """استخراج النص من ملف DOCX"""
        try:
            docx_file = io.BytesIO(file_content)
            doc = docx.Document(docx_file)

            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"

            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting text from DOCX: {e}")
            return ""

    @staticmethod
    async def extract_text_from_txt(file_content: bytes) -> str:
        """استخراج النص من ملف TXT"""
        try:
            # محاولة فك التشفير بعدة صيغ
            encodings = ['utf-8', 'utf-16', 'windows-1256', 'iso-8859-1']

            for encoding in encodings:
                try:
                    text = file_content.decode(encoding)
                    return text.strip()
                except UnicodeDecodeError:
                    continue

            # إذا فشلت جميع المحاولات
            return file_content.decode('utf-8', errors='ignore').strip()
        except Exception as e:
            logger.error(f"Error extracting text from TXT: {e}")
            return ""

class MathSolver:
    """حل المسائل الرياضية باستخدام SymPy و SciPy"""

    @staticmethod
    def solve_equation(equation_text: str) -> str:
        """حل المعادلات الرياضية"""
        try:
            # استخراج المتغيرات
            x = sp.Symbol('x')
            y = sp.Symbol('y')
            z = sp.Symbol('z')

            # محاولة حل المعادلة
            equation = sp.sympify(equation_text)
            solution = sp.solve(equation, x)

            result = f"✅ **الحل:**\n\n"
            result += f"المعادلة: {equation}\n"
            result += f"الحل: {solution}\n"

            # إضافة خطوات الحل
            result += f"\n📝 **الشرح:**\n"
            result += sp.pretty(equation) + "\n"

            return result
        except Exception as e:
            return f"❌ خطأ في حل المعادلة: {str(e)}\n\nتأكد من كتابة المعادلة بشكل صحيح"

    @staticmethod
    def calculate_integral(function_text: str) -> str:
        """حساب التكامل"""
        try:
            x = sp.Symbol('x')
            function = sp.sympify(function_text)
            integral = sp.integrate(function, x)

            result = f"✅ **التكامل:**\n\n"
            result += f"الدالة: {function}\n"
            result += f"التكامل: {integral}\n"

            return result
        except Exception as e:
            return f"❌ خطأ في حساب التكامل: {str(e)}"

    @staticmethod
    def calculate_derivative(function_text: str) -> str:
        """حساب التفاضل"""
        try:
            x = sp.Symbol('x')
            function = sp.sympify(function_text)
            derivative = sp.diff(function, x)

            result = f"✅ **التفاضل:**\n\n"
            result += f"الدالة: {function}\n"
            result += f"المشتقة: {derivative}\n"

            return result
        except Exception as e:
            return f"❌ خطأ في حساب التفاضل: {str(e)}"

class BookSearch:
    """البحث في الكتب عبر APIs مجانية"""

    @staticmethod
    def search_google_books(query: str) -> str:
        """البحث في Google Books"""
        try:
            url = "https://www.googleapis.com/books/v1/volumes"
            params = {
                'q': query,
                'maxResults': 5,
                'langRestrict': 'ar,en'
            }

            response = requests.get(url, params=params, timeout=10)

            if response.ok:
                data = response.json()

                if 'items' not in data:
                    return "❌ لم يتم العثور على نتائج"

                result = "📚 **نتائج البحث في الكتب:**\n\n"

                for i, item in enumerate(data['items'][:5], 1):
                    info = item.get('volumeInfo', {})
                    title = info.get('title', 'بدون عنوان')
                    authors = ', '.join(info.get('authors', ['غير معروف']))
                    description = info.get('description', 'لا يوجد وصف')[:150]

                    result += f"**{i}. {title}**\n"
                    result += f"📝 المؤلف: {authors}\n"
                    result += f"📄 الوصف: {description}...\n\n"

                return result
            else:
                return "❌ خطأ في الاتصال بخدمة الكتب"

        except Exception as e:
            return f"❌ خطأ في البحث: {str(e)}"

    @staticmethod
    def search_open_library(query: str) -> str:
        """البحث في Open Library"""
        try:
            url = "https://openlibrary.org/search.json"
            params = {'q': query, 'limit': 5}

            response = requests.get(url, params=params, timeout=10)

            if response.ok:
                data = response.json()

                if 'docs' not in data or not data['docs']:
                    return "❌ لم يتم العثور على نتائج"

                result = "📖 **نتائج من المكتبة المفتوحة:**\n\n"

                for i, doc in enumerate(data['docs'][:5], 1):
                    title = doc.get('title', 'بدون عنوان')
                    authors = ', '.join(doc.get('author_name', ['غير معروف']))
                    year = doc.get('first_publish_year', 'غير معروف')

                    result += f"**{i}. {title}**\n"
                    result += f"👤 المؤلف: {authors}\n"
                    result += f"📅 سنة النشر: {year}\n\n"

                return result
            else:
                return "❌ خطأ في الاتصال بالمكتبة المفتوحة"

        except Exception as e:
            return f"❌ خطأ في البحث: {str(e)}"

class MathExerciseSolver:
    """حل التمارين الرياضية من الصور باستخدام OCR + AI (مجاني 100%)"""

    @staticmethod
    async def extract_text_from_image(image_path: str) -> str:
        """استخراج النص من الصورة باستخدام Tesseract OCR"""
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)

            text_ar = pytesseract.image_to_string(img, lang='ara')
            text_en = pytesseract.image_to_string(img, lang='eng')

            text = text_ar if len(text_ar) > len(text_en) else text_en

            if text_ar and text_en:
                text = text_ar + "\n" + text_en

            logger.info(f"OCR extracted {len(text)} characters")
            return text.strip()
        except Exception as e:
            logger.error(f"OCR error: {e}")
            return ""

    @staticmethod
    def solve_with_ai(problem_text: str) -> str:
        """حل التمرين باستخدام AI مجاني"""
        try:
            prompt = f"""أنت معلم رياضيات محترف. حل هذا التمرين خطوة بخطوة:

{problem_text}

**قواعد التنسيق والإخراج الإلزامية:**
✓ وضوح التنسيق الرياضي: اكتب جميع المعادلات والنتائج الرياضية بتنسيق واضح ومرئي ومفهوم
✓ تجنب الأوامر الخام: لا تستخدم أوامر LaTeX الخام مثل \\frac أو \\sqrt أو \\cdot في الإخراج
✓ استخدم الرموز البديلة: بدلاً من \\frac{{a}}{{b}} اكتب (a/b) أو a÷b، وبدلاً من \\sqrt{{x}} اكتب √x أو الجذر التربيعي لـ x
✓ الترقيم والتنظيم: رتب الحل خطوة بخطوة بترقيم واضح (1. 2. 3.) لتسهيل المتابعة
✓ النتيجة النهائية: اعرض النتيجة النهائية بوضوح تام في نهاية الحل

قدم الحل بشكل واضح ومنظم مع شرح كل خطوة."""

            solution = AIModels.grok4(prompt)
            return solution
        except Exception as e:
            logger.error(f"AI solve error: {e}")
            return f"❌ خطأ في الحل: {str(e)}"

    @staticmethod
    def create_solution_image(solution_text: str, title: str = "✅ الحل الكامل") -> str:
        """تحويل النص إلى صورة جميلة باستخدام Pillow مع دعم العربية والإنجليزية"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import textwrap
            from arabic_reshaper import reshape
            from bidi.algorithm import get_display

            width = 1200
            padding = 60
            line_height = 45
            title_height = 100

            solution_text_clean = solution_text[:3000] if len(solution_text) > 3000 else solution_text

            lines = []
            for paragraph in solution_text_clean.split('\n'):
                if paragraph.strip():
                    if any(ord(c) > 127 for c in paragraph):
                        reshaped = reshape(paragraph)
                        bidi_text = get_display(reshaped)
                        wrapped = textwrap.fill(bidi_text, width=70)
                    else:
                        wrapped = textwrap.fill(paragraph, width=90)
                    lines.extend(wrapped.split('\n'))
                else:
                    lines.append('')

            height = max(800, len(lines) * line_height + padding * 2 + title_height)

            gradient_start = (240, 248, 255)
            gradient_end = (230, 240, 250)
            img = Image.new('RGB', (width, height), color=gradient_start)
            draw = ImageDraw.Draw(img)

            for y in range(height):
                r = int(gradient_start[0] + (gradient_end[0] - gradient_start[0]) * y / height)
                g = int(gradient_start[1] + (gradient_end[1] - gradient_start[1]) * y / height)
                b = int(gradient_start[2] + (gradient_end[2] - gradient_start[2]) * y / height)
                draw.line([(0, y), (width, y)], fill=(r, g, b))

            try:
                font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
                font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
            except:
                try:
                    font_title = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 32)
                    font_body = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 22)
                except:
                    font_title = ImageFont.load_default()
                    font_body = ImageFont.load_default()

            if any(ord(c) > 127 for c in title):
                reshaped_title = reshape(title)
                bidi_title = get_display(reshaped_title)
            else:
                bidi_title = title

            title_bbox = draw.textbbox((0, 0), bidi_title, font=font_title)
            title_width = title_bbox[2] - title_bbox[0]
            title_x = (width - title_width) // 2

            draw.rectangle([(0, 0), (width, title_height)], fill=(70, 130, 180))
            draw.text((title_x, 30), bidi_title, fill=(255, 255, 255), font=font_title)

            y_position = title_height + padding
            for line in lines:
                if line.strip():
                    draw.text((padding, y_position), line, fill=(30, 30, 30), font=font_body)
                y_position += line_height

            draw.rectangle([(0, height-3), (width, height)], fill=(70, 130, 180))

            output_path = f"/tmp/solution_{int(time.time())}.png"
            img.save(output_path, quality=95)

            logger.info(f"✅ Solution image created: {output_path} ({len(lines)} lines)")
            return output_path
        except ImportError as ie:
            logger.warning(f"Arabic support libraries not available: {ie}")
            try:
                from PIL import Image, ImageDraw, ImageFont
                import textwrap

                width = 1200
                padding = 60
                line_height = 40

                lines = []
                solution_text_clean = solution_text[:3000] if len(solution_text) > 3000 else solution_text
                for paragraph in solution_text_clean.split('\n'):
                    if paragraph.strip():
                        wrapped = textwrap.fill(paragraph, width=80)
                        lines.extend(wrapped.split('\n'))
                    else:
                        lines.append('')

                height = max(800, len(lines) * line_height + padding * 2 + 100)

                img = Image.new('RGB', (width, height), color=(240, 248, 255))
                draw = ImageDraw.Draw(img)

                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
                except:
                    font = ImageFont.load_default()

                draw.rectangle([(0, 0), (width, 80)], fill=(70, 130, 180))
                draw.text((padding, 25), title, fill=(255, 255, 255), font=font)

                y_position = 100 + padding
                for line in lines:
                    draw.text((padding, y_position), line, fill=(0, 0, 0), font=font)
                    y_position += line_height

                output_path = f"/tmp/solution_{int(time.time())}.png"
                img.save(output_path)

                logger.info(f"Solution image created (basic): {output_path}")
                return output_path
            except Exception as e:
                logger.error(f"Image creation error (fallback): {e}")
                return ""
        except Exception as e:
            logger.error(f"Image creation error: {e}")
            return ""

class AIModels:
    """جميع نماذج الذكاء الاصطناعي"""

    @staticmethod
    def translate_to_english(text: str) -> str:
        """ترجمة النص إلى الإنجليزية لتحسين دقة إنشاء الصور"""
        try:
            # محاولة الترجمة باستخدام MyMemory API (أكثر دقة)
            response = requests.get(
                'https://api.mymemory.translated.net/get',
                params={
                    'q': text,
                    'langpair': 'ar|en'
                },
                timeout=5
            )
            if response.ok:
                result = response.json()
                if result.get('responseStatus') == 200:
                    translated = result.get('responseData', {}).get('translatedText', text)
                    logger.info(f"Translated: '{text[:50]}...' -> '{translated[:50]}...'")
                    return translated
        except Exception as e:
            logger.warning(f"Translation with MyMemory failed, trying Google: {e}")

        # محاولة بديلة مع Google Translate
        try:
            response = requests.get(
                'https://translate.googleapis.com/translate_a/single',
                params={
                    'client': 'gtx',
                    'sl': 'auto',
                    'tl': 'en',
                    'dt': 't',
                    'q': text
                },
                timeout=5
            )
            if response.ok:
                result = response.json()
                if result and len(result) > 0 and len(result[0]) > 0:
                    translated = ''.join([item[0] for item in result[0] if item[0]])
                    logger.info(f"Translated (Google): '{text[:50]}...' -> '{translated[:50]}...'")
                    return translated
        except Exception as e:
            logger.warning(f"All translation failed, using original text: {e}")

        return text

    @staticmethod
    def is_valid_image_url(url: str) -> bool:
        """التحقق من صحة رابط الصورة - يدعم http و https وروابط Telegram"""
        if not url or not isinstance(url, str):
            return False
        url = url.strip()

        if not (url.startswith('http://') or url.startswith('https://')):
            return False

        if 'api.telegram.org/file/bot' in url.lower():
            return True

        return any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif'])

    @staticmethod
    def grok4(text: str, conversation_history: list = None, max_retries: int = 3) -> str:
        """نموذج Grok-4 للمحادثة العامة مع سياق محسّن (5 رسائل) و retry logic"""
        logger.info("📡 استدعاء Grok-4 API")

        for attempt in range(max_retries):
            try:
                prompt = text
                if conversation_history:
                    context = "\n".join([f"المستخدم: {msg}\nالمساعد: {resp}" for msg, resp in conversation_history[-5:]])
                    prompt = f"سياق المحادثة السابقة:\n{context}\n\nالسؤال الحالي: {text}"

                logger.info(f"🔄 محاولة {attempt + 1}/{max_retries}")
                response = requests.post(
                    'https://sii3.top/api/grok4.php',
                    data={'text': prompt},
                    timeout=60
                )

                if response.ok:
                    result = response.text
                    cleaned = AIModels._clean_response(result)

                    # التحقق من أن الرد صالح وليس خطأ
                    if cleaned and len(cleaned.strip()) > 10 and "error" not in cleaned.lower()[:50]:
                        logger.info(f"✅ Grok-4 API نجح في المحاولة {attempt + 1}")
                        return cleaned
                    else:
                        logger.warning(f"⚠️ رد غير صالح في المحاولة {attempt + 1}: {cleaned[:100]}")
                        if attempt < max_retries - 1:
                            import time
                            time.sleep(2)
                            continue
                else:
                    logger.error(f"❌ Grok-4 HTTP خطأ {response.status_code} في المحاولة {attempt + 1}")
                    logger.error(f"الرد: {response.text[:200]}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(2)
                        continue

            except requests.exceptions.Timeout:
                logger.error(f"⏱️ Grok-4 timeout في المحاولة {attempt + 1}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2)
                    continue
            except Exception as e:
                logger.error(f"💥 Grok-4 خطأ في المحاولة {attempt + 1}: {type(e).__name__} - {str(e)}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2)
                    continue

        # إذا فشلت جميع المحاولات
        logger.error("❌ Grok-4 فشل في جميع المحاولات")
        return "⚠️ عذراً، الخدمة غير متاحة حالياً. يرجى المحاولة لاحقاً أو إعادة صياغة السؤال."

    @staticmethod
    def search(query: str) -> str:
        """البحث الشامل عبر 40 متصفح"""
        try:
            response = requests.post(
                'https://sii3.top/api/s.php',
                data={'q': query},
                timeout=45
            )
            if response.ok:
                result = response.text
                return AIModels._format_search_results(AIModels._clean_response(result))
            else:
                return f"خطأ: {response.status_code}"
        except Exception as e:
            return f"خطأ في البحث: {str(e)}"

    @staticmethod
    def darkcode(text: str) -> str:
        """مساعد البرمجة DarkCode"""
        try:
            response = requests.post(
                'https://sii3.top/api/DarkCode.php',
                json={'text': text},
                timeout=45
            )
            if response.ok:
                result = response.text
                return AIModels._clean_response(result)
            else:
                return f"خطأ: {response.status_code}"
        except Exception as e:
            return f"خطأ في مساعد البرمجة: {str(e)}"

    @staticmethod
    def ocr(text: str, image_urls: list, language: str = "ar") -> str:
        """استخراج النص من الصور مع دعم اللغات المختلفة"""
        try:
            if not image_urls:
                return ""

            links = ", ".join(image_urls[:10])
            logger.info(f"OCR request - text: {text[:50] if text else 'empty'}, images: {len(image_urls)}, language: {language}")
            logger.info(f"OCR links: {links[:200]}")

            instruction_text = text if text else ""
            if not instruction_text or len(instruction_text.strip()) < 5:
                if language == "ar":
                    instruction_text = "استخرج جميع النصوص والمعادلات والأرقام الموجودة في الصورة بالعربية. احتفظ بالتنسيق والترتيب الأصلي."
                else:
                    instruction_text = "Extract all text, equations, and numbers from the image in Arabic and English. Preserve the original formatting and order."

            payload = {"text": instruction_text}
            if links:
                payload["link"] = links

            response = requests.post(
                'https://sii3.top/api/OCR.php',
                data=payload,
                timeout=60
            )

            logger.info(f"OCR response status: {response.status_code}")

            if response.ok:
                try:
                    result_json = response.json()
                    logger.info(f"OCR JSON response keys: {result_json.keys() if isinstance(result_json, dict) else 'not dict'}")

                    extracted_text = result_json.get('response', '')

                    if not extracted_text:
                        logger.warning("OCR returned empty response")
                        return ""
                    
                    if "something went wrong" in extracted_text.lower() or "please try again" in extracted_text.lower():
                        logger.error(f"OCR API error: {extracted_text}")
                        return ""
                    
                    if "sure! please specify" in extracted_text.lower():
                        logger.warning("OCR API asking for language specification - retrying with explicit instruction")
                        return ""

                    final_text = extracted_text.replace('\\n', '\n')
                    logger.info(f"OCR success - extracted {len(final_text)} chars")
                    return final_text
                except Exception as e:
                    logger.error(f"OCR JSON parsing error: {e}")
                    return ""
            else:
                logger.error(f"OCR HTTP error: {response.status_code}")
                return ""
        except Exception as e:
            logger.error(f"OCR error: {e}")
            return ""

    @staticmethod
    def prompt_img(text: str) -> str:
        """توسيع المطالبات للصور"""
        try:
            response = requests.post(
                'https://sii3.top/api/prompt-img.php',
                data={'text': text},
                timeout=30
            )
            return response.text if response.ok else text
        except Exception as e:
            return text

    @staticmethod
    def flux_pro(text: str, max_retries: int = 2) -> str:
        """توليد صور واقعية عالية الجودة"""
        # ترجمة النص للإنجليزية لتحسين الدقة
        english_text = AIModels.translate_to_english(text)

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    'https://sii3.top/api/flux-pro.php',
                    data={'text': english_text},
                    timeout=150
                )
                if response.ok:
                    result = response.text.strip()
                    if (result.startswith('http://') or result.startswith('https://')) and any(ext in result.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
                        return result
                    logger.warning(f"flux_pro invalid response on attempt {attempt + 1}")
                else:
                    logger.warning(f"flux_pro HTTP error {response.status_code} on attempt {attempt + 1}")
            except requests.exceptions.Timeout:
                logger.warning(f"flux_pro timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"flux_pro error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue

        return ""

    @staticmethod
    def seedream_4(text: str, image_urls: list = None, max_retries: int = 2) -> str:
        """نموذج SeedReam-4 الجديد - توليد وتحرير الصور (يدعم حتى 4 صور)"""
        english_text = AIModels.translate_to_english(text)

        data = {'text': english_text}
        if image_urls:
            data['links'] = ','.join(image_urls[:4])

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    'https://sii3.top/api/SeedReam-4.php',
                    data=data,
                    timeout=150
                )
                if response.ok:
                    result = response.text.strip()
                    if AIModels.is_valid_image_url(result):
                        logger.info(f"SeedReam-4 success: {result[:100]}")
                        return result
                    logger.warning(f"SeedReam-4 invalid response on attempt {attempt + 1}: {result[:100]}")
                else:
                    logger.warning(f"SeedReam-4 HTTP error {response.status_code} on attempt {attempt + 1}, response: {response.text[:200]}")
            except requests.exceptions.Timeout:
                logger.warning(f"SeedReam-4 timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"SeedReam-4 error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue

        return ""

    @staticmethod
    def veo3_text_to_video(text: str, max_retries: int = 2) -> str:
        """Veo3: تحويل النص إلى فيديو مع دعم صوتي مجاني"""
        english_text = AIModels.translate_to_english(text)

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    'https://sii3.top/api/veo3.php',
                    data={'text': english_text},
                    timeout=180
                )
                if response.ok:
                    result = response.text.strip()
                    if result.startswith('http') and any(ext in result.lower() for ext in ['.mp4', '.avi', '.mov', '.webm']):
                        logger.info(f"Veo3 text-to-video success: {result[:100]}")
                        return result
                    logger.warning(f"Veo3 invalid video response on attempt {attempt + 1}: {result[:100]}")
                else:
                    logger.warning(f"Veo3 HTTP error {response.status_code} on attempt {attempt + 1}, response: {response.text[:200]}")
            except requests.exceptions.Timeout:
                logger.warning(f"Veo3 timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"Veo3 error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue

        return ""

    @staticmethod
    def veo3_image_to_video(text: str, image_url: str, max_retries: int = 2) -> str:
        """Veo3: تحويل الصورة إلى فيديو مع دعم صوتي مجاني"""
        english_text = AIModels.translate_to_english(text)

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    'https://sii3.top/api/veo3.php',
                    data={'text': english_text, 'link': image_url},
                    timeout=180
                )
                if response.ok:
                    result = response.text.strip()
                    if result.startswith('http') and any(ext in result.lower() for ext in ['.mp4', '.avi', '.mov', '.webm']):
                        logger.info(f"Veo3 image-to-video success: {result[:100]}")
                        return result
                    logger.warning(f"Veo3 invalid video response on attempt {attempt + 1}: {result[:100]}")
                else:
                    logger.warning(f"Veo3 HTTP error {response.status_code} on attempt {attempt + 1}, response: {response.text[:200]}")
            except requests.exceptions.Timeout:
                logger.warning(f"Veo3 timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"Veo3 error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue

        return ""

    @staticmethod
    def gpt_imager(text: str, image_url: str = None, max_retries: int = 2) -> str:
        """إنشاء وتعديل الصور - النموذج الجديد المحسّن"""
        logger.info("🎨 استدعاء GPT-Imager API")

        # ترجمة النص للإنجليزية لتحسين الدقة
        english_text = AIModels.translate_to_english(text)

        data = {'text': english_text}
        if image_url:
            data['link'] = image_url
            logger.info(f"📸 تحرير الصورة: {image_url[:100]}")

        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 GPT-Imager محاولة {attempt + 1}/{max_retries}")
                response = requests.post(
                    'https://sii3.top/api/gpt-img.php',
                    data=data,
                    timeout=150
                )

                logger.info(f"📡 GPT-Imager response status: {response.status_code}")

                if response.ok:
                    result = response.text.strip()
                    logger.info(f"📥 GPT-Imager response: {result[:200]}")

                    # Try parsing as JSON first
                    try:
                        json_data = response.json()
                        logger.info(f"GPT-Imager JSON keys: {json_data.keys() if isinstance(json_data, dict) else 'not dict'}")

                        # Check for error
                        if 'error' in json_data:
                            error_msg = json_data['error']
                            logger.error(f"❌ GPT-Imager API error on attempt {attempt + 1}: {error_msg}")
                            if attempt < max_retries - 1:
                                import time
                                time.sleep(2)
                                continue
                        else:
                            # Look for image URL
                            image_result = json_data.get('image', json_data.get('url', json_data.get('result', '')))
                            if AIModels.is_valid_image_url(image_result):
                                logger.info(f"✅ GPT-Imager success: {image_result[:100]}")
                                return image_result
                            logger.warning(f"⚠️ GPT-Imager JSON parsed but no valid URL: {json_data}")
                    except json.JSONDecodeError:
                        # If not JSON, treat as direct URL
                        if AIModels.is_valid_image_url(result):
                            logger.info(f"✅ GPT-Imager success (direct URL): {result[:100]}")
                            return result
                        logger.warning(f"⚠️ GPT-Imager not JSON and not valid URL: {result[:200]}")
                else:
                    logger.error(f"❌ GPT-Imager HTTP error {response.status_code} on attempt {attempt + 1}: {response.text[:200]}")
                    # خطأ 500 يعني السيرفر معطل، لا داعي للمحاولة مجدداً
                    if response.status_code == 500:
                        logger.warning("⚠️ Server error 500, skipping retries")
                        break
            except requests.exceptions.Timeout:
                logger.error(f"⏱️ GPT-Imager timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"💥 GPT-Imager error on attempt {attempt + 1}: {type(e).__name__} - {str(e)}")
                if attempt < max_retries - 1:
                    continue

        logger.error("❌ GPT-Imager فشل في جميع المحاولات")
        return ""

    @staticmethod
    def img_bo(text: str, size: str = "1024x1024", max_retries: int = 2) -> str:
        """توليد صور عالية الجودة وواقعية مع أحجام مخصصة"""
        valid_sizes = ["1024x1024", "1792x1024", "1024x1792"]
        if size not in valid_sizes:
            size = "1024x1024"

        # ترجمة النص للإنجليزية لتحسين الدقة
        english_text = AIModels.translate_to_english(text)

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    'https://sii3.top/api/img-bo.php',
                    data={'text': english_text, 'size': size},
                    timeout=150
                )
                if response.ok:
                    result = response.text.strip()
                    if AIModels.is_valid_image_url(result):
                        return result
                    logger.warning(f"img-bo invalid response format on attempt {attempt + 1}")
                else:
                    logger.warning(f"img-bo HTTP error {response.status_code} on attempt {attempt + 1}")
            except requests.exceptions.Timeout:
                logger.warning(f"img-bo timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"img-bo error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue

        return ""

    @staticmethod
    def img_cv(text: str, max_retries: int = 2) -> str:
        """توليد صور بجودة عالية وسرعة فائقة خلال ثوانٍ"""
        # ترجمة النص للإنجليزية لتحسين الدقة
        english_text = AIModels.translate_to_english(text)

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    'https://sii3.top/api/img-cv.php',
                    data={'text': english_text},
                    timeout=30
                )
                if response.ok:
                    response_text = response.text.strip()
                    logger.info(f"img_cv response on attempt {attempt + 1}: {response_text[:200]}")

                    # Try parsing as JSON first
                    try:
                        json_data = response.json()
                        result = json_data.get('image', json_data.get('url', json_data.get('result', '')))
                        if AIModels.is_valid_image_url(result):
                            return result
                        logger.warning(f"img_cv JSON parsed but no valid URL found: {json_data}")
                    except:
                        # If not JSON, treat as direct URL
                        if AIModels.is_valid_image_url(response_text):
                            return response_text
                        logger.warning(f"img_cv not JSON and not valid URL: {response_text[:200]}")
                else:
                    logger.warning(f"img_cv HTTP error {response.status_code} on attempt {attempt + 1}: {response.text[:200]}")
            except requests.exceptions.Timeout:
                logger.warning(f"img_cv timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"img_cv error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue

        return ""

    @staticmethod
    def nano_banana(text: str, image_urls: list = None, max_retries: int = 2) -> str:
        """توليد وتحرير صور بنموذج gemini-2.5-flash-nano-banan - سريع جداً ويدعم 1-10 صور"""
        logger.info("🍌 استدعاء Nano Banana API")

        # ترجمة النص للإنجليزية لتحسين الدقة
        english_text = AIModels.translate_to_english(text)

        data = {'text': english_text}
        if image_urls:
            data['links'] = ','.join(image_urls[:10])
            logger.info(f"📸 عدد الصور المرسلة: {len(image_urls[:10])}")

        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 محاولة {attempt + 1}/{max_retries}")
                response = requests.post(
                    'https://sii3.top/api/nano-banana.php',
                    data=data,
                    timeout=60
                )
                if response.ok:
                    response_text = response.text.strip()
                    logger.info(f"📥 استجابة: {response_text[:200]}")

                    # Try parsing as JSON first
                    try:
                        json_data = response.json()
                        result = json_data.get('image', json_data.get('url', json_data.get('result', '')))
                        if AIModels.is_valid_image_url(result):
                            logger.info("✅ Nano Banana نجح")
                            return result
                        logger.warning(f"⚠️ JSON بدون URL صالح: {json_data}")
                    except:
                        # If not JSON, treat as direct URL
                        if AIModels.is_valid_image_url(response_text):
                            logger.info("✅ Nano Banana نجح (URL مباشر)")
                            return response_text
                        logger.warning(f"⚠️ ليس JSON ولا URL صالح: {response_text[:200]}")
                else:
                    logger.error(f"❌ خطأ HTTP {response.status_code}")
                    logger.error(f"الرد: {response.text[:200]}")
            except requests.exceptions.Timeout:
                logger.error(f"⏱️ انتهت المهلة في المحاولة {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"💥 خطأ في المحاولة {attempt + 1}: {type(e).__name__} - {str(e)}")
                if attempt < max_retries - 1:
                    continue

        logger.error("❌ Nano Banana فشل في جميع المحاولات")
        return ""

    @staticmethod
    def quality_enhancer(image_url: str, max_retries: int = 3) -> str:
        """تحسين جودة الصور حتى دقة 8K باستخدام GPT-5 - يدعم http و https وروابط Telegram"""
        import hashlib
        import urllib.parse

        logger.info("✨ بدء تحسين جودة الصورة...")
        # حساب hash للصورة الأصلية للمقارنة
        original_hash = hashlib.md5(image_url.encode()).hexdigest()[:8]
        logger.info(f"📸 Original image hash: {original_hash}, URL: {image_url[:100]}")

        for attempt in range(max_retries):
            try:
                # استخدام urlencode لضمان ترميز الرابط بشكل صحيح
                encoded_url = urllib.parse.quote(image_url, safe='')
                api_url = f'https://sii3.top/api/quality.php?link={encoded_url}'
                logger.info(f"🔄 quality_enhancer attempt {attempt + 1}/{max_retries}")

                response = requests.get(
                    api_url,
                    timeout=150
                )

                logger.info(f"📡 quality_enhancer response status: {response.status_code}")

                if response.ok:
                    response_text = response.text.strip()
                    logger.info(f"📥 quality_enhancer response on attempt {attempt + 1}: {response_text[:200]}")

                    # محاولة تحليل JSON أولاً
                    try:
                        json_data = response.json()

                        # التحقق من وجود خطأ في الاستجابة
                        if 'error' in json_data:
                            error_msg = json_data['error']
                            logger.error(f"❌ quality_enhancer API error on attempt {attempt + 1}: {error_msg}")

                            # إذا كان الخطأ "server is down"، انتقل مباشرة للنماذج البديلة
                            if "server is down" in error_msg.lower() or "down" in error_msg.lower():
                                logger.warning("⚠️ Server is down, skipping to fallback models")
                                break

                            if attempt < max_retries - 1:
                                import time
                                time.sleep(3)
                                continue
                        else:
                            # البحث عن رابط الصورة
                            result = json_data.get('image', json_data.get('url', json_data.get('result', json_data.get('enhanced_image', ''))))
                            if AIModels.is_valid_image_url(result):
                                # التحقق من أن الصورة المُرجعة مختلفة عن الأصلية
                                result_hash = hashlib.md5(result.encode()).hexdigest()[:8]
                                if result_hash != original_hash and image_url not in result:
                                    logger.info(f"✅ quality_enhancer success - new image hash: {result_hash}")
                                    return result
                                else:
                                    logger.warning(f"⚠️ Received same image or similar URL, retrying...")
                                    if attempt < max_retries - 1:
                                        import time
                                        time.sleep(2)
                                        continue
                            logger.warning(f"⚠️ quality_enhancer JSON parsed but no valid URL found: {json_data}")
                    except json.JSONDecodeError:
                        # إذا لم يكن JSON، التعامل كرابط مباشر
                        if AIModels.is_valid_image_url(response_text):
                            result_hash = hashlib.md5(response_text.encode()).hexdigest()[:8]
                            if result_hash != original_hash:
                                logger.info(f"✅ quality_enhancer success (direct URL) - hash: {result_hash}")
                                return response_text
                        logger.warning(f"⚠️ quality_enhancer not JSON and not valid URL: {response_text[:200]}")
                else:
                    logger.error(f"❌ quality_enhancer HTTP error {response.status_code} on attempt {attempt + 1}: {response.text[:200]}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(3)
            except requests.exceptions.Timeout:
                logger.error(f"⏱️ quality_enhancer timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"💥 quality_enhancer error on attempt {attempt + 1}: {type(e).__name__} - {str(e)}")
                if attempt < max_retries - 1:
                    continue

        # إذا فشلت جميع المحاولات، استخدم نماذج بديلة متعددة
        logger.info("🔄 All quality_enhancer attempts failed, trying multiple fallback models")

        # محاولة 1: nano_banana (الأسرع)
        logger.info("🍌 Trying nano_banana as fallback 1")
        fallback_url = AIModels.nano_banana("enhance image quality 8K, improve details, sharpen, increase resolution, upscale to ultra high resolution, professional quality enhancement", [image_url])
        if AIModels.is_valid_image_url(fallback_url):
            logger.info("✅ nano_banana fallback succeeded")
            return fallback_url

        # محاولة 2: gpt_imager
        logger.info("🎨 nano_banana failed, trying gpt_imager as fallback 2")
        fallback_url = AIModels.gpt_imager("enhance and upscale image quality to 8K resolution, improve details, colors and sharpness, professional quality enhancement", image_url)
        if AIModels.is_valid_image_url(fallback_url):
            logger.info("✅ gpt_imager fallback succeeded")
            return fallback_url

        # محاولة 3: seedream_4
        logger.info("🌱 gpt_imager failed, trying seedream_4 as fallback 3")
        fallback_url = AIModels.seedream_4("upscale to 8K ultra resolution, enhance quality, improve details and clarity, sharpen image", [image_url])
        if AIModels.is_valid_image_url(fallback_url):
            logger.info("✅ seedream_4 fallback succeeded")
            return fallback_url

        # إذا فشلت جميع النماذج
        logger.error("❌ All quality enhancement models failed")
        return ""
    
    @staticmethod
    def check_profanity(text: str) -> Dict[str, Any]:
        """كشف الكلام البذيء باستخدام الذكاء الاصطناعي"""
        try:
            prompt = f"""أنت نظام كشف الكلام البذيء والمسيء. 
حلل النص التالي وحدد ما إذا كان يحتوي على:
1. كلمات بذيئة أو شتائم
2. إهانات أو تحقير
3. تهديدات
4. محتوى جنسي غير لائق
5. كلام عنصري أو كراهية

النص: "{text}"

أجب فقط بـ JSON بهذا الشكل:
{{"is_profane": true/false, "category": "نوع المخالفة", "severity": "منخفض/متوسط/عالي", "detected_words": ["كلمة1", "كلمة2"]}}"""
            
            response = requests.post(
                'https://sii3.top/api/grok4.php',
                data={'text': prompt},
                timeout=10
            )
            
            if response.ok:
                result = response.text.strip()
                
                try:
                    # محاولة استخراج JSON من النص
                    import re
                    json_match = re.search(r'\{[^}]+\}', result)
                    if json_match:
                        json_data = json.loads(json_match.group())
                        return {
                            'is_profane': json_data.get('is_profane', False),
                            'category': json_data.get('category', 'غير محدد'),
                            'severity': json_data.get('severity', 'منخفض'),
                            'detected_words': json_data.get('detected_words', [])
                        }
                except:
                    pass
                
                # تحليل بسيط كاحتياطي
                lower_text = text.lower()
                profane_words = ['كلب', 'حمار', 'غبي', 'أحمق', 'خنزير', 'قذر']
                found_words = [word for word in profane_words if word in lower_text]
                
                if found_words or any(word in result.lower() for word in ['true', 'yes', 'نعم', 'بذيء']):
                    return {
                        'is_profane': True,
                        'category': 'شتائم',
                        'severity': 'متوسط',
                        'detected_words': found_words
                    }
            
            return {
                'is_profane': False,
                'category': '',
                'severity': '',
                'detected_words': []
            }
        except Exception as e:
            logger.error(f"خطأ في كشف الكلام البذيء: {e}")
            return {
                'is_profane': False,
                'category': '',
                'severity': '',
                'detected_words': []
            }

    @staticmethod
    def _clean_response(text: str) -> str:
        """تنظيف الردود من JSON والرموز غير المرغوب فيها"""
        try:
            import re

            # محاولة تحليل JSON أولاً
            try:
                json_data = json.loads(text)
                if isinstance(json_data, dict):
                    # إزالة معلومات التاريخ والمطور
                    if 'date' in json_data:
                        del json_data['date']
                    if 'dev' in json_data:
                        del json_data['dev']

                    # استخراج المحتوى الأساسي
                    if 'response' in json_data:
                        text = json_data['response']
                    elif 'results' in json_data:
                        return AIModels._format_search_results(json_data)
                    elif 'query' in json_data and 'results' in json_data:
                        return AIModels._format_search_results(json_data)
                    else:
                        for key, value in json_data.items():
                            if isinstance(value, str) and len(value.strip()) > 10:
                                text = value
                                break
                        else:
                            text = str(json_data)
            except json.JSONDecodeError:
                pass

            # تنظيف JSON المتبقي
            text = re.sub(r'\{\s*"date":\s*"[^"]*",?\s*', '', text)
            text = re.sub(r'\{\s*"response":\s*"([^"]*)",?\s*', r'\1', text)
            text = re.sub(r'"dev":\s*"[^"]*",?\s*', '', text)
            text = re.sub(r'"Don\'t forget to support[^"]*",?\s*', '', text)
            text = re.sub(r'^\{\s*', '', text)
            text = re.sub(r'\s*\}$', '', text)
            text = re.sub(r'^\[\s*', '', text)
            text = re.sub(r'\s*\]$', '', text)
            text = re.sub(r'^"', '', text)
            text = re.sub(r'"$', '', text)

            # تنظيف رموز الترميز
            text = re.sub(r'\\n', '\n', text)
            text = re.sub(r'\\t', '\t', text)
            text = re.sub(r'\\"', '"', text)

            return text.strip().strip(',').strip()

        except Exception as e:
            return text

    @staticmethod
    def _format_search_results(data) -> str:
        """تنسيق نتائج البحث بشكل منظم"""
        try:
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except:
                    return data

            if isinstance(data, dict) and 'results' in data:
                results_text = "🔍 **نتائج البحث:**\n\n"

                if 'google' in data['results'] and isinstance(data['results']['google'], list):
                    google_results = data['results']['google'][:5]

                    for i, result in enumerate(google_results, 1):
                        if isinstance(result, dict):
                            title = result.get('title', 'بدون عنوان')
                            url = result.get('url', '')
                            description = result.get('description', '').strip()

                            results_text += f"**{i}. {title}**\n"
                            if description and len(description) > 10:
                                import re
                                desc_clean = re.sub(r'[^\w\s\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF.,!?()-]', '', description)
                                desc_short = desc_clean[:120] + "..." if len(desc_clean) > 120 else desc_clean
                                results_text += f"📝 {desc_short}\n"
                            if url:
                                results_text += f"🔗 {url}\n\n"

                if 'wikipedia' in data['results'] and isinstance(data['results']['wikipedia'], list):
                    wiki_results = data['results']['wikipedia'][:2]

                    if wiki_results:
                        results_text += "📚 **من ويكيبيديا:**\n\n"
                        for i, result in enumerate(wiki_results, 1):
                            if isinstance(result, dict):
                                title = result.get('title', 'بدون عنوان')
                                url = result.get('url', '')
                                results_text += f"**{i}. {title}**\n"
                                if url:
                                    results_text += f"🔗 {url}\n\n"

                return results_text if len(results_text) > 30 else "لم يتم العثور على نتائج مناسبة"

            return str(data)

        except Exception as e:
            return f"خطأ في تنسيق النتائج: {str(e)}"

ai = AIModels()

class LoadingAnimation:
    """رسائل انتظار جميلة"""

    DOTS_PATTERNS = [
        "⏳ جاري المعالجة.",
        "⏳ جاري المعالجة..",
        "⏳ جاري المعالجة...",
        "⏳ جاري المعالجة....",
    ]

    PROGRESS_PATTERNS = [
        "▂",
        "▂▃",
        "▂▃▄",
        "▂▃▄▅",
        "▂▃▄",
        "▂▃",
        "▂",
    ]

    BOYKTA_PATTERNS = [
        "✨ B O Y K T A ✨",
        "⭐ B O Y K T A ⭐",
        "🌟 B O Y K T A 🌟",
        "💫 B O Y K T A 💫",
        "🌠 B O Y K T A 🌠",
        "⚡ B O Y K T A ⚡",
    ]

    @staticmethod
    def get_random_animation(prefix: str = "") -> str:
        """الحصول على رسالة انتظار عشوائية"""
        import random
        animation_type = random.choice(['dots', 'progress', 'boykta'])

        if animation_type == 'dots':
            pattern = random.choice(LoadingAnimation.DOTS_PATTERNS)
        elif animation_type == 'progress':
            pattern = random.choice(LoadingAnimation.PROGRESS_PATTERNS)
        else:
            pattern = random.choice(LoadingAnimation.BOYKTA_PATTERNS)

        return f"{pattern}\n{prefix}" if prefix else pattern

    @staticmethod
    async def send_animated_message(message, text: str, duration: int = 6):
        """إرسال رسالة متحركة"""
        import asyncio
        import random

        animation_type = random.choice(['dots', 'progress', 'boykta'])

        if animation_type == 'dots':
            patterns = LoadingAnimation.DOTS_PATTERNS
        elif animation_type == 'progress':
            patterns = LoadingAnimation.PROGRESS_PATTERNS
        else:
            patterns = LoadingAnimation.BOYKTA_PATTERNS

        sent_message = await message.reply_text(f"{patterns[0]}\n{text}")

        try:
            for i in range(duration):
                await asyncio.sleep(1)
                pattern = patterns[i % len(patterns)]
                try:
                    await sent_message.edit_text(f"{pattern}\n{text}")
                except:
                    pass
        except:
            pass

        return sent_message

def get_cancel_button():
    """الحصول على زر إلغاء"""
    return InlineKeyboardButton("❌ إلغاء والعودة للقائمة", callback_data="cancel_operation")

def clear_user_operations(context: ContextTypes.DEFAULT_TYPE):
    """إلغاء جميع العمليات السابقة وتنظيف البيانات المؤقتة"""
    keys_to_clear = [
        'waiting_for', 
        'pending_photo', 
        'collected_photos', 
        'edit_pending', 
        'edit_pending_multiple',
        'edit_image',
        'ocr_photos',
        'last_extracted_text',
        'admin_action'
    ]
    for key in keys_to_clear:
        if key in context.user_data:
            del context.user_data[key]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر البدء - مع دعم المجموعات"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    is_group = chat_id < 0

    if is_group:
        await update.message.reply_text(
            "👋 مرحباً! أنا بوت مساعدة الطلاب.\n\n"
            "للاستخدام في المجموعة:\n"
            "• استخدم الأوامر الموجهة مثل: /بحث@اسم_البوت\n"
            "• أو تحدث معي مباشرة\n\n"
            "للاستخدام الكامل، راسلني في محادثة خاصة! 😊"
        )
        return

    is_subscribed = await check_channel_membership(user.id, context, chat_id)
    if not is_subscribed:
        await send_subscription_required_message(update, context)
        return

    keyboard = [
        [KeyboardButton("📚 مساعدة في الدراسة"), KeyboardButton("🔍 البحث")],
        [KeyboardButton("💻 مساعدة برمجة",), KeyboardButton("🎨 إنشاء صورة")],
        [KeyboardButton("✏️ تحرير صورة"), KeyboardButton("📸 تحليل صورة")],
        [KeyboardButton("🎬 إنشاء فيديو"), KeyboardButton("❓ المساعدة")]
    ]

    if is_super_admin(user.id):
        keyboard.append([KeyboardButton("⚙️ لوحة التحكم")])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    quota = db.get_user_quota(user.id)
    limits = SUBSCRIPTION_LIMITS[quota['tier']]

    welcome_text = f"""🎓 أهلاً {user.first_name}!

أنا بوت ذكي لمساعدة الطلاب 🤖

✨ **ما يمكنني فعله:**
📚 حل التمارين والأسئلة الدراسية من الصور
🔢 حل المعادلات الرياضية (`/حل`)
📖 البحث في الكتب (`/كتاب`)
🔍 البحث عن المواد الدراسية
💻 مساعدتك في البرمجة والأكواد
📸 استخراج النص من الصور وتحليلها
📄 معالجة الملفات (PDF, DOCX, TXT) واستخراج النص
🎨 إنشاء صور بالذكاء الاصطناعي
✏️ تحرير الصور
🎬 تحويل النص/الصور إلى فيديو

**📊 حصتك اليومية ({quota['tier']}):**
🎨 الصور: {quota['daily_used']}/{limits['daily_images']}
🎬 الفيديو: {quota['daily_video_used']}/{limits['daily_videos']}

**للبدء:**
- أرسل سؤالك مباشرة
- أو استخدم الأزرار أدناه
- استخدم الأوامر المتخصصة

دعنا نبدأ رحلة التعلم معاً! 🚀
    """

    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def solve_next_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حل التمرين التالي في محادثة منفصلة"""
    query = update.callback_query
    await query.answer()

    exercise_data = context.user_data.get('math_exercise')
    if not exercise_data:
        await query.edit_message_text("❌ انتهت صلاحية التمرين. ابدأ تمريناً جديداً")
        return

    exercise_data['current_exercise'] += 1
    exercise_num = exercise_data['current_exercise']

    await query.edit_message_text(f"🧮 جاري حل التمرين {exercise_num}...")

    # استخراج التمرين المحدد من التحليل
    extract_prompt = f"""من التحليل التالي، استخرج **التمرين رقم {exercise_num}** فقط:

{exercise_data['analysis']}

قدم:
1. البيانات المعطاة في هذا التمرين
2. المطلوب بالضبط
3. نص التمرين كاملاً"""

    exercise_extraction = ai.grok4(extract_prompt)

    await query.message.reply_text(
        f"📋 **التمرين {exercise_num}:**\n\n{exercise_extraction}"
    )

    # حل التمرين في محادثة منفصلة (بدون سياق التمارين السابقة)
    await query.message.reply_text(f"🤔 جاري حل التمرين {exercise_num}...")

    solve_prompt = f"""أنت معلم خبير ومتخصص في جميع المواد الدراسية (رياضيات، فيزياء، كيمياء، لغة عربية، إنجليزية، تاريخ، جغرافيا، أحياء، علوم، إلخ). 

قم بحل/الإجابة على التمرين/السؤال التالي بشكل تفصيلي:

{exercise_extraction}

**النص الأصلي للمرجع (مع البيانات/الرسوم):**
{exercise_data['original_text'][:1000]}...

**التعليمات:**
1. حدد نوع المادة بدقة (رياضيات، فيزياء، كيمياء، لغة عربية، إنجليزية، تاريخ، جغرافيا، أحياء، علوم، إلخ)
2. **اذكر البيانات/الرسوم/الجداول المعطاة** إن وُجدت (مثل: "يوجد رسم بياني..." أو "جدول يحتوي على...")
3. اشرح المعطيات بوضوح كامل
4. حدد المطلوب بالضبط
5. قدم الحل/الإجابة خطوة بخطوة بالتفصيل الكامل
6. اعرض النتيجة النهائية بوضوح بارز
7. تحقق من صحة الإجابة إن أمكن
8. **إذا كان هناك إشارة مرجعية** (مثل: "كما ذكرنا في التمرين السابق")، أشر إليها بوضوح

**قواعد التنسيق (للمسائل الرياضية/العلمية):**
✓ وضوح التنسيق: اكتب جميع المعادلات والنتائج بتنسيق واضح ومرئي ومفهوم
✓ تجنب أوامر LaTeX الخام: لا تستخدم \\frac أو \\sqrt أو \\cdot
✓ استخدم الرموز البديلة: (a/b) بدلاً من \\frac{{a}}{{b}}، و√x بدلاً من \\sqrt{{x}}
✓ الترقيم: رقّم الخطوات بوضوح (1. 2. 3.)
✓ النتيجة النهائية: ضعها في إطار واضح

**ملاحظات مهمة:**
- هذا تمرين منفصل، ركز عليه فقط
- اشرح بلغة سهلة ومفهومة للطالب باللغة العربية الفصحى
- استخدم أمثلة إن لزم الأمر
- للتمارين العلمية: اعرض الحسابات والخطوات بدقة
- للأسئلة الأدبية/اللغوية/التاريخية: قدم إجابة شاملة ومنطقية ومنظمة"""

    solution = ai.grok4(solve_prompt)

    # حفظ الحل في محادثة منفصلة
    if 'exercises' not in exercise_data:
        exercise_data['exercises'] = []

    exercise_data['exercises'].append({
        'number': exercise_num,
        'extraction': exercise_extraction,
        'solution': solution
    })

    # إرسال الحل
    if len(solution) > 4096:
        parts = [solution[i:i+4096] for i in range(0, len(solution), 4096)]
        for i, part in enumerate(parts):
            if i == 0:
                await query.message.reply_text(f"✅ **حل التمرين {exercise_num}:**\n\n{part}")
            else:
                await query.message.reply_text(part)
    else:
        await query.message.reply_text(f"✅ **حل التمرين {exercise_num}:**\n\n{solution}")

    # خيارات المتابعة
    keyboard = [
        [InlineKeyboardButton("❓ توضيح أكثر لهذا التمرين", callback_data=f"clarify_exercise_{exercise_num}")],
        [InlineKeyboardButton("▶️ التمرين التالي", callback_data="solve_exercise_next")],
        [InlineKeyboardButton("🔄 إعادة حل هذا التمرين", callback_data=f"resolve_exercise_{exercise_num}")],
        [InlineKeyboardButton("📋 عرض جميع الحلول", callback_data="show_all_exercises")],
        [InlineKeyboardButton("✅ إنهاء", callback_data="finish_exercise")],
        [get_cancel_button()]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("💡 **ماذا تريد أن تفعل؟**", reply_markup=reply_markup)

async def clarify_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """توضيح إضافي لتمرين محدد"""
    query = update.callback_query
    await query.answer()

    exercise_num = int(query.data.split('_')[-1])
    exercise_data = context.user_data.get('math_exercise')

    if not exercise_data:
        await query.edit_message_text("❌ انتهت صلاحية التمرين")
        return

    await query.edit_message_text(f"🔍 جاري شرح التمرين {exercise_num} بشكل أوضح...")

    # البحث عن التمرين في القائمة
    current_exercise = None
    for ex in exercise_data.get('exercises', []):
        if ex['number'] == exercise_num:
            current_exercise = ex
            break

    clarify_prompt = f"""قدم شرحاً مبسطاً وتوضيحاً إضافياً للتمرين رقم {exercise_num}:

**التمرين:**
{current_exercise['extraction'] if current_exercise else exercise_data['original_text']}

اشرح:
1. البيانات المعطاة بالتفصيل
2. ما المطلوب بالضبط
3. الخطوات الأساسية للحل
4. أي ملاحظات مهمة
5. أمثلة مشابهة إن أمكن

**قواعد التنسيق الرياضي (إذا كان رياضياً):**
✓ وضوح التنسيق: اكتب جميع المعادلات بتنسيق واضح ومفهوم
✓ تجنب أوامر LaTeX الخام: لا تستخدم \\frac أو \\sqrt أو \\cdot
✓ استخدم الرموز البديلة: (a/b) بدلاً من \\frac{{a}}{{b}}، و√x بدلاً من \\sqrt{{x}}"""

    clarification = ai.grok4(clarify_prompt)

    await query.message.reply_text(f"💡 **توضيح التمرين {exercise_num}:**\n\n{clarification}")

    keyboard = [
        [InlineKeyboardButton("▶️ المتابعة للتمرين التالي", callback_data="solve_exercise_next")],
        [InlineKeyboardButton("🔄 إعادة الحل", callback_data=f"resolve_exercise_{exercise_num}")],
        [get_cancel_button()]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("💡 **الخطوة التالية؟**", reply_markup=reply_markup)

async def resolve_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعادة حل تمرين محدد بطريقة مختلفة"""
    query = update.callback_query
    await query.answer()

    exercise_num = int(query.data.split('_')[-1])
    exercise_data = context.user_data.get('math_exercise')

    if not exercise_data:
        await query.edit_message_text("❌ انتهت صلاحية التمرين")
        return

    await query.edit_message_text(f"🔄 جاري إعادة حل التمرين {exercise_num} بطريقة مختلفة...")

    # البحث عن التمرين في القائمة
    current_exercise = None
    for ex in exercise_data.get('exercises', []):
        if ex['number'] == exercise_num:
            current_exercise = ex
            break

    resolve_prompt = f"""أعد حل التمرين رقم {exercise_num} بطريقة مختلفة أو بشرح أبسط:

**التمرين:**
{current_exercise['extraction'] if current_exercise else exercise_data['original_text']}

قدم:
1. طريقة حل بديلة إن وجدت
2. شرح أبسط وأوضح
3. نصائح لفهم أفضل
4. حل خطوة بخطوة بتفصيل أكثر

**قواعد التنسيق الرياضي الإلزامية:**
✓ وضوح التنسيق: اكتب جميع المعادلات والنتائج بتنسيق واضح ومفهوم
✓ تجنب أوامر LaTeX الخام: لا تستخدم \\frac أو \\sqrt أو \\cdot في الإخراج
✓ استخدم الرموز البديلة: (a/b) بدلاً من \\frac{{a}}{{b}}، و√x بدلاً من \\sqrt{{x}}
✓ الترقيم: رقّم الخطوات بوضوح (1. 2. 3.)"""

    new_solution = ai.grok4(resolve_prompt)

    if len(new_solution) > 4096:
        parts = [new_solution[i:i+4096] for i in range(0, len(new_solution), 4096)]
        for i, part in enumerate(parts):
            if i == 0:
                await query.message.reply_text(f"🔄 **حل بديل للتمرين {exercise_num}:**\n\n{part}")
            else:
                await query.message.reply_text(part)
    else:
        await query.message.reply_text(f"🔄 **حل بديل للتمرين {exercise_num}:**\n\n{new_solution}")

    keyboard = [
        [InlineKeyboardButton("▶️ التمرين التالي", callback_data="solve_exercise_next")],
        [get_cancel_button()]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("💡 **المتابعة؟**", reply_markup=reply_markup)

async def show_all_exercises(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض جميع التمارين المحلولة"""
    query = update.callback_query
    await query.answer()

    exercise_data = context.user_data.get('math_exercise')

    if not exercise_data or not exercise_data.get('exercises'):
        await query.edit_message_text("❌ لا يوجد تمارين محلولة حتى الآن")
        return

    await query.edit_message_text("📋 جاري إعداد ملخص جميع التمارين...")

    # بناء ملخص شامل
    summary_text = "📚 **ملخص جميع التمارين المحلولة:**\n\n"

    for ex in exercise_data['exercises']:
        summary_text += f"━━━━━━━━━━━━━━━━━━━━\n"
        summary_text += f"🔢 **التمرين {ex['number']}:**\n\n"
        summary_text += f"📋 {ex['extraction'][:200]}...\n\n"
        summary_text += f"✅ **الحل:**\n{ex['solution'][:300]}...\n\n"

    summary_text += "━━━━━━━━━━━━━━━━━━━━\n"

    # إرسال الملخص
    if len(summary_text) > 4096:
        parts = [summary_text[i:i+4096] for i in range(0, len(summary_text), 4096)]
        for i, part in enumerate(parts):
            await query.message.reply_text(part)
    else:
        await query.message.reply_text(summary_text)

    keyboard = [
        [InlineKeyboardButton("▶️ متابعة التمارين", callback_data="solve_exercise_next")],
        [InlineKeyboardButton("✅ إنهاء", callback_data="finish_exercise")],
        [get_cancel_button()]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("💡 **ماذا بعد؟**", reply_markup=reply_markup)

async def finish_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إنهاء حل التمرين"""
    query = update.callback_query
    await query.answer()

    if 'math_exercise' in context.user_data:
        del context.user_data['math_exercise']

    keyboard = [
        [InlineKeyboardButton("🧮 حل تمرين جديد", callback_data="solve_another_exercise")],
        [get_cancel_button()]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "✅ **تم إنهاء التمرين بنجاح!**\n\n"
        "يمكنك الآن:\n"
        "• حل تمرين جديد\n"
        "• العودة للقائمة الرئيسية",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المساعدة"""
    help_text = (
        "🤖 **دليل استخدام البوت:**\n\n"
        "**📚 للمساعدة في الدراسة:**\n"
        "- أرسل سؤالك مباشرة\n"
        "- مثال: \"اشرح لي قانون نيوتن الثاني\"\n\n"
        "**🔢 للرياضيات:**\n"
        "- `/حل [معادلة]` - حل المعادلات\n"
        "- **مثال:** `/حل x**2-4`\n"
        "- أرسل صورة التمرين → اختر \"🧮 حل التمرين الرياضي\"\n\n"
        "**📖 للبحث في الكتب:**\n"
        "- `/كتاب [موضوع]` - البحث في ملايين الكتب\n"
        "- مثال: `/كتاب الفيزياء الحديثة`\n\n"
        "**🔍 للبحث:**\n"
        "- اضغط زر \"🔍 البحث\" أو اكتب: /بحث [الموضوع]\n\n"
        "**💻 للمساعدة في البرمجة:**\n"
        "- اضغط زر \"💻 مساعدة برمجة\" أو اكتب: /كود [سؤالك]\n\n"
        "**📸 لتحليل الصور:**\n"
        "- اكتب: /تحليل ثم أرسل الصورة\n\n"
        "**📄 لتحليل الملفات:**\n"
        "- أرسل ملف PDF, DOCX, أو TXT مباشرة\n"
        "- يدعم حتى 20 ميغابايت\n\n"
        "**🎨 لإنشاء صور:**\n"
        "- اضغط زر \"🎨 إنشاء صورة\"\n\n"
        "**🎬 لإنشاء فيديو:**\n"
        "- /فيديو [الوصف]\n\n"
        "**💡 نصيحة:** يمكنك إلغاء أي عملية بالضغط على زر \"❌ إلغاء\"\n\n"
        "أي سؤال آخر؟ فقط اسأل! 😊"
    )
    await update.message.reply_text(help_text)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لوحة تحكم الأدمن المحسّنة"""
    user_id = update.effective_user.id

    if not is_super_admin(user_id):
        await update.message.reply_text("⛔ هذا الأمر متاح للمشرفين فقط!")
        return

    keyboard = [
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 إدارة المجموعات", callback_data="admin_groups")],
        [InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban"),
         InlineKeyboardButton("✅ فك الحظر", callback_data="admin_unban")],
        [InlineKeyboardButton("🔇 كتم مستخدم", callback_data="admin_mute"),
         InlineKeyboardButton("🔊 إلغاء الكتم", callback_data="admin_unmute")],
        [get_cancel_button()]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "⚙️ **لوحة تحكم الأدمن**\n\nاختر الإجراء المطلوب:",
        reply_markup=reply_markup
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أزرار لوحة التحكم والميزات الإضافية"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user

    # التحقق من الاشتراك لكل عملية
    if query.data != "check_subscription" and query.data != "cancel_operation":
        is_subscribed = await check_channel_membership(user.id, context)
        if not is_subscribed:
            await send_subscription_required_message(update, context)
            return

    # معالجة التحقق من الاشتراك
    if query.data == "check_subscription":
        is_subscribed = await check_channel_membership(user.id, context)
        if is_subscribed:
            await query.edit_message_text("✅ **رائع! تم التحقق من اشتراكك**\n\nيمكنك الآن استخدام البوت بحرية\nاكتب /start للبدء")
        else:
            await query.answer("⚠️ لم يتم الاشتراك بعد! يرجى الاشتراك أولاً", show_alert=True)
        return

    # معالجة زر تحسين صورة أخرى
    if query.data == "start_enhance_another":
        context.user_data['waiting_for'] = 'enhance_photo'
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "✨ **جاهز لتحسين صورة جديدة**\n\n"
            "أرسل الصورة التي تريد تحسين جودتها",
            reply_markup=reply_markup
        )
        return

    # معالجة زر حل تمرين آخر
    if query.data == "solve_another_exercise":
        # حذف التمرين السابق إن وجد
        if 'math_exercise' in context.user_data:
            del context.user_data['math_exercise']

        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🧮 **جاهز لحل تمرين رياضي جديد!**\n\n"
            "📸 أرسل صورة التمرين الرياضي الذي تريد حله\n\n"
            "💡 تأكد من:\n"
            "• وضوح الصورة\n"
            "• قراءة النص بشكل واضح\n"
            "• جودة عالية للصورة",
            reply_markup=reply_markup
        )
        return

    # معالجة حل التمرين التالي (النظام الجديد)
    if query.data == "solve_exercise_next":
        await solve_next_exercise(update, context)
        return

    # معالجة توضيح تمرين
    if query.data.startswith("clarify_exercise_"):
        await clarify_exercise(update, context)
        return

    # معالجة إعادة حل تمرين
    if query.data.startswith("resolve_exercise_"):
        await resolve_exercise(update, context)
        return

    # معالجة عرض جميع التمارين
    if query.data == "show_all_exercises":
        await show_all_exercises(update, context)
        return

    # معالجة إنهاء التمرين
    if query.data == "finish_exercise":
        await finish_exercise(update, context)
        return

    # معالجة خيارات الصورة
    if query.data == "photo_ocr":
        await process_photo_ocr(update, context)
        return

    if query.data == "photo_edit":
        await process_photo_edit(update, context)
        return

    if query.data == "photo_math_solve":
        await process_photo_math_solve(update, context)
        return

    # معالجة الحل التلقائي للأسئلة المحددة
    if query.data == "auto_solve_questions":
        await auto_solve_detected_questions(update, context)
        return

    # معالجة تحسين جودة الصور
    if query.data.startswith("enhance:"):
        image_url = query.data.replace("enhance:", "").strip()

        loading_msg = LoadingAnimation.get_random_animation("🎁 جاري تحسين جودة الصورة إلى 8K...")
        await query.edit_message_text(loading_msg)

        try:
            enhanced_url = ai.quality_enhancer(image_url)

            if ai.is_valid_image_url(enhanced_url):
                await query.message.reply_photo(
                    photo=enhanced_url,
                    caption="✨ **تم تحسين الجودة بنجاح!**\n\n"
                            "🎯 تحسينات:\n"
                            "• دقة محسّنة حتى 8K\n"
                            "• ألوان أكثر وضوحاً\n"
                            "• تفاصيل أدق وأوضح"
                )

                keyboard = [
                    [InlineKeyboardButton("✏️ تحرير هذه الصورة", callback_data=f"start_edit:{enhanced_url}")],
                    [InlineKeyboardButton("🔄 تحسين المزيد", callback_data=f"enhance:{enhanced_url}")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("💡 **خيارات إضافية:**", reply_markup=reply_markup)
            else:
                keyboard = [[get_cancel_button()]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text(
                    "⚠️ عذراً، حدث خطأ في تحسين الجودة.\nتأكد من أن الصورة صالحة وحاول مرة أخرى.",
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Error enhancing image quality: {e}")
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                "⚠️ حدث خطأ غير متوقع أثناء تحسين الجودة.\nيرجى المحاولة مرة أخرى.",
                reply_markup=reply_markup
            )
        return

    if query.data == "photo_enhance":
        await process_photo_enhance(update, context)
        return

    # معالجة خيارات OCR القديمة
    if query.data.startswith("ocr_extract") or query.data.startswith("ocr_trans_") or query.data == "ocr_back_menu":
        await handle_ocr_option(update, context)
        return
    
    # معالجة خيارات OCR الجديدة - مباشرة بدون سؤال المستخدم
    if query.data == "ocr_explain":
        extracted_text = context.user_data.get('extracted_full_text', '')
        if not extracted_text:
            await query.answer("⚠️ النص غير متوفر، أرسل صورة جديدة", show_alert=True)
            return
        
        loading_msg = await query.edit_message_text("📖 جاري الشرح المفصل...")
        prompt = f"اشرح النص التالي بالتفصيل وبطريقة مبسطة:\n\n{extracted_text}"
        explanation = ai.grok4(prompt)
        
        await query.message.reply_text(f"📖 **الشرح المفصل:**\n\n{explanation}")
        await loading_msg.delete()
        return
    
    if query.data == "ocr_solve":
        extracted_text = context.user_data.get('extracted_full_text', '')
        if not extracted_text:
            await query.answer("⚠️ النص غير متوفر، أرسل صورة جديدة", show_alert=True)
            return
        
        loading_msg = await query.edit_message_text("✍️ جاري حل المسائل...")
        prompt = f"حل جميع المسائل والتمارين الموجودة في النص التالي بالتفصيل مع الخطوات:\n\n{extracted_text}"
        solution = ai.grok4(prompt)
        
        await query.message.reply_text(f"✍️ **حل المسائل:**\n\n{solution}")
        await loading_msg.delete()
        return
    
    if query.data == "ocr_translate":
        extracted_text = context.user_data.get('extracted_full_text', '')
        if not extracted_text:
            await query.answer("⚠️ النص غير متوفر، أرسل صورة جديدة", show_alert=True)
            return
        
        loading_msg = await query.edit_message_text("🔄 جاري الترجمة...")
        
        is_arabic = any('\u0600' <= char <= '\u06FF' for char in extracted_text[:100])
        if is_arabic:
            translated = ai.translate_to_english(extracted_text)
            await query.message.reply_text(f"🔄 **الترجمة إلى الإنجليزية:**\n\n{translated}")
        else:
            prompt = f"ترجم النص التالي إلى العربية:\n\n{extracted_text}"
            translated = ai.grok4(prompt)
            await query.message.reply_text(f"🔄 **الترجمة إلى العربية:**\n\n{translated}")
        
        await loading_msg.delete()
        return
    
    if query.data == "ocr_summary":
        extracted_text = context.user_data.get('extracted_full_text', '')
        if not extracted_text:
            await query.answer("⚠️ النص غير متوفر، أرسل صورة جديدة", show_alert=True)
            return
        
        loading_msg = await query.edit_message_text("📝 جاري إنشاء الملخص...")
        prompt = f"لخص النص التالي بشكل شامل ومختصر:\n\n{extracted_text}"
        summary = ai.grok4(prompt)
        
        await query.message.reply_text(f"📝 **الملخص:**\n\n{summary}")
        await loading_msg.delete()
        return
    
    if query.data == "ocr_search":
        extracted_text = context.user_data.get('extracted_full_text', '')
        if not extracted_text:
            await query.answer("⚠️ النص غير متوفر، أرسل صورة جديدة", show_alert=True)
            return
        
        loading_msg = await query.edit_message_text("🔍 جاري البحث عن معلومات...")
        
        first_line = extracted_text.split('\n')[0][:100]
        search_results = ai.search_web(first_line)
        
        await query.message.reply_text(f"🔍 **نتائج البحث:**\n\n{search_results}")
        await loading_msg.delete()
        return
    
    if query.data == "ocr_qa":
        extracted_text = context.user_data.get('extracted_full_text', '')
        if not extracted_text:
            await query.answer("⚠️ النص غير متوفر، أرسل صورة جديدة", show_alert=True)
            return
        
        loading_msg = await query.edit_message_text("💡 جاري توليد الأسئلة والأجوبة...")
        prompt = f"اقرأ النص التالي وأنشئ 5 أسئلة مهمة مع أجوبتها:\n\n{extracted_text}"
        qa = ai.grok4(prompt)
        
        await query.message.reply_text(f"💡 **أسئلة وأجوبة:**\n\n{qa}")
        await loading_msg.delete()
        return
    
    if query.data == "ocr_show_full":
        extracted_text = context.user_data.get('extracted_full_text', '')
        if not extracted_text:
            await query.answer("⚠️ النص غير متوفر، أرسل صورة جديدة", show_alert=True)
            return
        
        if len(extracted_text) > 4000:
            parts = [extracted_text[i:i+4000] for i in range(0, len(extracted_text), 4000)]
            for i, part in enumerate(parts):
                await query.message.reply_text(f"📄 **النص الكامل ({i+1}/{len(parts)}):**\n\n{part}")
        else:
            await query.message.reply_text(f"📄 **النص الكامل:**\n\n{extracted_text}")
        
        await query.answer("✅ تم عرض النص الكامل")
        return

    # معالجة الضغط على زر "انتهيت" للصور
    if query.data == "photos_done_edit":
        await process_multiple_photos_edit(update, context)
        return

    if query.data == "photos_done_analyze":
        await process_multiple_photos_analyze(update, context)
        return

    # معالجة زر الإلغاء
    if query.data == "cancel_operation":
        # حذف البيانات المؤقتة
        context.user_data.clear()
        await query.edit_message_text("❌ تم إلغاء العملية\n\nاكتب /start للعودة إلى القائمة الرئيسية")
        return

    # معالجة إنشاء صور بحجم محدد
    if query.data.startswith("imgsize:"):
        parts = query.data.split(":", 2)
        size = parts[1]
        text = parts[2]

        loading_msg = LoadingAnimation.get_random_animation(f"🎨 جاري إنشاء صورة...")
        await query.edit_message_text(loading_msg)

        try:
            # استخدام Nano Banana (الأحدث والأفضل)
            image_url = ai.nano_banana(text)

            if ai.is_valid_image_url(image_url):
                await query.message.reply_photo(
                    photo=image_url,
                    caption=f"🎨 {text}"
                )

                keyboard = [
                       [InlineKeyboardButton("✏️ تحرير هذه الصورة", callback_data=f"start_edit:{image_url}")],
                    [InlineKeyboardButton("🎁 تحسين الجودة 8K", callback_data=f"enhance:{image_url}")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("💡 يمكنك تحرير الصورة أو تحسين جودتها:", reply_markup=reply_markup)
            else:
                # محاولة مرة أخرى
                await query.message.reply_text("🔄 جاري المحاولة مرة أخرى...")
                image_url = ai.nano_banana(text)

                if ai.is_valid_image_url(image_url):
                    await query.message.reply_photo(
                        photo=image_url,
                        caption=f"🎨 {text}"
                    )

                    keyboard = [
                        [InlineKeyboardButton("✏️ تحرير هذه الصورة", callback_data=f"start_edit:{image_url}")],
                        [get_cancel_button()]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.message.reply_text("💡 يمكنك تحرير الصورة:", reply_markup=reply_markup)
                else:
                    keyboard = [[get_cancel_button()]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.message.reply_text(
                        "⚠️ عذراً، خدمة إنشاء الصور غير متاحة حالياً.\n"
                        "يرجى المحاولة مرة أخرى بعد قليل.",
                        reply_markup=reply_markup
                    )
        except Exception as e:
            logger.error(f"Error in image generation: {e}")
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                "⚠️ حدث خطأ غير متوقع.\nيرجى المحاولة مرة أخرى.",
                reply_markup=reply_markup
            )
        return

    # معالجة إنشاء صور تلقائي
    if query.data.startswith("imgauto:"):
        text = query.data.replace("imgauto:", "").strip()

        loading_msg = LoadingAnimation.get_random_animation("🎨 جاري إنشاء الصورة...")
        await query.edit_message_text(loading_msg)

        try:
            # استخدام Nano Banana
            image_url = ai.nano_banana(text)

            if ai.is_valid_image_url(image_url):
                await query.message.reply_photo(photo=image_url, caption=f"🎨 {text}")

                keyboard = [
                    [InlineKeyboardButton("✏️ تحرير هذه الصورة", callback_data=f"start_edit:{image_url}")],
                    [InlineKeyboardButton("🎁 تحسين الجودة 8K", callback_data=f"enhance:{image_url}")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("💡 يمكنك تحرير الصورة أو تحسين جودتها:", reply_markup=reply_markup)
                return

            # محاولة مرة أخرى
            await query.message.reply_text("🔄 جاري المحاولة مرة أخرى...")
            image_url = ai.nano_banana(text)

            if ai.is_valid_image_url(image_url):
                await query.message.reply_photo(photo=image_url, caption=f"🎨 {text}")

                keyboard = [
                    [InlineKeyboardButton("✏️ تحرير هذه الصورة", callback_data=f"start_edit:{image_url}")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("💡 يمكنك تحرير الصورة:", reply_markup=reply_markup)
                return

            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                "⚠️ عذراً، خدمة إنشاء الصور غير متاحة حالياً.\n"
                "يرجى المحاولة مرة أخرى بعد قليل.",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error in auto image: {e}")
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                "⚠️ حدث خطأ غير متوقع.\nيرجى المحاولة مرة أخرى.",
                reply_markup=reply_markup
            )
        return

    # معالجة بدء تحرير صورة
    if query.data.startswith("start_edit:"):
        photo_url = query.data.replace("start_edit:", "")
        context.user_data['edit_pending'] = photo_url
        context.user_data['waiting_for_edit_desc'] = True

        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "✏️ **أرسل وصف التعديل المطلوب:**\n\n"
            "مثال: اجعل الخلفية زرقاء\n"
            "مثال: أضف تأثير نيون\n"
            "مثال: حول الصورة إلى أبيض وأسود",
            reply_markup=reply_markup
        )
        return

    # معالجة تحرير الصور
    if query.data.startswith("edit:"):
        model = query.data.replace("edit:", "")
        edit_data = context.user_data.get('edit_image')

        if not edit_data:
            await query.edit_message_text("❌ انتهت صلاحية طلب التحرير\nاكتب /start للعودة")
            return

        photo_url = edit_data['url']
        edit_query = edit_data['query']

        loading_msg = LoadingAnimation.get_random_animation(f"🍌 جاري تحرير الصورة باستخدام {model}...")
        await query.edit_message_text(loading_msg)

        try:
            # جرب Nano Banana أولاً (الأسرع والأفضل)
            logger.info("🍌 محاولة التحرير بـ Nano Banana...")
            image_url = ai.nano_banana(edit_query, [photo_url])

            if ai.is_valid_image_url(image_url):
                logger.info("✅ نجح التحرير بـ Nano Banana")
                await query.message.reply_photo(
                    photo=image_url,
                    caption=f"✨ تم التحرير بـ Nano Banana: {edit_query}"
                )

                keyboard = [
                    [InlineKeyboardButton("✏️ تحرير مرة أخرى", callback_data=f"start_edit:{image_url}")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("💡 يمكنك تحرير الصورة مرة أخرى:", reply_markup=reply_markup)

                del context.user_data['edit_image']
                return

            # إذا فشل، جرب GPT-Imager
            logger.warning("⚠️ Nano Banana فشل، محاولة GPT-Imager...")
            await query.message.reply_text("🔄 جاري المحاولة بنموذج احتياطي...")
            image_url = ai.gpt_imager(edit_query, photo_url)

            if ai.is_valid_image_url(image_url):
                logger.info("✅ نجح التحرير بـ GPT-Imager")
                await query.message.reply_photo(
                    photo=image_url,
                    caption=f"✨ تم التحرير بـ GPT-Imager: {edit_query}"
                )

                keyboard = [
                    [InlineKeyboardButton("✏️ تحرير مرة أخرى", callback_data=f"start_edit:{image_url}")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("💡 يمكنك تحرير الصورة مرة أخرى:", reply_markup=reply_markup)

                del context.user_data['edit_image']
            else:
                logger.error("❌ فشل التحرير بجميع النماذج")
                keyboard = [[get_cancel_button()]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("عذراً، حدث خطأ في التحرير. حاول مرة أخرى", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"💥 Error editing: {type(e).__name__} - {str(e)}")
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("عذراً، حدث خطأ في التحرير", reply_markup=reply_markup)
        return

    # معالجة عرض النص الكامل للملف
    if query.data == "show_full_text":
        extracted_text = context.user_data.get('last_extracted_text', '')
        document_name = context.user_data.get('document_name', 'الملف')

        if not extracted_text:
            await query.edit_message_text("❌ لم يتم العثور على نص محفوظ")
            return

        await query.edit_message_text(f"📄 جاري عرض النص الكامل من {document_name}...")

        # إرسال النص على دفعات إذا كان طويلاً
        if len(extracted_text) > 4000:
            parts = [extracted_text[i:i+4000] for i in range(0, len(extracted_text), 4000)]
            for i, part in enumerate(parts):
                if i == 0:
                    await query.message.reply_text(f"📝 **النص الكامل ({i+1}/{len(parts)}):**\n\n{part}")
                else:
                    await query.message.reply_text(f"📝 **({i+1}/{len(parts)}):**\n\n{part}")
        else:
            await query.message.reply_text(f"📝 **النص الكامل:**\n\n{extracted_text}")

        keyboard = [
            [InlineKeyboardButton("💡 شرح وتحليل", callback_data="analyze_document")],
            [InlineKeyboardButton("🔍 البحث", callback_data="search_last_ocr")],
            [get_cancel_button()]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("💡 **خيارات إضافية:**", reply_markup=reply_markup)
        return

    # معالجة تحليل المستند
    if query.data == "analyze_document":
        extracted_text = context.user_data.get('last_extracted_text', '')
        document_name = context.user_data.get('document_name', 'الملف')

        if not extracted_text:
            await query.edit_message_text("❌ لم يتم العثور على نص محفوظ")
            return

        await query.edit_message_text("🤔 جاري تحليل المحتوى...")

        analysis_prompt = f"""تم استخراج النص التالي من ملف {document_name}:

{extracted_text[:3000]}

قم بما يلي:
1. إذا كان تمريناً أو واجبا قدم الحل التفصيلي
2. إذا كان نصاً تعليمياً قدم ملخصاً وشرحاً مبسطاً
3. اشرح المصطلحات والمفاهيم المهمة
4. قدم أمثلة إضافية إذا لزم الأمر

**قواعد التنسيق الرياضي (إذا كان المحتوى رياضياً):**
✓ وضوح التنسيق: اكتب جميع المعادلات والنتائج بتنسيق واضح ومفهوم
✓ تجنب أوامر LaTeX الخام: لا تستخدم \\frac أو \\sqrt أو \\cdot
✓ استخدم الرموز البديلة: (a/b) بدلاً من \\frac{{a}}{{b}}، و√x بدلاً من \\sqrt{{x}}
✓ الترقيم: رقّم الخطوات بوضوح (1. 2. 3.)

قدم إجابة شاملة ومفيدة للطالب."""

        analysis = ai.grok4(analysis_prompt)

        if len(analysis) > 4096:
            parts = [analysis[i:i+4096] for i in range(0, len(analysis), 4096)]
            for i, part in enumerate(parts):
                if i == 0:
                    await query.message.reply_text(f"✅ **التحليل والشرح:**\n\n{part}")
                else:
                    await query.message.reply_text(part)
        else:
            await query.message.reply_text(f"✅ **التحليل والشرح:**\n\n{analysis}")

        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("اكتب /start للعودة", reply_markup=reply_markup)
        return

    # معالجة البحث عن النص المستخرج
    if query.data == "search_last_ocr" or query.data.startswith("search_extracted:") or query.data.startswith("auto_search:"):
        if query.data == "search_last_ocr":
            search_text = context.user_data.get('last_extracted_text', '')
            if not search_text:
                await query.edit_message_text("❌ لم يتم العثور على نص للبحث عنه")
                return
        elif query.data.startswith("search_extracted:"):
            search_text = query.data.replace("search_extracted:", "").strip()
        else:
            search_text = query.data.replace("auto_search:", "").strip()

        await query.edit_message_text("🔍 جاري البحث عن المحتوى...")

        search_result = ai.search(search_text)

        if len(search_result) > 4096:
            parts = [search_result[i:i+4096] for i in range(0, len(search_result), 4096)]
            for i, part in enumerate(parts):
                if i == 0:
                    await query.message.reply_text(part)
                else:
                    await query.message.reply_text(part)
        else:
            await query.message.reply_text(search_result)

        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("اكتب /start للعودة للقائمة", reply_markup=reply_markup)
        return

    # معالجة أزرار الأدمن
    if not is_super_admin(update.effective_user.id):
        await query.edit_message_text("⛔ غير مصرح لك!")
        return

    if query.data == "admin_broadcast":
        context.user_data['waiting_for'] = 'broadcast_message'
        await query.edit_message_text(
            "📢 **إرسال رسالة جماعية**\n\n"
            "اكتب الرسالة التي تريد إرسالها لجميع المستخدمين:\n\n"
            "💡 يمكنك استخدام:\n"
            "• نص عادي\n"
            "• تنسيق Markdown\n"
            "• روابط وصور"
        )
        return

    if query.data == "admin_stats":
        stats = db.get_stats()
        stats_text = (
            f"**إحصائيات البوت:**\n\n"
            f"📊 إجمالي المستخدمين: {stats['total_users']}\n"
            f"💬 إجمالي الرسائل: {stats['total_messages']}\n"
            f"🚫 المستخدمون المحظورون: {stats['banned_users']}\n"
            f"🔇 المستخدمون المكتومون: {stats['muted_users']}\n"
            f"📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(stats_text, reply_markup=reply_markup)
    
    elif query.data == "admin_groups":
        groups = db.get_all_groups()
        if not groups:
            await query.edit_message_text("❌ لا توجد مجموعات مسجلة بعد.")
            return
        
        groups_text = "**📋 المجموعات المسجلة:**\n\n"
        keyboard = []
        
        for group in groups[:10]:
            group_id = group['group_id']
            group_name = group['group_name'][:30]
            settings = db.get_group_settings(group_id)
            status = "🟢 مفعّل" if settings.get('auto_moderation') else "🔴 معطل"
            
            groups_text += f"{status} **{group_name}**\n"
            groups_text += f"   معرف: `{group_id}`\n\n"
            
            keyboard.append([InlineKeyboardButton(
                f"⚙️ {group_name}", 
                callback_data=f"group_manage:{group_id}"
            )])
        
        keyboard.append([get_cancel_button()])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(groups_text, reply_markup=reply_markup)
    
    elif query.data.startswith("group_manage:"):
        group_id = int(query.data.replace("group_manage:", ""))
        settings = db.get_group_settings(group_id)
        group_info = db.get_group_info(group_id)
        
        if not group_info:
            await query.edit_message_text("❌ المجموعة غير موجودة.")
            return
        
        auto_mod_status = "✅ مفعّل" if settings.get('auto_moderation') else "❌ معطل"
        delete_status = "✅ نعم" if settings.get('delete_profanity') else "❌ لا"
        warn_status = "✅ نعم" if settings.get('warn_on_profanity') else "❌ لا"
        
        info_text = (
            f"**⚙️ إعدادات المجموعة:**\n\n"
            f"📌 الاسم: {group_info['group_name']}\n"
            f"🆔 المعرف: `{group_id}`\n\n"
            f"**الإعدادات الحالية:**\n"
            f"🤖 الرقابة التلقائية: {auto_mod_status}\n"
            f"🗑 حذف الرسائل البذيئة: {delete_status}\n"
            f"⚠️ التحذيرات: {warn_status}\n"
            f"📊 الحد الأقصى للتحذيرات: {settings.get('max_warnings', 3)}\n"
        )
        
        keyboard = [
            [InlineKeyboardButton(
                f"{'🔴 تعطيل' if settings.get('auto_moderation') else '🟢 تفعيل'} الرقابة",
                callback_data=f"toggle_mod:{group_id}"
            )],
            [InlineKeyboardButton(
                f"{'✅ تعطيل' if settings.get('delete_profanity') else '🗑 تفعيل'} حذف الرسائل",
                callback_data=f"toggle_delete:{group_id}"
            )],
            [InlineKeyboardButton(
                f"{'✅ تعطيل' if settings.get('warn_on_profanity') else '⚠️ تفعيل'} التحذيرات",
                callback_data=f"toggle_warn:{group_id}"
            )],
            [InlineKeyboardButton("📊 إحصائيات التحذيرات", callback_data=f"group_stats:{group_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_groups")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(info_text, reply_markup=reply_markup)
    
    elif query.data.startswith("toggle_mod:"):
        group_id = int(query.data.replace("toggle_mod:", ""))
        settings = db.get_group_settings(group_id)
        new_value = not settings.get('auto_moderation', False)
        db.update_group_setting(group_id, 'auto_moderation', new_value)
        
        await query.answer(f"✅ تم {'تفعيل' if new_value else 'تعطيل'} الرقابة التلقائية")
        
        # إعادة عرض الصفحة
        context.user_data['temp'] = f"group_manage:{group_id}"
        query.data = f"group_manage:{group_id}"
        await admin_callback(update, context)
    
    elif query.data.startswith("toggle_delete:"):
        group_id = int(query.data.replace("toggle_delete:", ""))
        settings = db.get_group_settings(group_id)
        new_value = not settings.get('delete_profanity', False)
        db.update_group_setting(group_id, 'delete_profanity', new_value)
        
        await query.answer(f"✅ تم {'تفعيل' if new_value else 'تعطيل'} حذف الرسائل البذيئة")
        
        query.data = f"group_manage:{group_id}"
        await admin_callback(update, context)
    
    elif query.data.startswith("toggle_warn:"):
        group_id = int(query.data.replace("toggle_warn:", ""))
        settings = db.get_group_settings(group_id)
        new_value = not settings.get('warn_on_profanity', False)
        db.update_group_setting(group_id, 'warn_on_profanity', new_value)
        
        await query.answer(f"✅ تم {'تفعيل' if new_value else 'تعطيل'} التحذيرات")
        
        query.data = f"group_manage:{group_id}"
        await admin_callback(update, context)
    
    elif query.data.startswith("group_stats:"):
        group_id = int(query.data.replace("group_stats:", ""))
        warnings_data = db.get_group_warnings_stats(group_id)
        
        stats_text = f"**📊 إحصائيات التحذيرات للمجموعة {group_id}:**\n\n"
        
        if not warnings_data:
            stats_text += "✅ لا توجد تحذيرات مسجلة"
        else:
            for user_stat in warnings_data[:10]:
                stats_text += (
                    f"👤 المستخدم: {user_stat['user_id']}\n"
                    f"⚠️ عدد التحذيرات: {user_stat['warning_count']}\n"
                    f"📅 آخر تحذير: {user_stat['last_warning']}\n\n"
                )
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data=f"group_manage:{group_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(stats_text, reply_markup=reply_markup)

    elif query.data in ["admin_ban", "admin_unban", "admin_mute", "admin_unmute"]:
        action_text = {
            "admin_ban": "حظر",
            "admin_unban": "فك حظر",
            "admin_mute": "كتم",
            "admin_unmute": "إلغاء كتم"
        }
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"أرسل معرف المستخدم (User ID) المطلوب {action_text[query.data]}:",
            reply_markup=reply_markup
        )
        context.user_data['admin_action'] = query.data

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة جميع الرسائل مع Rate Limiting ودعم المجموعات"""
    user = update.effective_user
    message = update.message
    chat_id = update.effective_chat.id
    is_group = chat_id < 0

    # في المجموعات: التحقق من شروط الرد
    if is_group:
        # إضافة المجموعة إلى قاعدة البيانات إذا لم تكن موجودة
        try:
            chat = await context.bot.get_chat(chat_id)
            db.add_group(chat_id, chat.title or "Unknown Group")
        except:
            pass
        
        # فحص الكلام البذيء في المجموعات
        if message.text and len(message.text) > 3:
            group_settings = db.get_group_settings(chat_id)
            
            # تخطي الفحص للأدمن (عام أو أدمن المجموعة)
            if group_settings.get('auto_moderation') and not is_group_admin(user.id, chat_id):
                try:
                    profanity_check = ai.check_profanity(message.text)
                    
                    if profanity_check.get('is_profane'):
                        logger.warning(f"⚠️ كلام بذيء من {user.id} في {chat_id}: {profanity_check}")
                        
                        # تسجيل الكشف
                        db.log_profanity_detection(
                            user.id, 
                            chat_id, 
                            message.text[:100], 
                            ', '.join(profanity_check.get('detected_words', [])),
                            'deleted' if group_settings.get('delete_profanity') else 'warned'
                        )
                        
                        # حذف الرسالة إذا كانت الإعدادات تسمح
                        if group_settings.get('delete_profanity'):
                            try:
                                await message.delete()
                                logger.info(f"✅ تم حذف رسالة بذيئة من {user.id}")
                            except Exception as e:
                                logger.error(f"❌ فشل حذف الرسالة: {e}")
                        
                        # إضافة تحذير
                        if group_settings.get('warn_on_profanity'):
                            db.add_warning(user.id, chat_id, f"استخدام كلام بذيء: {profanity_check.get('category')}", context.bot.id)
                            warnings_count = db.get_user_warnings(user.id, chat_id)
                            max_warnings = group_settings.get('max_warnings', 3)
                            
                            warning_msg = (
                                f"⚠️ تحذير للمستخدم {user.mention_html()}\n\n"
                                f"السبب: استخدام {profanity_check.get('category', 'كلام غير لائق')}\n"
                                f"عدد التحذيرات: {warnings_count}/{max_warnings}\n\n"
                            )
                            
                            if warnings_count >= max_warnings:
                                try:
                                    await context.bot.ban_chat_member(chat_id, user.id)
                                    warning_msg += f"❌ تم طرد المستخدم بسبب تجاوز الحد الأقصى من التحذيرات!"
                                    db.clear_warnings(user.id, chat_id)
                                    logger.info(f"🚫 تم طرد {user.id} من {chat_id} بعد {warnings_count} تحذيرات")
                                except Exception as e:
                                    warning_msg += f"⚠️ فشل طرد المستخدم. قد يحتاج البوت صلاحيات إضافية."
                                    logger.error(f"❌ فشل طرد المستخدم: {e}")
                            else:
                                warning_msg += f"💡 التزم باللغة المحترمة لتجنب الطرد من المجموعة."
                            
                            await message.reply_text(warning_msg, parse_mode='HTML')
                        
                        return
                except Exception as e:
                    logger.error(f"خطأ في فحص الكلام البذيء: {e}")
        
        bot_username = context.bot.username
        should_respond = False

        # الحالة 1: الرد على رسالة البوت
        if message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id:
            should_respond = True
            logger.info(f"Group message: Reply to bot by user {user.id}")

        # الحالة 2: ذكر اسم البوت في الرسالة
        elif message.text:
            # التحقق من ذكر البوت بـ @ أو اسمه أو "بويكتا"
            bot_names = [f"@{bot_username}", bot_username, "بويكتا", "بويكتا كي", "@بويكتا"]
            if any(name in message.text for name in bot_names):
                should_respond = True
                logger.info(f"Group message: Bot mentioned by user {user.id}")

        # الحالة 3: الأوامر الموجهة للبوت
        elif message.entities:
            for entity in message.entities:
                if entity.type == "mention" and message.text[entity.offset:entity.offset + entity.length] == f"@{bot_username}":
                    should_respond = True
                    logger.info(f"Group message: Bot command by user {user.id}")
                    break

        # إذا لم تتحقق الشروط، تجاهل الرسالة
        if not should_respond:
            return

    # فحص Rate Limiting
    can_proceed, wait_time = check_rate_limit(user.id)
    if not can_proceed:
        await message.reply_text(
            f"⏳ يرجى الانتظار {wait_time:.1f} ثانية قبل إرسال رسالة أخرى.",
            disable_notification=True
        )
        return

    # التحقق من الاشتراك (فقط في المحادثات الخاصة)
    if not is_group:
        is_subscribed = await check_channel_membership(user.id, context, chat_id)
        if not is_subscribed:
            await send_subscription_required_message(update, context)
            return

    db.add_or_update_user(user.id, user.username or "", user.first_name or "")
    db.check_and_reset_quota(user.id)

    if db.is_banned(user.id):
        await message.reply_text("⛔ أنت محظور من استخدام البوت!")
        return

    if db.is_muted(user.id):
        return

    # معالجة البث الجماعي للأدمن
    if context.user_data.get('waiting_for') == 'broadcast_message' and is_super_admin(user.id):
        broadcast_text = message.text
        user_ids = db.get_all_user_ids()

        if not user_ids:
            await message.reply_text("⚠️ لا يوجد مستخدمين في قاعدة البيانات!")
            del context.user_data['waiting_for']
            return

        success = 0
        failed = 0
        blocked = 0

        status_msg = await message.reply_text(f"📢 جاري إرسال الرسالة إلى {len(user_ids)} مستخدم...")

        for uid in user_ids:
            try:
                await context.bot.send_message(chat_id=uid, text=broadcast_text)
                success += 1
                logger.info(f"Broadcast sent successfully to user {uid}")
            except Exception as e:
                failed += 1
                error_msg = str(e).lower()
                if "blocked" in error_msg or "bot was blocked" in error_msg:
                    blocked += 1
                    logger.warning(f"User {uid} has blocked the bot")
                else:
                    logger.warning(f"Failed to send broadcast to {uid}: {e}")

            # تأخير صغير لتجنب الحظر من Telegram
            if success % 20 == 0:
                await asyncio.sleep(1)

        await status_msg.edit_text(
            f"✅ **تم إكمال البث الجماعي!**\n\n"
            f"📊 **الإحصائيات:**\n"
            f"✅ نجح: {success}\n"
            f"❌ فشل: {failed}\n"
            f"🚫 محظور: {blocked}\n"
            f"📝 الإجمالي: {len(user_ids)}"
        )
        del context.user_data['waiting_for']
        return

    # معالجة أوامر الأدمن
    if context.user_data.get('admin_action') and is_super_admin(user.id):
        try:
            target_user_id = int(message.text)
            action = context.user_data['admin_action']

            if action == "admin_ban":
                db.ban_user(target_user_id)
                await message.reply_text(f"✅ تم حظر المستخدم {target_user_id}")
            elif action == "admin_unban":
                db.unban_user(target_user_id)
                await message.reply_text(f"✅ تم فك حظر المستخدم {target_user_id}")
            elif action == "admin_mute":
                db.mute_user(target_user_id)
                await message.reply_text(f"✅ تم كتم المستخدم {target_user_id}")
            elif action == "admin_unmute":
                db.unmute_user(target_user_id)
                await message.reply_text(f"✅ تم إلغاء كتم المستخدم {target_user_id}")

            del context.user_data['admin_action']
        except ValueError:
            await message.reply_text("❌ معرف المستخدم غير صحيح!")
        return

    # معالجة تحرير صورة واحدة
    if context.user_data.get('edit_pending') and context.user_data.get('waiting_for_edit_desc'):
        photo_url = context.user_data['edit_pending']
        edit_query = message.text
        
        # مسح العلامة لتجنب استخدامها مرة أخرى
        del context.user_data['waiting_for_edit_desc']

        # جرب Nano Banana أولاً (الأسرع والأفضل)
        await message.reply_text(f"🍌 جاري تحرير الصورة بـ Nano Banana...")
        image_url = ai.nano_banana(edit_query, [photo_url])

        if ai.is_valid_image_url(image_url):
            await message.reply_photo(
                photo=image_url,
                caption=f"✨ تم التحرير بـ Nano Banana: {edit_query}"
            )

            keyboard = [
                [InlineKeyboardButton("✏️ تحرير مرة أخرى", callback_data=f"start_edit:{image_url}")],
                [get_cancel_button()]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await message.reply_text("💡 يمكنك تحرير الصورة مرة أخرى:", reply_markup=reply_markup)
        else:
            # إذا فشل، جرب GPT-Imager
            await message.reply_text("🔄 جاري المحاولة بنموذج احتياطي...")
            image_url = ai.gpt_imager(edit_query, photo_url)

            if ai.is_valid_image_url(image_url):
                await message.reply_photo(
                    photo=image_url,
                    caption=f"✨ تم التحرير بـ GPT-Imager: {edit_query}"
                )

                keyboard = [
                    [InlineKeyboardButton("✏️ تحرير مرة أخرى", callback_data=f"start_edit:{image_url}")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await message.reply_text("💡 يمكنك تحرير الصورة مرة أخرى:", reply_markup=reply_markup)
            else:
                keyboard = [[get_cancel_button()]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await message.reply_text("عذراً، حدث خطأ في التحرير. حاول مرة أخرى", reply_markup=reply_markup)

        del context.user_data['edit_pending']
        return

    # معالجة تحرير عدة صور
    if context.user_data.get('edit_pending_multiple') and context.user_data.get('waiting_for_edit_desc_multi'):
        photo_urls = context.user_data['edit_pending_multiple']
        edit_query = message.text
        photo_count = len(photo_urls)
        
        # مسح العلامة لتجنب استخدامها مرة أخرى
        del context.user_data['waiting_for_edit_desc_multi']

        await message.reply_text(f"🍌 جاري تحرير {photo_count} صورة...")

        # تحرير جميع الصور (Nano Banana أولاً، ثم GPT-Imager)
        for i, photo_url in enumerate(photo_urls[:10], 1):
            await message.reply_text(f"⏳ جاري تحرير الصورة {i}/{min(photo_count, 10)}...")

            # جرب Nano Banana أولاً
            image_url = ai.nano_banana(edit_query, [photo_url])

            if ai.is_valid_image_url(image_url):
                await message.reply_photo(
                    photo=image_url,
                    caption=f"✨ الصورة {i} (Nano Banana): {edit_query}"
                )
            else:
                # إذا فشل، جرب GPT-Imager
                image_url = ai.gpt_imager(edit_query, photo_url)

                if ai.is_valid_image_url(image_url):
                    await message.reply_photo(
                        photo=image_url,
                        caption=f"✨ الصورة {i} (GPT-Imager): {edit_query}"
                    )
                else:
                    await message.reply_text(f"⚠️ فشل تحرير الصورة {i}")

        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text("✅ تم الانتهاء من تحرير جميع الصور!", reply_markup=reply_markup)

        del context.user_data['edit_pending_multiple']
        return

    text = message.text

    if text in ["📚 مساعدة في الدراسة", "❓ المساعدة"]:
        await help_command(update, context)
        return

    if text == "⚙️ لوحة التحكم":
        await admin_panel(update, context)
        return

    if text == "🔍 البحث":
        clear_user_operations(context)
        await message.reply_text(
            "🔍 **للبحث استخدم الأمر:**\n\n"
            "`/بحث` متبوعاً بموضوع البحث\n\n"
            "**مثال:**\n"
            "`/بحث تمرين 5 صفحة 20 رياضيات`"
        )
        return

    if text == "💻 مساعدة برمجة":
        clear_user_operations(context)
        await message.reply_text(
            "💻 **للمساعدة البرمجية استخدم الأمر:**\n\n"
            "`/كود` متبوعاً بسؤالك\n\n"
            "**مثال:**\n"
            "`/كود كيف أكتب دالة في Python`"
        )
        return

    if text == "🎨 إنشاء صورة":
        clear_user_operations(context)
        await message.reply_text(
            "🎨 **لإنشاء صورة استخدم الأمر:**\n\n"
            "`/صورة` متبوعاً بوصف الصورة\n\n"
            "**مثال:**\n"
            "`/صورة رسم توضيحي للدورة الدموية`"
        )
        return

    if text == "✏️ تحرير صورة":
        clear_user_operations(context)
        context.user_data['waiting_for'] = 'edit_photo'
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(
            "✏️ **لتحرير صورة:**\n\n"
            "الآن أرسل الصورة التي تريد تحريرها",
            reply_markup=reply_markup
        )
        return

    if text == "📸 تحليل صورة":
        clear_user_operations(context)
        context.user_data['waiting_for'] = 'analyze_photo'
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(
            "📸 **لتحليل صورة:**\n\n"
            "الآن أرسل الصورة للتحليل واستخراج النص",
            reply_markup=reply_markup
        )
        return

    if text == "🎬 إنشاء فيديو":
        clear_user_operations(context)
        await message.reply_text(
            "🎬 **لإنشاء فيديو استخدم الأمر:**\n\n"
            "`/فيديو` متبوعاً بوصف الفيديو\n\n"
            "**مثال:**\n"
            "`/فيديو شرح الدورة الدموية بطريقة مبسطة`\n\n"
            "💡 يمكنك أيضاً إرسال صورة ثم كتابة `/فيديو [الوصف]` لتحويلها لفيديو!"
        )
        return

    if text == "✨ تحسين جودة صورة":
        clear_user_operations(context)
        context.user_data['waiting_for'] = 'enhance_photo'
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(
            "✨ **لتحسين جودة الصورة حتى 8K:**\n\n"
            "الآن أرسل الصورة التي تريد تحسين جودتها\n"
            "سيتم تحسين التفاصيل، الألوان، والوضوح باستخدام GPT-5",
            reply_markup=reply_markup
        )
        return

    if text.startswith("/تحرير"):
        context.user_data['waiting_for'] = 'edit_photo'
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(
            "✏️ **جاهز لتحرير الصورة**\n\n"
            "أرسل الصورة الآن",
            reply_markup=reply_markup
        )
        return

    if text.startswith("/تحليل"):
        context.user_data['waiting_for'] = 'analyze_photo'
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(
            "📸 **جاهز لتحليل الصورة**\n\n"
            "أرسل الصورة الآن",
            reply_markup=reply_markup
        )
        return

    if message.photo:
        await handle_photo(update, context)
        return

    if message.document:
        await handle_document(update, context)
        return

    if text.startswith("/فيديو"):
        clear_user_operations(context)
        query = text.replace("/فيديو", "").strip()
        if not query:
            await message.reply_text("❌ **يرجى كتابة وصف الفيديو بعد الأمر**\n\nمثال: `/فيديو شرح الدورة الدموية`")
            return

        # التحقق من الحصة اليومية للفيديو
        quota = db.get_user_quota(user.id)
        limits = SUBSCRIPTION_LIMITS[quota['tier']]

        if quota['daily_video_used'] >= limits['daily_videos']:
            await message.reply_text(
                f"⚠️ **لقد استنفذت حصتك اليومية من الفيديو!**\n\n"
                f"📊 خطتك ({quota['tier']}): {limits['daily_videos']} فيديو/يوم\n"
                f"🎬 مستخدم: {quota['daily_video_used']}/{limits['daily_videos']}\n\n"
                f"💡 سيتم إعادة تعيين الحصة غداً"
            )
            return

        loading_msg = LoadingAnimation.get_random_animation("🎬 جاري إنشاء الفيديو...")
        status_message = await message.reply_text(loading_msg)

        # استخدام Veo3 لإنشاء الفيديو
        video_url = ai.veo3_text_to_video(query)

        try:
            await status_message.delete()
        except:
            pass

        if ai.is_valid_image_url(video_url):
            db.increment_quota(user.id, 'video')
            await message.reply_video(
                video=video_url,
                caption=f"🎬 **تم إنشاء الفيديو!**\n\n📝 الوصف: {query}\n\n🔊 مع صوت مجاني!"
            )
        else:
            await message.reply_text(
                "⚠️ **عذراً، خدمة إنشاء الفيديو غير متاحة حالياً**\n\n"
                "🔧 السبب: نفاد الرصيد في API\n"
                "💡 الحل: يرجى المحاولة لاحقاً أو استخدام خدمات أخرى\n\n"
                "يمكنك استخدام:\n"
                "• 🎨 إنشاء صورة\n"
                "• 📚 المساعدة في الدراسة\n"
                "• 💻 مساعدة البرمجة"
            )
        return

    if text.startswith("/بحث"):
        clear_user_operations(context)
        query = text.replace("/بحث", "").strip()
        if not query:
            await message.reply_text("❌ **يرجى كتابة موضوع البحث بعد الأمر**\n\nمثال: `/بحث تمرين 5`")
            return

        loading_msg = LoadingAnimation.get_random_animation("🔍 جاري البحث...")
        status_message = await message.reply_text(loading_msg)
        result = ai.search(query)

        try:
            await status_message.delete()
        except:
            pass

        if len(result) > 4096:
            parts = [result[i:i+4096] for i in range(0, len(result), 4096)]
            for part in parts:
                await message.reply_text(part)
        else:
            await message.reply_text(result)

        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text("اكتب /start للعودة", reply_markup=reply_markup)
        return

    if text.startswith("/كود"):
        clear_user_operations(context)
        query = text.replace("/كود", "").strip()
        if not query:
            await message.reply_text("❌ **يرجى كتابة سؤالك بعد الأمر**\n\nمثال: `/كود كيف أكتب حلقة for`")
            return

        loading_msg = LoadingAnimation.get_random_animation("💻 جاري معالجة طلبك البرمجي...")
        status_message = await message.reply_text(loading_msg)
        result = ai.darkcode(query)

        try:
            await status_message.delete()
        except:
            pass

        if len(result) > 4096:
            parts = [result[i:i+4096] for i in range(0, len(result), 4096)]
            for i, part in enumerate(parts):
                if i == 0:
                    await message.reply_text(f"💻 **الحل البرمجي:**\n\n{part}")
                else:
                    await message.reply_text(part)
        else:
            await message.reply_text(f"💻 **الحل البرمجي:**\n\n{result}")

        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text("اكتب /start للعودة", reply_markup=reply_markup)
        return

    # أمر حل المعادلات
    if text.startswith("/حل") or text.startswith("/معادلة"):
        clear_user_operations(context)
        equation = text.replace("/حل", "").replace("/معادلة", "").strip()
        if not equation:
            await message.reply_text(
                "🔢 **لحل معادلة رياضية:**\n\n"
                "استخدم: `/حل [المعادلة]`\n\n"
                "**أمثلة:**\n"
                "`/حل x**2 - 4`\n"
                "`/حل 2*x + 5 = 15`\n"
                "`/حل x**2 + 3*x - 10`"
            )
            return

        result = MathSolver.solve_equation(equation)
        await message.reply_text(result)
        return

    # معالجة طلب المستخدم بعد استخراج النص (بدون أسئلة محددة)
    if context.user_data.get('waiting_for_math_instruction'):
        context.user_data['waiting_for_math_instruction'] = False
        
        exercise_data = context.user_data.get('math_exercise')
        if not exercise_data or 'original_text' not in exercise_data:
            await message.reply_text("❌ انتهت صلاحية التمرين. أرسل صورة جديدة")
            return

        user_instruction = text.strip()
        original_text = exercise_data['original_text']

        loading_msg = await message.reply_text("🧮 جاري تنفيذ طلبك...")

        try:
            # حل التمرين حسب طلب المستخدم
            custom_solve_prompt = f"""أنت معلم خبير ومتخصص. قم بتنفيذ الطلب التالي بشكل تفصيلي:

**النص/التمرين:**
{original_text}

**طلب المستخدم:**
{user_instruction}

**التعليمات:**
1. افهم ما يريده المستخدم بالضبط من النص
2. نفذ الطلب خطوة بخطوة بالتفصيل الكامل
3. اشرح بلغة سهلة ومفهومة للطالب
4. اعرض النتيجة النهائية بوضوح
5. إذا كان رياضي، اعرض الحسابات والخطوات بدقة

**قواعد التنسيق الرياضي الإلزامية (للمسائل الرياضية):**
✓ وضوح التنسيق: اكتب جميع المعادلات والنتائج بتنسيق واضح ومفهوم
✓ تجنب أوامر LaTeX الخام: لا تستخدم \\frac أو \\sqrt أو \\cdot
✓ استخدم الرموز البديلة: (a/b) بدلاً من \\frac{{a}}{{b}}، و√x بدلاً من \\sqrt{{x}}
✓ الترقيم: رقّم الخطوات بوضوح (1. 2. 3.)

**ملاحظة:** ركز فقط على تنفيذ طلب المستخدم."""

            solution = ai.grok4(custom_solve_prompt)

            # تحويل الحل إلى صورة جميلة
            await message.reply_text("🎨 جاري تحويل النتيجة إلى صورة...")
            
            solution_image_path = MathExerciseSolver.create_solution_image(solution, f"✅ النتيجة: {user_instruction[:30]}...")
            
            if solution_image_path and os.path.exists(solution_image_path):
                # إرسال الصورة
                await message.reply_photo(
                    photo=open(solution_image_path, 'rb'),
                    caption=f"✅ **تم تنفيذ طلبك!**\n\n📝 الطلب: {user_instruction}\n📸 النتيجة معروضة في الصورة أعلاه"
                )
                
                # حذف الصورة المؤقتة
                try:
                    os.remove(solution_image_path)
                except:
                    pass
            else:
                # fallback: إرسال الحل كنص إذا فشل إنشاء الصورة
                if len(solution) > 4096:
                    parts = [solution[i:i+4096] for i in range(0, len(solution), 4096)]
                    for i, part in enumerate(parts):
                        if i == 0:
                            await message.reply_text(f"✅ **النتيجة ({i+1}/{len(parts)}):**\n\n{part}")
                        else:
                            await message.reply_text(f"**({i+1}/{len(parts)}):**\n\n{part}")
                else:
                    await message.reply_text(f"✅ **النتيجة:**\n\n{solution}")

            keyboard = [
                [InlineKeyboardButton("🔄 حل تمرين آخر", callback_data="solve_another_exercise")],
                [get_cancel_button()]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await loading_msg.edit_text("✅ **تم الانتهاء!**", reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error in custom solve: {e}")
            await message.reply_text(f"❌ حدث خطأ: {str(e)}\nيرجى المحاولة مرة أخرى")
        
        return

    # أمر البحث في الكتب
    if text.startswith("/كتاب") or text.startswith("/كتب"):
        clear_user_operations(context)
        query = text.replace("/كتاب", "").replace("/كتب", "").strip()
        if not query:
            await message.reply_text(
                "📚 **للبحث في الكتب:**\n\n"
                "استخدم: `/كتاب [موضوع البحث]`\n\n"
                "**أمثلة:**\n"
                "`/كتاب الرياضيات`\n"
                "`/كتاب الفيزياء الحديثة`\n"
                "`/كتاب البرمجة بلغة Python`"
            )
            return

        await message.reply_text("🔍 جاري البحث في الكتب...")

        # البحث في Google Books
        google_result = BookSearch.search_google_books(query)
        await message.reply_text(google_result)

        # البحث في Open Library
        await message.reply_text("🔍 البحث في المكتبة المفتوحة...")
        open_lib_result = BookSearch.search_open_library(query)
        await message.reply_text(open_lib_result)

        return

    if text.startswith("/صورة"):
        clear_user_operations(context)
        query = text.replace("/صورة", "").strip()
        if not query:
            await message.reply_text("❌ **يرجى كتابة وصف الصورة بعد الأمر**\n\nمثال: `/صورة رسم توضيحي للخلية`")
            return

        loading_msg = LoadingAnimation.get_random_animation("🎨 جاري إنشاء الصورة...")
        status_message = await message.reply_text(loading_msg)

        try:
            # تجربة img_cv أولاً (الأسرع)
            image_url = ai.img_cv(query)

            if ai.is_valid_image_url(image_url):
                try:
                    await status_message.delete()
                except:
                    pass

                await message.reply_photo(photo=image_url, caption=f"🎨 {query}")

                keyboard = [
                    [InlineKeyboardButton("✏️ تحرير هذه الصورة", callback_data=f"start_edit:{image_url}")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await message.reply_text("💡 يمكنك تحرير الصورة:", reply_markup=reply_markup)
                return

            # تجربة nano_banana
            await status_message.edit_text("🔄 جاري المحاولة بنموذج آخر...")
            image_url = ai.nano_banana(query)

            if ai.is_valid_image_url(image_url):
                try:
                    await status_message.delete()
                except:
                    pass

                await message.reply_photo(photo=image_url, caption=f"🎨 {query}")

                keyboard = [
                    [InlineKeyboardButton("✏️ تحرير هذه الصورة", callback_data=f"start_edit:{image_url}")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await message.reply_text("💡 يمكنك تحرير الصورة:", reply_markup=reply_markup)
                return

            # محاولة أخيرة
            await status_message.edit_text("🔄 محاولة أخيرة...")
            image_url = ai.nano_banana(query)

            if ai.is_valid_image_url(image_url):
                try:
                    await status_message.delete()
                except:
                    pass

                await message.reply_photo(photo=image_url, caption=f"🎨 {query}")

                keyboard = [
                    [InlineKeyboardButton("✏️ تحرير هذه الصورة", callback_data=f"start_edit:{image_url}")],
                    [InlineKeyboardButton("🎁 تحسين الجودة 8K", callback_data=f"enhance:{image_url}")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await message.reply_text("💡 يمكنك تحرير الصورة أو تحسين جودتها:", reply_markup=reply_markup)
                return

            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await status_message.edit_text(
                "⚠️ عذراً، خدمة إنشاء الصور غير متاحة حالياً.\n"
                "يرجى المحاولة مرة أخرى بعد قليل.",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error in /صورة command: {e}")
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await status_message.edit_text(
                    "⚠️ حدث خطأ غير متوقع.\nيرجى المحاولة مرة أخرى.",
                    reply_markup=reply_markup
                )
            except:
                await message.reply_text(
                    "⚠️ حدث خطأ غير متوقع.\nيرجى المحاولة مرة أخرى.",
                    reply_markup=reply_markup
                )
        return

    # المحادثة العامة مع سياق
    loading_msg = LoadingAnimation.get_random_animation("💭 جاري التفكير...")
    status_message = await message.reply_text(loading_msg)

    # تنظيف النص من اسم البوت في المجموعات
    clean_text = text
    if is_group and text:
        bot_username = context.bot.username
        # إزالة @username من النص
        clean_text = text.replace(f"@{bot_username}", "").strip()
        # إزالة اسم البوت بدون @
        clean_text = clean_text.replace(bot_username, "").strip()
        # إزالة اسم "بويكتا" وتنويعاته
        for name in ["بويكتا كي", "بويكتا", "@بويكتا"]:
            clean_text = clean_text.replace(name, "").strip()

    # الحصول على سياق المحادثة مع دعم المجموعات
    conversation_history = db.get_conversation_history(user.id, chat_id)
    response = ai.grok4(clean_text, conversation_history)

    try:
        await status_message.delete()
    except:
        pass

    # حفظ المحادثة مع chat_id لدعم المجموعات (استخدام النص المنظف)
    final_text = clean_text if is_group else text
    db.add_conversation(user.id, final_text, response, chat_id)

    if len(response) > 4096:
        for i in range(0, len(response), 4096):
            await message.reply_text(response[i:i+4096])
    else:
        await message.reply_text(response)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الملفات المرسلة (PDF, DOCX, TXT) - محسّن مع سجل أخطاء"""
    message = update.message
    document = message.document
    user = update.effective_user

    logger.info(f"📄 Received document: {document.file_name}, size: {document.file_size} bytes")

    # التحقق من نوع الملف
    file_name = document.file_name.lower()
    file_size = document.file_size

    # التحقق من حجم الملف (حد أقصى 20 ميغابايت)
    if file_size > 20 * 1024 * 1024:
        logger.warning(f"File too large: {file_size} bytes")
        await message.reply_text("⚠️ حجم الملف كبير جداً! الحد الأقصى هو 20 ميغابايت")
        return

    # التحقق من نوع الملف المدعوم
    supported_extensions = ['.pdf', '.docx', '.doc', '.txt']
    if not any(file_name.endswith(ext) for ext in supported_extensions):
        logger.warning(f"Unsupported file type: {file_name}")
        await message.reply_text(
            "⚠️ **نوع الملف غير مدعوم!**\n\n"
            "الأنواع المدعومة:\n"
            "📄 PDF (.pdf)\n"
            "📝 Word (.docx, .doc)\n"
            "📃 Text (.txt)"
        )
        return

    # تنزيل الملف
    loading_msg = await message.reply_text("📥 جاري تنزيل الملف...")

    try:
        logger.info(f"📥 Downloading file: {document.file_id}")
        file = await context.bot.get_file(document.file_id)
        file_content = await file.download_as_bytearray()
        logger.info(f"✅ File downloaded successfully, size: {len(file_content)} bytes")

        await loading_msg.edit_text("🔍 جاري استخراج النص من الملف...")

        # استخراج النص حسب نوع الملف
        extracted_text = ""

        try:
            if file_name.endswith('.pdf'):
                logger.info("📄 Extracting text from PDF...")
                extracted_text = await FileProcessor.extract_text_from_pdf(bytes(file_content))
                logger.info(f"✅ PDF text extracted: {len(extracted_text)} chars")
            elif file_name.endswith('.docx') or file_name.endswith('.doc'):
                logger.info("📝 Extracting text from DOCX...")
                extracted_text = await FileProcessor.extract_text_from_docx(bytes(file_content))
                logger.info(f"✅ DOCX text extracted: {len(extracted_text)} chars")
            elif file_name.endswith('.txt'):
                logger.info("📃 Extracting text from TXT...")
                extracted_text = await FileProcessor.extract_text_from_txt(bytes(file_content))
                logger.info(f"✅ TXT text extracted: {len(extracted_text)} chars")
        except Exception as extract_error:
            logger.error(f"❌ Extraction error for {file_name}: {type(extract_error).__name__} - {str(extract_error)}")
            raise

        try:
            await loading_msg.delete()
        except:
            pass

        # التحقق من نجاح الاستخراج
        if not extracted_text or len(extracted_text.strip()) < 5:
            logger.warning(f"⚠️ No text extracted from {file_name}")
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await message.reply_text(
                "❌ عذراً، لم أتمكن من استخراج نص من هذا الملف.\n"
                "تأكد من أن الملف يحتوي على نص قابل للقراءة.",
                reply_markup=reply_markup
            )
            return

        # عرض النص المستخرج
        text_preview = extracted_text[:500] + "..." if len(extracted_text) > 500 else extracted_text

        await message.reply_text(
            f"📄 **تم استخراج النص من الملف:**\n\n"
            f"📝 اسم الملف: {document.file_name}\n"
            f"📊 عدد الأحرف: {len(extracted_text)}\n\n"
            f"**معاينة:**\n{text_preview}"
        )

        # حفظ النص للمعالجة
        context.user_data['last_extracted_text'] = extracted_text
        context.user_data['document_name'] = document.file_name
        logger.info(f"✅ Text saved for user {user.id}, document: {document.file_name}")

        # عرض الخيارات
        keyboard = [
            [InlineKeyboardButton("📖 عرض النص الكامل", callback_data="show_full_text")],
            [InlineKeyboardButton("💡 شرح وتحليل المحتوى", callback_data="analyze_document")],
            [InlineKeyboardButton("🌐 ترجمة", callback_data="ocr_translate_menu")],
            [InlineKeyboardButton("🔍 البحث عن الموضوع", callback_data="search_last_ocr")],
            [get_cancel_button()]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await message.reply_text(
            "💡 **ماذا تريد أن تفعل بهذا النص؟**",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"💥 Error processing document {file_name}: {type(e).__name__} - {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        try:
            await loading_msg.delete()
        except:
            pass
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(
            f"⚠️ حدث خطأ أثناء معالجة الملف.\n"
            f"الخطأ: {str(e)}\n"
            "يرجى المحاولة مرة أخرى أو استخدام ملف آخر.",
            reply_markup=reply_markup
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الصور المرسلة"""
    message = update.message
    photo = message.photo[-1]

    file = await context.bot.get_file(photo.file_id)
    photo_url = file.file_path
    if not photo_url.startswith('http'):
        photo_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file.file_path}"

    # التحقق من وجود أمر مسبق
    waiting_for = context.user_data.get('waiting_for')

    # إذا لم يكن هناك أمر سابق، إلغاء أي عمليات قديمة
    if not waiting_for:
        clear_user_operations(context)

    if waiting_for == 'edit_photo':
        # تجميع صور للتحرير
        if 'collected_photos' not in context.user_data:
            context.user_data['collected_photos'] = []

        context.user_data['collected_photos'].append(photo_url)
        photo_count = len(context.user_data['collected_photos'])

        keyboard = [
            [InlineKeyboardButton(f"✅ انتهيت ({photo_count} صورة)", callback_data="photos_done_edit")],
            [get_cancel_button()]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await message.reply_text(
            f"📸 تم استلام الصورة {photo_count}\n\n"
            "يمكنك إرسال المزيد من الصور أو الضغط على 'انتهيت' للمتابعة",
            reply_markup=reply_markup
        )
        return

    elif waiting_for == 'analyze_photo':
        # تجميع صور للتحليل
        if 'collected_photos' not in context.user_data:
            context.user_data['collected_photos'] = []

        context.user_data['collected_photos'].append(photo_url)
        photo_count = len(context.user_data['collected_photos'])

        keyboard = [
            [InlineKeyboardButton(f"✅ انتهيت ({photo_count} صورة)", callback_data="photos_done_analyze")],
            [get_cancel_button()]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await message.reply_text(
            f"📸 تم استلام الصورة {photo_count}\n\n"
            "يمكنك إرسال المزيد من الصور (حتى 10 صور) أو الضغط على 'انتهيت' للمتابعة",
            reply_markup=reply_markup
        )
        return

    elif waiting_for == 'enhance_photo':
        # تحسين جودة الصورة مباشرة
        del context.user_data['waiting_for']

        loading_msg = LoadingAnimation.get_random_animation("✨ جاري تحسين جودة الصورة حتى 8K...")
        status_message = await message.reply_text(loading_msg)

        try:
            enhanced_url = ai.quality_enhancer(photo_url)

            if ai.is_valid_image_url(enhanced_url):
                try:
                    await status_message.delete()
                except:
                    pass

                await message.reply_photo(
                    photo=enhanced_url,
                    caption="✨ **تم تحسين الجودة بنجاح!**\n\n"
                            "🎯 تحسينات:\n"
                            "• دقة محسّنة حتى 8K\n"
                            "• ألوان أكثر وضوحاً\n"
                            "• تفاصيل أدق وأوضح"
                )

                keyboard = [
                    [InlineKeyboardButton("✨ تحسين صورة أخرى", callback_data="start_enhance_another")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await message.reply_text("💡 يمكنك تحسين المزيد من الصور:", reply_markup=reply_markup)
            else:
                keyboard = [[get_cancel_button()]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await status_message.edit_text(
                    "⚠️ عذراً، خدمة تحسين الجودة غير متاحة حالياً.\n"
                    "يرجى المحاولة مرة أخرى بعد قليل.",
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Error enhancing photo: {e}")
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await status_message.edit_text(
                    "⚠️ حدث خطأ أثناء تحسين الصورة.\nيرجى المحاولة مرة أخرى.",
                    reply_markup=reply_markup
                )
            except:
                await message.reply_text(
                    "⚠️ حدث خطأ أثناء تحسين الصورة.\nيرجى المحاولة مرة أخرى.",
                    reply_markup=reply_markup
                )
        return

    # إذا لم يكن هناك أمر مسبق، عرض الخيارات
    context.user_data['pending_photo'] = photo_url

    keyboard = [
        [InlineKeyboardButton("🧮 حل التمرين الرياضي", callback_data="photo_math_solve")],
        [InlineKeyboardButton("📝 استخراج النص وتحليله", callback_data="photo_ocr")],
        [InlineKeyboardButton("✏️ تحرير الصورة", callback_data="photo_edit")],
        [InlineKeyboardButton("✨ تحسين الجودة 8K", callback_data="photo_enhance")],
        [get_cancel_button()]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text(
        "📸 **ماذا تريد أن تفعل بهذه الصورة؟**",
        reply_markup=reply_markup
    )


async def handle_ocr_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة خيارات OCR المختلفة"""
    query = update.callback_query
    await query.answer()

    # معالجة قائمة الترجمة
    if query.data == "ocr_translate_menu":
        keyboard = [
            [InlineKeyboardButton("🌐 عربي", callback_data="ocr_trans_ar"), 
             InlineKeyboardButton("🇬🇧 إنجليزي", callback_data="ocr_trans_en")],
            [InlineKeyboardButton("🇫🇷 فرنسي", callback_data="ocr_trans_fr"),
             InlineKeyboardButton("🇪🇸 إسباني", callback_data="ocr_trans_es")],
            [InlineKeyboardButton("🇩🇪 ألماني", callback_data="ocr_trans_de"),
             InlineKeyboardButton("🇮🇹 إيطالي", callback_data="ocr_trans_it")],
            [InlineKeyboardButton("🇹🇷 تركي", callback_data="ocr_trans_tr"),
             InlineKeyboardButton("🇷🇺 روسي", callback_data="ocr_trans_ru")],
            [InlineKeyboardButton("🇨🇳 صيني", callback_data="ocr_trans_zh"),
             InlineKeyboardButton("🇯🇵 ياباني", callback_data="ocr_trans_ja")],
            [InlineKeyboardButton("🇰🇷 كوري", callback_data="ocr_trans_ko"),
             InlineKeyboardButton("🇮🇳 هندي", callback_data="ocr_trans_hi")],
            [InlineKeyboardButton("◀️ رجوع", callback_data="ocr_back_menu")],
            [get_cancel_button()]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🌐 **اختر لغة الترجمة:**\n\n"
            "سيتم استخراج النص من الصور ثم ترجمته إلى اللغة المختارة",
            reply_markup=reply_markup
        )
        return

    # معالجة الرجوع للقائمة الرئيسية
    if query.data == "ocr_back_menu":
        photo_urls = context.user_data.get('ocr_photos', [])
        if not photo_urls:
            await query.edit_message_text("❌ انتهت صلاحية الصور. أرسل صورة جديدة")
            return

        photo_count = len(photo_urls)
        keyboard = [
            [InlineKeyboardButton("📝 استخراج النص فقط", callback_data="ocr_extract_only")],
            [InlineKeyboardButton("📝📖 استخراج + شرح", callback_data="ocr_extract_explain")],
            [InlineKeyboardButton("🌐📸 استخراج + ترجمة", callback_data="ocr_translate_menu")],
            [get_cancel_button()]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"📸 **تم استلام {photo_count} صورة**\n\n"
            "اختر ما تريد القيام به:",
            reply_markup=reply_markup
        )
        return

    photo_urls = context.user_data.get('ocr_photos', [])
    if not photo_urls:
        await query.edit_message_text("❌ انتهت صلاحية الصور. أرسل صورة جديدة")
        return

    option = query.data
    photo_count = len(photo_urls)

    await query.edit_message_text(f"⏳ جاري استخراج النص من {photo_count} صورة...")

    ocr_result = ai.ocr("", photo_urls)

    if not ocr_result or len(ocr_result.strip()) < 5:
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            "❌ عذراً، لم أتمكن من استخراج نص من الصور.\nتأكد من وضوح الصور وحاول مرة أخرى.",
            reply_markup=reply_markup
        )
        if 'ocr_photos' in context.user_data:
            del context.user_data['ocr_photos']
        return

    clean_ocr = ocr_result.strip()

    if option == "ocr_extract_only":
        if len(clean_ocr) > 4000:
            parts = [clean_ocr[i:i+4000] for i in range(0, len(clean_ocr), 4000)]
            for i, part in enumerate(parts):
                if i == 0:
                    await query.message.reply_text(f"📝 **النص المستخرج:**\n\n{part}")
                else:
                    await query.message.reply_text(part)
        else:
            await query.message.reply_text(f"📝 **النص المستخرج:**\n\n{clean_ocr}")

    elif option == "ocr_extract_explain":
        if len(clean_ocr) > 4000:
            parts = [clean_ocr[i:i+4000] for i in range(0, len(clean_ocr), 4000)]
            for i, part in enumerate(parts):
                if i == 0:
                    await query.message.reply_text(f"📝 **النص المستخرج:**\n\n{part}")
                else:
                    await query.message.reply_text(part)
        else:
            await query.message.reply_text(f"📝 **النص المستخرج:**\n\n{clean_ocr}")

        await query.message.reply_text("🤔 جاري تحليل المحتوى...")

        analysis_prompt = f"""النص التالي مستخرج من {photo_count} صورة:

{clean_ocr}

قم بما يلي:
1. إذا كان تمريناً قدم الحل التفصيلي
2. إذا كان النص طويلا قدم شرحاً مبسطاً
3. اشرح المصطلحات المهمة

**قواعد التنسيق الرياضي (إذا كان رياضياً):**
✓ وضوح التنسيق: اكتب جميع المعادلات والنتائج بتنسيق واضح ومفهوم
✓ تجنب أوامر LaTeX الخام: لا تستخدم \\frac أو \\sqrt أو \\cdot
✓ استخدم الرموز البديلة: (a/b) بدلاً من \\frac{{a}}{{b}}، و√x بدلاً من \\sqrt{{x}}
✓ الترقيم: رقّم الخطوات بوضوح (1. 2. 3.)

لا تكرر االنص ركز على التحليل والشرح."""

        solution = ai.grok4(analysis_prompt)

        if len(solution) > 4096:
            parts = [solution[i:i+4096] for i in range(0, len(solution), 4096)]
            for i, part in enumerate(parts):
                if i == 0:
                    await query.message.reply_text(f"✅ **التحليل والشرح:**\n\n{part}")
                else:
                    await query.message.reply_text(part)
        else:
            await query.message.reply_text(f"✅ **التحليل والشرح:**\n\n{solution}")

    elif option.startswith("ocr_trans_"):
        lang_code = option.replace("ocr_trans_", "")

        lang_map = {
            "ar": ("العربية", "🌐", "ar"),
            "en": ("English", "🇬🇧", "en"),
            "fr": ("Français", "🇫🇷", "fr"),
            "es": ("Español", "🇪🇸", "es"),
            "de": ("Deutsch", "🇩🇪", "de"),
            "it": ("Italiano", "🇮🇹", "it"),
            "tr": ("Türkçe", "🇹🇷", "tr"),
            "ru": ("Русский", "🇷🇺", "ru"),
            "zh": ("中文", "🇨🇳", "zh"),
            "ja": ("日本語", "🇯🇵", "ja"),
            "ko": ("한국어", "🇰🇷", "ko"),
            "hi": ("हिन्दी", "🇮🇳", "hi")
        }

        if lang_code not in lang_map:
            await query.message.reply_text("❌ لغة غير مدعومة")
            return

        lang_name, flag, api_lang = lang_map[lang_code]

        # عرض النص المستخرج أولاً
        if len(clean_ocr) > 4000:
            parts = [clean_ocr[i:i+4000] for i in range(0, len(clean_ocr), 4000)]
            for i, part in enumerate(parts):
                if i == 0:
                    await query.message.reply_text(f"📝 **النص المستخرج:**\n\n{part}")
                else:
                    await query.message.reply_text(part)
        else:
            await query.message.reply_text(f"📝 **النص المستخرج:**\n\n{clean_ocr}")

        # رسالة جاري الترجمة
        await query.message.reply_text(f"{flag} جاري الترجمة إلى {lang_name}...")

        # استخدام API ترجمة
        try:
            # محاولة استخدام MyMemory API
            import urllib.parse
            encoded_text = urllib.parse.quote(clean_ocr[:500])  # حد أقصى 500 حرف

            response = requests.get(
                'https://api.mymemory.translated.net/get',
                params={
                    'q': clean_ocr[:500],
                    'langpair': f'auto|{api_lang}'
                },
                timeout=10
            )

            if response.ok:
                result = response.json()
                if result.get('responseStatus') == 200:
                    translation = result.get('responseData', {}).get('translatedText', '')
                    if translation:
                        if len(translation) > 4096:
                            parts = [translation[i:i+4096] for i in range(0, len(translation), 4096)]
                            for i, part in enumerate(parts):
                                if i == 0:
                                    await query.message.reply_text(f"{flag} **الترجمة ({lang_name}):**\n\n{part}")
                                else:
                                    await query.message.reply_text(part)
                        else:
                            await query.message.reply_text(f"{flag} **الترجمة ({lang_name}):**\n\n{translation}")
                    else:
                        raise Exception("Empty translation")
                else:
                    raise Exception("API error")
            else:
                raise Exception("API request failed")

        except Exception as e:
            logger.warning(f"Translation API failed, using AI: {e}")
            # استخدام الذكاء الاصطناعي كبديل
            translate_prompts = {
                "ar": "ترجم النص التالي إلى العربية بشكل واضح ومفهوم",
                "en": "Translate the following text to English clearly and accurately",
                "fr": "Traduisez le texte suivant en français de manière claire et précise",
                "es": "Traduce el siguiente texto al español de forma clara y precisa",
                "de": "Übersetzen Sie den folgenden Text klar und präzise ins Deutsche",
                "it": "Traduci il seguente testo in italiano in modo chiaro e preciso",
                "tr": "Aşağıdaki metni Türkçe'ye açık ve net bir şekilde çevirin",
                "ru": "Переведите следующий текст на русский язык четко и точно",
                "zh": "将以下文本清晰准确地翻译成中文",
                "ja": "次のテキストを日本語に明確かつ正確に翻訳してください",
                "ko": "다음 텍스트를 명확하고 정확하게 한국어로 번역하세요",
                "hi": "निम्नलिखित पाठ को स्पष्ट और सटीक रूप से हिंदी में अनुवाद करें"
            }

            prompt_prefix = translate_prompts.get(lang_code, "Translate the following text clearly")
            translate_prompt = f"{prompt_prefix}:\n\n{clean_ocr}"
            translation = ai.grok4(translate_prompt)

            if len(translation) > 4096:
                parts = [translation[i:i+4096] for i in range(0, len(translation), 4096)]
                for i, part in enumerate(parts):
                    if i == 0:
                        await query.message.reply_text(f"{flag} **الترجمة ({lang_name}):**\n\n{part}")
                    else:
                        await query.message.reply_text(part)
            else:
                await query.message.reply_text(f"{flag} **الترجمة ({lang_name}):**\n\n{translation}")

    # حفظ النص المستخرج للبحث لاحقاً
    context.user_data['last_extracted_text'] = clean_ocr

    keyboard = [
        [InlineKeyboardButton("🔍 البحث عن الموضوع", callback_data="search_last_ocr")],
        [get_cancel_button()]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("💡 **خيارات إضافية:**", reply_markup=reply_markup)

    if 'ocr_photos' in context.user_data:
        del context.user_data['ocr_photos']

async def process_photo_enhance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحسين جودة الصورة حتى 8 K - محسّن مع سجل أخطاء"""
    query = update.callback_query
    await query.answer()

    photo_url = context.user_data.get('pending_photo')
    if not photo_url:
        await query.edit_message_text("❌ انتهت صلاحية الصورة. أرسل صورة جديدة")
        return

    await query.edit_message_text("✨ جاري تحسين جودة الصورة حتى 8K...")
    logger.info(f"✨ Starting enhancement for: {photo_url[:100]}")

    try:
        enhanced_url = ai.quality_enhancer(photo_url)

        if ai.is_valid_image_url(enhanced_url):
            logger.info(f"✅ Enhancement successful: {enhanced_url[:100]}")
            await query.message.reply_photo(
                photo=enhanced_url,
                caption="✨ تم تحسين جودة الصورة بنجاح!\n📐 دقة محسّنة حتى 8K\n🎨 ألوان وتفاصيل محسّنة"
            )

            keyboard = [
                [InlineKeyboardButton("✨ تحسين صورة أخرى", callback_data="start_enhance_another")],
                [get_cancel_button()]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("💡 يمكنك تحسين المزيد من الصور:", reply_markup=reply_markup)
        else:
            logger.warning("❌ Enhancement failed - no valid URL returned")
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                "⚠️ عذراً، خدمة تحسين الجودة غير متاحة حالياً.\n"
                "جميع النماذج البديلة فشلت أيضاً.",
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"💥 Error in photo enhancement: {type(e).__name__} - {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"⚠️ حدث خطأ أثناء تحسين الصورة.\n"
            f"الخطأ: {str(e)}",
            reply_markup=reply_markup
        )

    if 'pending_photo' in context.user_data:
        del context.user_data['pending_photo']

async def process_multiple_photos_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تحرير عدة صور"""
    query = update.callback_query
    await query.answer()

    photo_urls = context.user_data.get('collected_photos', [])
    if not photo_urls:
        await query.edit_message_text("❌ لم يتم العثور على صور. أرسل صورة جديدة")
        return

    photo_count = len(photo_urls)
    context.user_data['edit_pending_multiple'] = photo_urls
    context.user_data['waiting_for_edit_desc_multi'] = True
    if 'waiting_for' in context.user_data:
        del context.user_data['waiting_for']
    if 'collected_photos' in context.user_data:
        del context.user_data['collected_photos']

    keyboard = [[get_cancel_button()]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✏️ **تم استلام {photo_count} صورة للتحرير**\n\n"
        "أرسل وصف التعديل المطلوب:\n\n"
        "مثال: اجعل الخلفية زرقاء\n"
        "مثال: أضف تأثير نيون\n"
        "مثال: حول الصورة إلى أبيض وأسود",
        reply_markup=reply_markup
    )

async def process_multiple_photos_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض خيارات استخراج النص للمستخدم"""
    query = update.callback_query
    await query.answer()

    photo_urls = context.user_data.get('collected_photos', [])
    if not photo_urls:
        await query.edit_message_text("❌ لم يتم العثور على صور. أرسل صورة جديدة")
        return

    photo_count = min(len(photo_urls), 10)
    photo_urls = photo_urls[:10]

    context.user_data['ocr_photos'] = photo_urls
    if 'waiting_for' in context.user_data:
        del context.user_data['waiting_for']
    if 'collected_photos' in context.user_data:
        del context.user_data['collected_photos']

    keyboard = [
        [InlineKeyboardButton("📝 استخراج النص فقط", callback_data="ocr_extract_only")],
        [InlineKeyboardButton("📝📖 استخراج + شرح", callback_data="ocr_extract_explain")],
        [InlineKeyboardButton("🌐📸 استخراج + ترجمة", callback_data="ocr_translate_menu")],
        [get_cancel_button()]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"📸 **تم استلام {photo_count} صورة**\n\n"
        "اختر ما تريد القيام به:",
        reply_markup=reply_markup
    )

async def process_photo_ocr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض خيارات استخراج النص للمستخدم"""
    query = update.callback_query
    await query.answer()

    photo_url = context.user_data.get('pending_photo')
    if not photo_url:
        await query.edit_message_text("❌ انتهت صلاحية الصورة. أرسل صورة جديدة")
        return

    context.user_data['waiting_for'] = 'analyze_photo'
    if 'collected_photos' not in context.user_data:
        context.user_data['collected_photos'] = []
    context.user_data['collected_photos'].append(photo_url)
    del context.user_data['pending_photo']

    keyboard = [[InlineKeyboardButton(f"✅ انتهيت (1 صورة)", callback_data="photos_done_analyze")],
                [get_cancel_button()]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📸 **استخراج النص من الصور**\n\n"
        "تم استلام الصورة! يمكنك:\n"
        "• إرسال المزيد من الصور (حتى 10 صور)\n"
        "• الضغط على 'انتهيت' لاختيار نوع العملية",
        reply_markup=reply_markup
    )

async def process_photo_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء تحرير الصورة"""
    query = update.callback_query
    await query.answer()

    photo_url = context.user_data.get('pending_photo')
    if not photo_url:
        await query.edit_message_text("❌ انتهت صلاحية الصورة. أرسل صورة جديدة")
        return

    context.user_data['edit_pending'] = photo_url
    del context.user_data['pending_photo']

    keyboard = [[get_cancel_button()]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "✏️ **أرسل وصف التعديل المطلوب:**\n\n"
        "مثال: اجعل الخلفية زرقاء\n"
        "مثال: أضف تأثير نيون\n"
        "مثال: حول الصورة إلى أبيض وأسود",
        reply_markup=reply_markup
    )

async def auto_solve_detected_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حل الأسئلة المكتشفة تلقائياً من النص المستخرج"""
    query = update.callback_query
    await query.answer()

    exercise_data = context.user_data.get('math_exercise')
    if not exercise_data or 'original_text' not in exercise_data:
        await query.edit_message_text("❌ انتهت صلاحية التمرين. أرسل صورة جديدة")
        return

    loading_msg = await query.edit_message_text("🧮 جاري حل جميع الأسئلة المكتشفة...")

    try:
        original_text = exercise_data['original_text']

        # أولاً: تحليل وتقسيم التمارين
        analysis_prompt = f"""حلل النص التالي وقسّمه إلى تمارين منفصلة (لجميع المواد: رياضيات، فيزياء، كيمياء، لغات، تاريخ، جغرافيا، إلخ):

{original_text}

**التعليمات:**
1. حدد نوع المادة
2. **صف أي بيانات/رسوم/جداول** مُعطاة بدقة
3. حدد عدد التمارين/الأسئلة
4. لكل تمرين، استخرج نصه كاملاً **مع** أي إشارات مرجعية

**أجب بالتنسيق التالي:**

**نوع المادة:** [المادة]

**البيانات/الرسوم المُعطاة:** [الوصف أو "لا يوجد"]

**عدد التمارين:** [الرقم]

**التمارين:**

━━━━━━ التمرين 1 ━━━━━━
[نص التمرين الأول كاملاً]

━━━━━━ التمرين 2 ━━━━━━
[نص التمرين الثاني كاملاً]

..."""

        analysis = ai.grok4(analysis_prompt)
        
        await query.message.reply_text(f"📋 **التحليل:**\n\n{analysis[:1000]}...")

        # حل كل تمرين في صورة منفصلة
        await query.message.reply_text("🧮 **جاري حل كل تمرين في صورة منفصلة...**")
        
        # استخراج عدد التمارين من التحليل
        import re
        exercise_count_match = re.search(r'عدد التمارين[:\s]*(\d+)', analysis)
        num_exercises = int(exercise_count_match.group(1)) if exercise_count_match else 1
        
        # حل كل تمرين على حدة
        for i in range(1, num_exercises + 1):
            await query.message.reply_text(f"🔍 **جاري حل التمرين {i}...**")
            
            # استخراج التمرين المحدد
            extract_prompt = f"""من التحليل التالي، استخرج **التمرين رقم {i}** فقط:

{analysis}

**النص الأصلي:**
{original_text}

قدم نص التمرين كاملاً مع أي بيانات/رسوم/إشارات مرجعية متعلقة به."""

            exercise_text = ai.grok4(extract_prompt)
            
            # حل التمرين
            solve_prompt = f"""حل التمرين التالي بالتفصيل (لأي مادة: رياضيات، فيزياء، كيمياء، لغة، تاريخ، إلخ):

{exercise_text}

**قواعد الحل:**
✓ حدد نوع المادة
✓ اذكر البيانات/الرسوم المُعطاة إن وُجدت
✓ وضّح المطلوب بدقة
✓ قدم الحل خطوة بخطوة
✓ للمسائل الرياضية/العلمية: استخدم (a/b) بدلاً من \\frac{{a}}{{b}}، و√x بدلاً من \\sqrt{{x}}
✓ للمسائل الأدبية/اللغوية: قدم إجابة منظمة وشاملة
✓ اعرض النتيجة النهائية بوضوح"""

            solution = ai.grok4(solve_prompt)
            
            # تحويل الحل إلى صورة
            solution_image_path = MathExerciseSolver.create_solution_image(solution, f"✅ حل التمرين {i}")
            
            if solution_image_path and os.path.exists(solution_image_path):
                await query.message.reply_photo(
                    photo=open(solution_image_path, 'rb'),
                    caption=f"✅ **حل التمرين {i} من {num_exercises}**"
                )
                try:
                    os.remove(solution_image_path)
                except:
                    pass
            else:
                # fallback: إرسال كنص
                if len(solution) > 4096:
                    parts = [solution[i:i+4096] for i in range(0, len(solution), 4096)]
                    for j, part in enumerate(parts):
                        await query.message.reply_text(f"✅ **حل التمرين {i} ({j+1}/{len(parts)}):**\n\n{part}")
                else:
                    await query.message.reply_text(f"✅ **حل التمرين {i}:**\n\n{solution}")

        keyboard = [
            [InlineKeyboardButton("🔄 حل تمرين آخر", callback_data="solve_another_exercise")],
            [get_cancel_button()]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await loading_msg.edit_text(f"✅ **تم إنجاز جميع الحلول ({num_exercises} تمرين)!**", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error in auto solve: {e}")
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"❌ حدث خطأ أثناء الحل: {str(e)}\nيرجى المحاولة مرة أخرى",
            reply_markup=reply_markup
        )

async def process_photo_math_solve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حل تمرين رياضي من صورة - تحليل ذكي للأسئلة"""
    query = update.callback_query
    await query.answer()

    photo_url = context.user_data.get('pending_photo')
    if not photo_url:
        await query.edit_message_text("❌ انتهت صلاحية الصورة. أرسل صورة جديدة")
        return

    del context.user_data['pending_photo']

    loading_msg = await query.edit_message_text("🔍 جاري تحليل الصورة واستخراج التمرين...")

    try:
        logger.info(f"🔍 Using OCR for math problem: {photo_url[:100]}")

        await loading_msg.edit_text("📝 جاري استخراج النص من الصورة...")

        # استخدام OCR API مباشرة مع رابط الصورة
        extracted_text = ai.ocr("", [photo_url])

        if not extracted_text or len(extracted_text.strip()) < 3:
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await loading_msg.edit_text(
                "❌ لم أتمكن من استخراج نص من الصورة.\n\n"
                "تأكد من:\n"
                "• وضوح الصورة\n"
                "• أن التمرين مكتوب بشكل واضح\n"
                "• جودة الصورة عالية",
                reply_markup=reply_markup
            )
            return

        # إرسال النص المستخرج مع أزرار تفاعلية
        text_preview = extracted_text[:500] + "..." if len(extracted_text) > 500 else extracted_text
        
        # حفظ النص الكامل في السياق للاستخدام لاحقاً
        context.user_data['extracted_full_text'] = extracted_text
        
        # أزرار تفاعلية للمستخدم
        action_keyboard = [
            [
                InlineKeyboardButton("📖 شرح مفصل", callback_data="ocr_explain"),
                InlineKeyboardButton("✍️ حل المسائل", callback_data="ocr_solve")
            ],
            [
                InlineKeyboardButton("🔄 ترجمة", callback_data="ocr_translate"),
                InlineKeyboardButton("📝 ملخص", callback_data="ocr_summary")
            ],
            [
                InlineKeyboardButton("🔍 بحث عن معلومات", callback_data="ocr_search"),
                InlineKeyboardButton("💡 أسئلة واجوبة", callback_data="ocr_qa")
            ],
            [InlineKeyboardButton("📄 عرض النص الكامل", callback_data="ocr_show_full")],
            [get_cancel_button()]
        ]
        action_markup = InlineKeyboardMarkup(action_keyboard)
        
        await query.message.reply_text(
            f"✅ **تم استخراج النص بنجاح!**\n\n"
            f"📝 **معاينة النص:**\n{text_preview}\n\n"
            f"🔢 **إجمالي الأحرف:** {len(extracted_text)}\n\n"
            f"❓ **ماذا تريد أن تفعل بهذا النص؟**",
            reply_markup=action_markup
        )
        
        # إرسال النص الكامل إذا كان طويلاً (في رسالة منفصلة)
        if len(extracted_text) > 4000:
            parts = [extracted_text[i:i+4000] for i in range(0, len(extracted_text), 4000)]
            for i, part in enumerate(parts):
                if i == 0:
                    await query.message.reply_text(f"📝 **النص الكامل ({i+1}/{len(parts)}):**\n\n{part}")
                else:
                    await query.message.reply_text(f"📝 **({i+1}/{len(parts)}):**\n\n{part}")

        await loading_msg.edit_text("🔍 جاري تحليل النص واكتشاف الأسئلة...")

        # تحليل ذكي للكشف عن وجود أسئلة محددة
        detection_prompt = f"""حلل النص التالي بدقة شديدة (مع الحفاظ على التنسيق الأصلي):

{extracted_text}

**التعليمات:**
1. **استخرج النص كما هو بالضبط** دون تغيير التنسيق أو الترتيب
2. **صف أي بيانات/رسوم/جداول** إن وُجدت بدقة (مثل: "يوجد رسم بياني للدالة y=...", "جدول يحتوي على...")
3. **حدد عدد التمارين/الأسئلة** بدقة (مثل: "يوجد 3 تمارين")
4. **حدد نوع المادة** (رياضيات، فيزياء، كيمياء، لغة عربية، إنجليزية، تاريخ، جغرافيا، أحياء، إلخ)
5. **اذكر أي إشارات مرجعية** (مثل: "كما ذكرنا في التمرين السابق...")

**أجب بالتنسيق التالي:**

**هل يوجد أسئلة/مطاليب؟** [نعم/لا]

**عدد التمارين:** [الرقم]

**نوع المادة:** [المادة]

**وصف البيانات/الرسوم:** [الوصف أو "لا يوجد"]

**الإشارات المرجعية:** [نعم/لا - اذكرها إن وُجدت]

**قائمة التمارين:**
1. [نص التمرين الأول كما هو]
2. [نص التمرين الثاني كما هو]
..."""

        detection_result = ai.grok4(detection_prompt)
        
        # التحقق من وجود أسئلة محددة
        has_questions = "نعم" in detection_result[:100] or "yes" in detection_result[:100].lower()

        # حفظ النص المستخرج في السياق
        context.user_data['math_exercise'] = {
            'original_text': extracted_text,
            'detection_result': detection_result,
            'has_questions': has_questions
        }

        await query.message.reply_text(f"🔍 **نتيجة التحليل:**\n\n{detection_result}")

        if has_questions:
            # يوجد أسئلة محددة -> حلها مباشرة
            keyboard = [
                [InlineKeyboardButton("✅ ابدأ الحل مباشرة", callback_data="auto_solve_questions")],
                [get_cancel_button()]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await loading_msg.edit_text(
                "✅ **تم اكتشاف أسئلة محددة في النص!**\n\n"
                "سأقوم بحلها خطوة بخطوة.",
                reply_markup=reply_markup
            )
        else:
            # لا يوجد أسئلة محددة -> اطلب من المستخدم كتابة ماذا يريد
            context.user_data['waiting_for_math_instruction'] = True
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await loading_msg.edit_text(
                "❓ **لم أجد سؤالاً محدداً في النص.**\n\n"
                "📝 **اكتب ماذا تريد أن أفعل بهذا النص:**\n\n"
                "أمثلة:\n"
                "• احسب المشتقة\n"
                "• احسب التكامل\n"
                "• حل المعادلة\n"
                "• بسّط التعبير\n"
                "• أوجد قيمة x\n"
                "• أو أي شيء آخر تريده...",
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"Error in math solve: {e}")
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await loading_msg.edit_text(
                f"❌ حدث خطأ أثناء تحليل التمرين.\n\n"
                f"الخطأ: {str(e)}\n\n"
                "يرجى المحاولة مرة أخرى",
                reply_markup=reply_markup
            )
        except:
            await query.message.reply_text(
                "❌ حدث خطأ أثناء تحليل التمرين.\nيرجى المحاولة مرة أخرى",
                reply_markup=reply_markup
            )



async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة الأخطاء العامة للبوت"""
    error = context.error

    if isinstance(error, TelegramError):
        if "Conflict" in str(error):
            logger.warning("⚠️ تعارض في التحديثات - نسخة أخرى من البوت قد تكون تعمل")
            return
        elif "Timeout" in str(error):
            logger.warning("⚠️ انتهت مهلة الطلب")
            return
        elif "Network" in str(error):
            logger.warning("⚠️ خطأ في الشبكة")
            return

    logger.error(f"❌ خطأ غير متوقع: {type(error).__name__}: {str(error)}")

    # الرد على المستخدم فقط إذا كان هناك update و effective_message
    if update and hasattr(update, 'effective_message') and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى."
            )
        except:
            pass

def main():
    """تشغيل البوت"""
    try:
        logger.info("🌐 بدء Web Server للـ Health Checks...")
        try:
            from web_server import start_web_server
            start_web_server()
        except Exception as web_error:
            logger.warning(f"⚠️ تعذر بدء Web Server: {web_error}")

        # بدء نظام Keep-Alive الداخلي
        logger.info("🔄 بدء نظام Keep-Alive الداخلي...")
        try:
            from keep_alive import start_keep_alive
            start_keep_alive(interval_minutes=2)  # Ping كل دقيقتين
        except Exception as ka_error:
            logger.warning(f"⚠️ تعذر بدء Keep-Alive: {ka_error}")

        logger.info("🔧 تهيئة التطبيق...")
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        logger.info("📝 تسجيل معالجات الأوامر...")
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        application.add_handler(CallbackQueryHandler(admin_callback))

        application.add_error_handler(error_handler)
        logger.info("✅ تم تسجيل معالج الأخطاء")

        # إضافة Heartbeat Job لإبقاء البوت نشطاً
        async def heartbeat_job(context: ContextTypes.DEFAULT_TYPE):
            """مهمة Heartbeat لإبقاء البوت نشطاً (async مع non-blocking request)"""
            try:
                import requests
                # استخدام run_in_executor لتجنب blocking event loop
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, 
                    lambda: requests.get("http://127.0.0.1:5000/ping", timeout=3)
                )
                if response.status_code == 200:
                    logger.info(f"💓 Heartbeat ناجح - {datetime.now().strftime('%H:%M:%S')}")
            except Exception as e:
                logger.debug(f"Heartbeat error (normal): {e}")
        
        # إضافة Heartbeat كل دقيقة
        job_queue = application.job_queue
        job_queue.run_repeating(heartbeat_job, interval=60, first=60)
        logger.info("✅ تم تسجيل Heartbeat Job (كل 60 ثانية - async non-blocking)")

        logger.info("=" * 50)
        logger.info("✅ البوت يعمل الآن وجاهز لاستقبال الرسائل")
        logger.info(f"🤖 Admin ID: {ADMIN_ID}")
        logger.info(f"📢 القناة المطلوبة: {REQUIRED_CHANNEL}")
        
        # طباعة رابط ping الحالي
        import socket
        hostname = socket.gethostname()
        logger.info("=" * 50)
        logger.info("🔔 معلومات Cron-Job.org:")
        logger.info(f"📍 Hostname: {hostname}")
        logger.info("📍 استخدم رابط Deployment الثابت بعد النشر")
        logger.info("⚠️ رابط Dev Domain يتغير باستمرار - لا تستخدمه!")
        logger.info("=" * 50)
        
        logger.info("=" * 50)

        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.error("=" * 50)
        logger.error(f"💥 خطأ فادح في تشغيل البوت: {type(e).__name__}")
        logger.error(f"التفاصيل: {str(e)}")
        logger.error("=" * 50)
        import traceback
        logger.error(traceback.format_exc())
        raise

if __name__ == '__main__':
    main()