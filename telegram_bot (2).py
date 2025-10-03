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
from datetime import datetime
from typing import Optional, Dict, Any
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

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7848268331:AAHzmuy87fcemSTKTmQkdDJtmhlS3F5C7PI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7401831506"))
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@boyta28")

class Database:
    """إدارة قاعدة البيانات"""

    def __init__(self, use_database=True):
        self.use_database = use_database
        if self.use_database:
            try:
                self.conn = sqlite3.connect('bot_database.db', check_same_thread=False)
                self.create_tables()
            except Exception as e:
                logger.warning(f"Database disabled due to error: {e}")
                self.use_database = False
                self.conn = None
        else:
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
                last_activity TEXT
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
                message TEXT,
                response TEXT,
                timestamp TEXT
            )
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO stats (id, total_messages, total_users)
            VALUES (1, 0, 0)
        ''')
        self.conn.commit()

    def add_or_update_user(self, user_id: int, username: str, first_name: str):
        if not self.use_database or not self.conn:
            return
        try:
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

    def add_conversation(self, user_id: int, message: str, response: str):
        if not self.use_database or not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO conversations (user_id, message, response, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (user_id, message, response, now))
            self.conn.commit()

            # حذف المحادثات القديمة (أكثر من 10 رسائل)
            cursor.execute('''
                DELETE FROM conversations WHERE user_id = ? AND timestamp NOT IN (
                    SELECT timestamp FROM conversations WHERE user_id = ? 
                    ORDER BY timestamp DESC LIMIT 10
                )
            ''', (user_id, user_id))
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")

    def get_conversation_history(self, user_id: int, limit: int = 5) -> list:
        if not self.use_database or not self.conn:
            return []
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT message, response FROM conversations 
                WHERE user_id = ? 
                ORDER BY timestamp DESC LIMIT ?
            ''', (user_id, limit))
            results = cursor.fetchall()
            return list(reversed(results))
        except Exception as e:
            logger.warning(f"Database operation failed: {e}")
            return []

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

db = Database(use_database=True)

async def check_channel_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """التحقق من اشتراك المستخدم في القناة"""
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
    def grok4(text: str, conversation_history: list = None) -> str:
        """نموذج Grok-4 للمحادثة العامة مع سياق المحادثة"""
        try:
            # إضافة سياق المحادثة
            prompt = text
            if conversation_history:
                context = "\n".join([f"المستخدم: {msg}\nالمساعد: {resp}" for msg, resp in conversation_history[-3:]])
                prompt = f"سياق المحادثة السابقة:\n{context}\n\nالسؤال الحالي: {text}"

            response = requests.post(
                'https://sii3.top/api/grok4.php',
                data={'text': prompt},
                timeout=45
            )
            if response.ok:
                result = response.text
                return AIModels._clean_response(result)
            else:
                return f"خطأ: {response.status_code}"
        except Exception as e:
            return f"خطأ في الاتصال: {str(e)}"

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
    def ocr(text: str, image_urls: list) -> str:
        """استخراج النص من الصور - نفس منطق OCR_1759483533898.py"""
        try:
            if not image_urls:
                return ""
            
            links = ", ".join(image_urls[:10])
            logger.info(f"OCR request - text: {text[:50] if text else 'empty'}, images: {len(image_urls)}")
            logger.info(f"OCR links: {links[:200]}")
            
            payload = {"text": text if text else ""}
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
    def seedream(text: str, image_urls: list = None, max_retries: int = 2) -> str:
        """توليد وتحرير الصور"""
        # ترجمة النص للإنجليزية لتحسين الدقة
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
                    if (result.startswith('http://') or result.startswith('https://')) and any(ext in result.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
                        return result
                    logger.warning(f"seedream invalid response on attempt {attempt + 1}")
                else:
                    logger.warning(f"seedream HTTP error {response.status_code} on attempt {attempt + 1}")
            except requests.exceptions.Timeout:
                logger.warning(f"seedream timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"seedream error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue

        return ""

    @staticmethod
    def gpt_imager(text: str, image_url: str = None, max_retries: int = 2) -> str:
        """إنشاء وتعديل الصور"""
        # ترجمة النص للإنجليزية لتحسين الدقة
        english_text = AIModels.translate_to_english(text)
        
        data = {'text': english_text}
        if image_url:
            data['link'] = image_url

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    'https://sii3.top/api/gpt-img.php',
                    data=data,
                    timeout=150
                )
                if response.ok:
                    result = response.text.strip()
                    if (result.startswith('http://') or result.startswith('https://')) and any(ext in result.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
                        return result
                    logger.warning(f"gpt_imager invalid response on attempt {attempt + 1}")
                else:
                    logger.warning(f"gpt_imager HTTP error {response.status_code} on attempt {attempt + 1}")
            except requests.exceptions.Timeout:
                logger.warning(f"gpt_imager timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"gpt_imager error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue

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
        # ترجمة النص للإنجليزية لتحسين الدقة
        english_text = AIModels.translate_to_english(text)
        
        data = {'text': english_text}
        if image_urls:
            data['links'] = ','.join(image_urls[:10])

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    'https://sii3.top/api/nano-banana.php',
                    data=data,
                    timeout=60
                )
                if response.ok:
                    response_text = response.text.strip()
                    logger.info(f"nano_banana response on attempt {attempt + 1}: {response_text[:200]}")

                    # Try parsing as JSON first
                    try:
                        json_data = response.json()
                        result = json_data.get('image', json_data.get('url', json_data.get('result', '')))
                        if AIModels.is_valid_image_url(result):
                            return result
                        logger.warning(f"nano_banana JSON parsed but no valid URL found: {json_data}")
                    except:
                        # If not JSON, treat as direct URL
                        if AIModels.is_valid_image_url(response_text):
                            return response_text
                        logger.warning(f"nano_banana not JSON and not valid URL: {response_text[:200]}")
                else:
                    logger.warning(f"nano_banana HTTP error {response.status_code} on attempt {attempt + 1}: {response.text[:200]}")
            except requests.exceptions.Timeout:
                logger.warning(f"nano_banana timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"nano_banana error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue

        return ""

    @staticmethod
    def quality_enhancer(image_url: str, max_retries: int = 3) -> str:
        """تحسين جودة الصور حتى دقة 8K باستخدام GPT-5 - يدعم http و https وروابط Telegram"""
        import hashlib
        import urllib.parse
        
        # حساب hash للصورة الأصلية للمقارنة
        original_hash = hashlib.md5(image_url.encode()).hexdigest()[:8]
        logger.info(f"Original image hash: {original_hash}, URL: {image_url[:100]}")
        
        for attempt in range(max_retries):
            try:
                # استخدام urlencode لضمان ترميز الرابط بشكل صحيح
                encoded_url = urllib.parse.quote(image_url, safe='')
                api_url = f'https://sii3.top/api/quality.php?link={encoded_url}'
                logger.info(f"quality_enhancer attempt {attempt + 1} using encoded URL")
                
                response = requests.get(
                    api_url,
                    timeout=150
                )
                if response.ok:
                    response_text = response.text.strip()
                    logger.info(f"quality_enhancer response on attempt {attempt + 1}: {response_text[:200]}")

                    # محاولة تحليل JSON أولاً
                    try:
                        json_data = response.json()
                        
                        # التحقق من وجود خطأ في الاستجابة
                        if 'error' in json_data:
                            error_msg = json_data['error']
                            logger.warning(f"quality_enhancer API error on attempt {attempt + 1}: {error_msg}")
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
                                    logger.warning(f"Received same image or similar URL, retrying...")
                                    if attempt < max_retries - 1:
                                        import time
                                        time.sleep(2)
                                        continue
                            logger.warning(f"quality_enhancer JSON parsed but no valid URL found: {json_data}")
                    except json.JSONDecodeError:
                        # إذا لم يكن JSON، التعامل كرابط مباشر
                        if AIModels.is_valid_image_url(response_text):
                            result_hash = hashlib.md5(response_text.encode()).hexdigest()[:8]
                            if result_hash != original_hash:
                                logger.info(f"✅ quality_enhancer success (direct URL) - hash: {result_hash}")
                                return response_text
                        logger.warning(f"quality_enhancer not JSON and not valid URL: {response_text[:200]}")
                else:
                    logger.warning(f"quality_enhancer HTTP error {response.status_code} on attempt {attempt + 1}: {response.text[:200]}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(3)
            except requests.exceptions.Timeout:
                logger.warning(f"quality_enhancer timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
            except Exception as e:
                logger.error(f"quality_enhancer error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue

        # إذا فشلت جميع المحاولات، استخدم نماذج بديلة متعددة
        logger.info("All quality_enhancer attempts failed, trying multiple fallback models")
        
        # محاولة 1: nano_banana
        logger.info("Trying nano_banana as fallback 1")
        fallback_url = AIModels.nano_banana("enhance image quality 8K, improve details, sharpen, increase resolution, upscale to ultra high resolution, professional quality enhancement", [image_url])
        if AIModels.is_valid_image_url(fallback_url):
            logger.info("✅ nano_banana fallback succeeded")
            return fallback_url
        
        # محاولة 2: gpt_imager
        logger.info("nano_banana failed, trying gpt_imager as fallback 2")
        fallback_url = AIModels.gpt_imager("enhance and upscale image quality to 8K resolution, improve details, colors and sharpness, professional enhancement", image_url)
        if AIModels.is_valid_image_url(fallback_url):
            logger.info("✅ gpt_imager fallback succeeded")
            return fallback_url
        
        # محاولة 3: seedream
        logger.info("gpt_imager failed, trying seedream as fallback 3")
        fallback_url = AIModels.seedream("upscale to 8K ultra resolution, enhance quality, improve details and clarity, sharpen image", [image_url])
        if AIModels.is_valid_image_url(fallback_url):
            logger.info("✅ seedream fallback succeeded")
            return fallback_url
        
        # إذا فشلت جميع النماذج
        logger.error("❌ All quality enhancement models failed")
        return ""

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
    """أمر البدء"""
    user = update.effective_user

    # التحقق من الاشتراك
    is_subscribed = await check_channel_membership(user.id, context)
    if not is_subscribed:
        await send_subscription_required_message(update, context)
        return

    keyboard = [
        [KeyboardButton("📚 مساعدة في الدراسة"), KeyboardButton("🔍 البحث")],
        [KeyboardButton("💻 مساعدة برمجة"), KeyboardButton("🎨 إنشاء صورة")],
        [KeyboardButton("✏️ تحرير صورة"), KeyboardButton("📸 تحليل صورة")],
        [KeyboardButton("✨ تحسين جودة صورة"), KeyboardButton("❓ المساعدة")]
    ]

    if user.id == ADMIN_ID:
        keyboard.append([KeyboardButton("⚙️ لوحة التحكم")])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_text = f"""
🎓 أهلاً {user.first_name}!

أنا بوت ذكي لمساعدة الطلاب 🤖

✨ **ما يمكنني فعله:**
📚 حل التمارين والأسئلة الدراسية
🔍 البحث عن المواد الدراسية
💻 مساعدتك في البرمجة والأكواد
📸 استخراج النص من الصور وتحليلها
🎨 إنشاء صور توضيحية وتعليمية
✏️ تحرير الصور بالذكاء الاصطناعي
✨ تحسين جودة الصور حتى 8K

**للبدء:**
- أرسل سؤالك مباشرة
- أو استخدم الأزرار أدناه
- أرسل صورة تمرين وسأحله لك!

دعنا نبدأ رحلة التعلم معاً! 🚀
    """

    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر المساعدة"""
    user = update.effective_user

    # التحقق من الاشتراك
    is_subscribed = await check_channel_membership(user.id, context)
    if not is_subscribed:
        await send_subscription_required_message(update, context)
        return

    help_text = """
🤖 **دليل استخدام البوت:**

**📚 للمساعدة في الدراسة:**
- أرسل سؤالك مباشرة
- مثال: "اشرح لي قانون نيوتن الثاني"

**🔍 للبحث:**
- اضغط زر "🔍 البحث" أو اكتب: /بحث [الموضوع]
- مثال: /بحث تمرين 14 ص25 رياضيات

**💻 للمساعدة في البرمجة:**
- اضغط زر "💻 مساعدة برمجة" أو اكتب: /كود [سؤالك]
- مثال: /كود كيف أكتب حلقة for في Python

**📸 لتحليل الصور:**
- اكتب: /تحليل ثم أرسل الصورة
- أو اضغط زر "📸 تحليل صورة"

**🎨 لإنشاء صور:**
- اضغط زر "🎨 إنشاء صورة"
- ثم اكتب وصف الصورة المطلوبة
- مثال: "رسم توضيحي للدورة الدموية"

**✏️ لتحرير صور:**
- اكتب: /تحرير ثم أرسل الصورة
- أو اضغط زر "✏️ تحرير صورة"
- ثم اكتب وصف التحرير
- مثال: "اجعل الخلفية زرقاء"

**✨ لتحسين جودة الصور:**
- اضغط زر "✨ تحسين جودة صورة"
- أرسل الصورة
- سيتم تحسينها حتى دقة 8K باستخدام GPT-5
- تحسين الألوان، التفاصيل، والوضوح

**💡 نصيحة:** يمكنك إلغاء أي عملية بالضغط على زر "❌ إلغاء"

أي سؤال آخر؟ فقط اسأل! 😊
    """
    await update.message.reply_text(help_text)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لوحة تحكم الأدمن"""
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا الأمر متاح للمشرف فقط!")
        return

    keyboard = [
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats")],
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
            "أرسل الصورة التي تريد تحسين جودتها حتى 8K",
            reply_markup=reply_markup
        )
        return

    # معالجة خيارات الصورة
    if query.data == "photo_ocr":
        await process_photo_ocr(update, context)
        return

    if query.data == "photo_edit":
        await process_photo_edit(update, context)
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

    # معالجة خيارات OCR الجديدة
    if query.data.startswith("ocr_extract") or query.data.startswith("ocr_translate") or query.data.startswith("ocr_trans_") or query.data == "ocr_back_menu":
        await handle_ocr_option(update, context)
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

        loading_msg = LoadingAnimation.get_random_animation(f"🎨 جاري تحرير الصورة باستخدام {model}...")
        await query.edit_message_text(loading_msg)

        try:
            # استخدام Nano Banana فقط (يدعم حتى 10 صور)
            image_url = ai.nano_banana(edit_query, [photo_url])

            if ai.is_valid_image_url(image_url):
                await query.message.reply_photo(
                    photo=image_url,
                    caption=f"✨ تم التحرير: {edit_query}"
                )

                keyboard = [
                    [InlineKeyboardButton("✏️ تحرير مرة أخرى", callback_data=f"start_edit:{image_url}")],
                    [get_cancel_button()]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("💡 يمكنك تحرير الصورة مرة أخرى:", reply_markup=reply_markup)

                del context.user_data['edit_image']
            else:
                keyboard = [[get_cancel_button()]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("عذراً، حدث خطأ في التحرير. حاول مرة أخرى", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error editing: {e}")
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("عذراً، حدث خطأ في التحرير", reply_markup=reply_markup)
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
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ غير مصرح لك!")
        return

    if query.data == "admin_stats":
        stats = db.get_stats()
        stats_text = f"""
📊 **إحصائيات البوت:**

👥 إجمالي المستخدمين: {stats['total_users']}
💬 إجمالي الرسائل: {stats['total_messages']}
🚫 المستخدمون المحظورون: {stats['banned_users']}
🔇 المستخدمون المكتومون: {stats['muted_users']}

📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """
        keyboard = [[get_cancel_button()]]
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
    """معالجة جميع الرسائل"""
    user = update.effective_user
    message = update.message

    # التحقق من الاشتراك
    is_subscribed = await check_channel_membership(user.id, context)
    if not is_subscribed:
        await send_subscription_required_message(update, context)
        return

    db.add_or_update_user(user.id, user.username or "", user.first_name or "")

    if db.is_banned(user.id):
        await message.reply_text("⛔ أنت محظور من استخدام البوت!")
        return

    if db.is_muted(user.id):
        return

    # معالجة أوامر الأدمن
    if context.user_data.get('admin_action') and user.id == ADMIN_ID:
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
    if context.user_data.get('edit_pending'):
        photo_url = context.user_data['edit_pending']
        edit_query = message.text

        # اختيار نموذج التحرير
        context.user_data['edit_image'] = {
            'url': photo_url,
            'query': edit_query
        }

        # استخدام Nano Banana مباشرة (يدعم حتى 10 صور)
        await message.reply_text(f"🍌 جاري تحرير الصورة...")

        image_url = ai.nano_banana(edit_query, [photo_url])

        if ai.is_valid_image_url(image_url):
            await message.reply_photo(
                photo=image_url,
                caption=f"✨ تم التحرير: {edit_query}"
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
    if context.user_data.get('edit_pending_multiple'):
        photo_urls = context.user_data['edit_pending_multiple']
        edit_query = message.text
        photo_count = len(photo_urls)

        await message.reply_text(f"🎨 جاري تحرير {photo_count} صورة...")

        # تحرير جميع الصور بنموذج Nano Banana (يدعم حتى 10 صور)
        for i, photo_url in enumerate(photo_urls[:10], 1):
            await message.reply_text(f"⏳ جاري تحرير الصورة {i}/{min(photo_count, 10)}...")
            image_url = ai.nano_banana(edit_query, [photo_url])

            if ai.is_valid_image_url(image_url):
                await message.reply_photo(
                    photo=image_url,
                    caption=f"✨ الصورة {i}: {edit_query}"
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

    # الحصول على سياق المحادثة
    conversation_history = db.get_conversation_history(user.id)
    response = ai.grok4(text, conversation_history)

    try:
        await status_message.delete()
    except:
        pass

    # حفظ المحادثة
    db.add_conversation(user.id, text, response)

    if len(response) > 4096:
        for i in range(0, len(response), 4096):
            await message.reply_text(response[i:i+4096])
    else:
        await message.reply_text(response)

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
                await message.reply_text("💡 **يمكنك تحسين المزيد من الصور:**", reply_markup=reply_markup)
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
            "❌ عذراً، لم أتمكن من استخراج نص واضح من الصور.\nتأكد من وضوح الصور وحاول مرة أخرى.",
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
1. إذا كان تمريناً، قدم الحل التفصيلي
2. إذا كان نصاً، قدم شرحاً مبسطاً
3. اشرح المصطلحات المهمة

لا تكرر النص، ركز على التحليل والشرح."""

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
    """تحسين جودة الصورة حتى 8K"""
    query = update.callback_query
    await query.answer()

    photo_url = context.user_data.get('pending_photo')
    if not photo_url:
        await query.edit_message_text("❌ انتهت صلاحية الصورة. أرسل صورة جديدة")
        return

    await query.edit_message_text("✨ جاري تحسين جودة الصورة حتى 8K...")

    try:
        enhanced_url = ai.quality_enhancer(photo_url)

        if ai.is_valid_image_url(enhanced_url):
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
            keyboard = [[get_cancel_button()]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                "⚠️ عذراً، خدمة تحسين الجودة غير متاحة حالياً.\n"
                "يرجى المحاولة مرة أخرى بعد قليل.",
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Error in photo enhancement: {e}")
        keyboard = [[get_cancel_button()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            "⚠️ حدث خطأ أثناء تحسين الصورة.\nيرجى المحاولة مرة أخرى.",
            reply_markup=reply_markup
        )

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

    keyboard = [
        [InlineKeyboardButton(f"✅ انتهيت (1 صورة)", callback_data="photos_done_analyze")],
        [get_cancel_button()]
    ]
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

def main():
    """تشغيل البوت"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(admin_callback))

    logger.info("🚀 البوت يعمل الآن...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()