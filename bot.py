import os
import logging
import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from database import init_db, add_user, save_book, get_chapters, get_chapter_details, update_chapter_summary, update_chapter_questions
import pdfplumber
from duckduckgo_search import DDGS

# إعدادات التسجيل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# التوكن
TOKEN = "8310878802:AAHAtRQeTILAiypucDDWRPpehQzH0N62-Ls"

# الحالات (States)
WAITING_FOR_PDF = 1
WAITING_FOR_QUESTION_COUNT = 2

async def ask_ai(prompt, model="gpt-4o-mini"):
    """وظيفة لاستدعاء الذكاء الاصطناعي مجاناً عبر DuckDuckGo"""
    try:
        with DDGS() as ddgs:
            response = ddgs.chat(prompt, model=model)
            return response
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await add_user(user.id, user.username, user.full_name)
    
    keyboard = [
        [InlineKeyboardButton("📚 إرسال كتاب", callback_query_data='send_book')],
        [InlineKeyboardButton("👨‍💻 تواصل مع المطور", callback_query_data='contact_dev')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"أهلاً بك يا {user.first_name} في بوت استخلاص الأسئلة لمواد ثالثة ثانوي علمي! 🎓\n\n"
        "أنا هنا لمساعدتك في دراستك من خلال تحليل كتبك وتوليد ملخصات واختبارات ذكية ومجانية بالكامل.",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == 'send_book':
        context.user_data['state'] = WAITING_FOR_PDF
        await query.edit_message_text("يرجى إرسال الكتاب بصيغة PDF الآن. 📄")
        
    elif data == 'contact_dev':
        await query.edit_message_text("يمكنك التواصل مع المطور عبر: @YourDevUsername")

    elif data.startswith('chapter_'):
        chapter_id = int(data.split('_')[1])
        context.user_data['current_chapter_id'] = chapter_id
        
        keyboard = [
            [InlineKeyboardButton("📝 ملخص عن الباب", callback_query_data=f'summary_{chapter_id}')],
            [InlineKeyboardButton("❓ استخراج أسئلة", callback_query_data=f'questions_{chapter_id}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("ماذا تريد أن أفعل بهذا الباب؟", reply_markup=reply_markup)

    elif data.startswith('summary_'):
        chapter_id = int(data.split('_')[1])
        await query.edit_message_text("جاري استخراج الملخص... قد يستغرق ذلك لحظات. ⏳")
        await handle_summary(query, chapter_id)

    elif data.startswith('questions_'):
        chapter_id = int(data.split('_')[1])
        keyboard = [
            [InlineKeyboardButton("📋 أسئلة وإجابات", callback_query_data=f'all_q_{chapter_id}')],
            [InlineKeyboardButton("📝 اختبر نفسك", callback_query_data=f'quiz_{chapter_id}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("اختر نوع الأسئلة:", reply_markup=reply_markup)

    elif data.startswith('all_q_'):
        chapter_id = int(data.split('_')[1])
        await query.edit_message_text("جاري استخراج الأسئلة... ⏳")
        await handle_all_questions(query, chapter_id)

    elif data.startswith('quiz_'):
        chapter_id = int(data.split('_')[1])
        context.user_data['state'] = WAITING_FOR_QUESTION_COUNT
        context.user_data['quiz_chapter_id'] = chapter_id
        await query.edit_message_text("كم عدد الأسئلة التي تريدها؟ (الحد الأقصى المقترح: 50)")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != WAITING_FOR_PDF:
        return

    doc = update.message.document
    if doc.mime_type != 'application/pdf':
        await update.message.reply_text("عذراً، يجب إرسال ملف بصيغة PDF فقط.")
        return

    processing_msg = await update.message.reply_text("جاري استلام الكتاب ومعالجته... ⏳")
    
    file = await context.bot.get_file(doc.file_id)
    # حفظ الملف في المسار الرئيسي مباشرة لأن المنصة لا تدعم المجلدات
    file_path = f"{doc.file_id}.pdf"
    await file.download_to_drive(file_path)
    
    try:
        text_content = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_content += text + "\n"
        
        book_id = await save_book(update.effective_user.id, doc.file_id, doc.file_name, text_content)
        await processing_msg.edit_text("جاري تحليل الكتاب واستخراج الأبواب... 🧠")
        
        chapters = await extract_chapters_ai(text_content)
        
        if not chapters:
            await processing_msg.edit_text("عذراً، لم أتمكن من استخراج الأبواب بشكل آلي. يرجى التأكد من أن ملف الـ PDF يحتوي على نص قابل للقراءة.")
            return

        buttons = []
        for chapter in chapters:
            chapter_id = await add_chapter(book_id, chapter['title'], chapter['content'])
            buttons.append([InlineKeyboardButton(chapter['title'], callback_query_data=f'chapter_{chapter_id}')])
        
        reply_markup = InlineKeyboardMarkup(buttons)
        await processing_msg.edit_text(f"تم تحليل الكتاب بنجاح! تم العثور على {len(chapters)} أبواب. اختر الباب الذي تريد دراسته:", reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error processing PDF: {e}")
        await processing_msg.edit_text("حدث خطأ أثناء معالجة الكتاب. يرجى المحاولة مرة أخرى.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

async def extract_chapters_ai(text):
    sample_text = text[:15000]
    prompt = f"""
    أنت خبير في تحليل الكتب المدرسية. قم بتحليل النص التالي واستخرج منه قائمة دقيقة بالأبواب (Chapters) أو الفصول الرئيسية.
    يجب أن تكون العناوين مطابقة تماماً لما هو موجود في الكتاب.
    أريد النتيجة بتنسيق JSON فقط كقائمة من الكائنات تحت مفتاح "chapters"، كل كائن يحتوي على "title".
    لا تضف أي نص خارج الـ JSON.
    
    النص:
    {sample_text}
    """
    
    response_text = await ask_ai(prompt)
    if not response_text: return []
    
    try:
        # تنظيف النص من أي علامات Markdown إذا وجدت
        clean_json = response_text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)
        chapters_list = data.get('chapters', [])
        
        final_chapters = []
        for i, item in enumerate(chapters_list):
            title = item.get('title', '')
            start_idx = text.find(title)
            if i < len(chapters_list) - 1:
                next_title = chapters_list[i+1].get('title', '')
                end_idx = text.find(next_title)
                content = text[start_idx:end_idx] if start_idx != -1 and end_idx != -1 else "محتوى الباب قيد المعالجة..."
            else:
                content = text[start_idx:] if start_idx != -1 else "محتوى الباب قيد المعالجة..."
            final_chapters.append({'title': title, 'content': content})
        return final_chapters
    except:
        return []

async def handle_summary(query, chapter_id):
    details = await get_chapter_details(chapter_id)
    title, content, summary, _ = details
    
    if summary:
        await query.edit_message_text(f"📝 *ملخص {title}:*\n\n{summary}", parse_mode='Markdown')
        return

    prompt = f"قم بتلخيص المحتوى التالي من كتاب مدرسي للسنة الثالثة ثانوي علمي بشكل دقيق وشامل ومستند فقط على النص.\nالمحتوى:\n{content[:15000]}"
    summary_text = await ask_ai(prompt)
    
    if summary_text:
        await update_chapter_summary(chapter_id, summary_text)
        await query.edit_message_text(f"📝 *ملخص {title}:*\n\n{summary_text}", parse_mode='Markdown')
    else:
        await query.edit_message_text("عذراً، حدث خطأ أثناء توليد الملخص.")

async def handle_all_questions(query, chapter_id):
    details = await get_chapter_details(chapter_id)
    title, content, _, _ = details
    
    prompt = f"استخرج جميع أنواع الأسئلة الممكنة (MCQ، صح وخطأ، مقالي) مع إجاباتها من النص التالي.\nالنص:\n{content[:15000]}"
    questions_text = await ask_ai(prompt)
    
    if questions_text:
        await query.edit_message_text(f"📋 *أسئلة وإجابات {title}:*\n\n{questions_text}", parse_mode='Markdown')
    else:
        await query.edit_message_text("عذراً، حدث خطأ أثناء استخراج الأسئلة.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')
    if state == WAITING_FOR_QUESTION_COUNT:
        try:
            count = int(update.message.text)
            chapter_id = context.user_data.get('quiz_chapter_id')
            await start_quiz(update, context, chapter_id, count)
        except ValueError:
            await update.message.reply_text("يرجى إدخال رقم صحيح.")

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, chapter_id, count):
    details = await get_chapter_details(chapter_id)
    title, content, _, _ = details
    
    count = min(count, 20) # تحديد الحد الأقصى لكل طلب لضمان استقرار الـ AI المجاني
    await update.message.reply_text(f"جاري إنشاء اختبار من {count} أسئلة... ⏳")
    
    prompt = f"""
    قم بإنشاء {count} سؤال اختيار من متعدد من النص التالي. 
    يجب أن يكون لكل سؤال 4 خيارات وإجابة واحدة صحيحة.
    أريد النتيجة بتنسيق JSON فقط كقائمة من الكائنات تحت مفتاح "questions"، كل كائن يحتوي على:
    "question": نص السؤال
    "options": قائمة بـ 4 خيارات
    "correct_index": رقم الخيار الصحيح (0-3)
    لا تضف أي نص خارج الـ JSON.
    
    النص:
    {content[:10000]}
    """
    
    response_text = await ask_ai(prompt)
    if not response_text:
        await update.message.reply_text("عذراً، حدث خطأ أثناء توليد الاختبار.")
        return

    try:
        clean_json = response_text.replace('```json', '').replace('```', '').strip()
        quiz_data = json.loads(clean_json)
        questions = quiz_data.get('questions', [])
        
        for q in questions[:count]:
            await context.bot.send_poll(
                chat_id=update.effective_chat.id,
                question=q['question'][:300],
                options=[opt[:100] for opt in q['options'][:4]],
                correct_option_id=q['correct_index'],
                type=Poll.QUIZ,
                is_anonymous=False
            )
            await asyncio.sleep(1.5)
        await update.message.reply_text("تم إرسال جميع الأسئلة. بالتوفيق! 🌟")
    except:
        await update.message.reply_text("عذراً، حدث خطأ في معالجة بيانات الاختبار.")

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot is running...")
    app.run_polling()
