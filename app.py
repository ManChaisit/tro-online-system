# Force redeploy
import os
import json
import requests
import configparser
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler

# --- เพิ่มการ import สำหรับ LINE SDK ---
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, FollowEvent

# --- 1. การตั้งค่า App และฐานข้อมูล ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a_very_secure_secret_key_for_the_final_version'
basedir = os.path.abspath(os.path.dirname(__file__))
# เชื่อมต่อกับฐานข้อมูล PostgreSQL บน Render
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
scheduler = APScheduler()

# --- 2. อ่านค่า Config และตั้งค่า LINE Bot ---
config = configparser.ConfigParser()
config.read('config.ini')
LINE_CHANNEL_ACCESS_TOKEN = config.get('LINE_API', 'Channel_Access_Token', fallback=None)
LINE_CHANNEL_SECRET = config.get('LINE_API', 'Channel_Secret', fallback=None)

# ตรวจสอบว่ามี Token และ Secret หรือไม่ก่อนสร้าง instance
if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(LINE_CHANNEL_SECRET)
else:
    print("WARNING: LINE Channel Access Token or Secret is not configured in config.ini")
    line_bot_api = None
    handler = None

# --- 3. Database Model (ไม่เปลี่ยนแปลง) ---
class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False, unique=True)
    plate = db.Column(db.String(50), nullable=False)
    service = db.Column(db.String(100))
    service_date = db.Column(db.Date)
    prb_expiry = db.Column(db.Date, nullable=True)
    ins_expiry = db.Column(db.Date, nullable=True)
    line_user_id = db.Column(db.String(100), nullable=True, unique=True)

    @property
    def prb_days_left(self):
        if self.prb_expiry: return (self.prb_expiry - datetime.now().date()).days
        return None
    @property
    def ins_days_left(self):
        if self.ins_expiry: return (self.ins_expiry - datetime.now().date()).days
        return None

# --- 4. Webhook Endpoint และ Event Handlers ---
@app.route("/callback", methods=['POST'])
def callback():
    if not handler:
        return "LINE bot not configured.", 500
        
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature.", 400
    return 'OK'

@handler.add(FollowEvent)
def handle_follow(event):
    """ทำงานเมื่อมีผู้ใช้ใหม่เพิ่มเพื่อน"""
    user_id = event.source.user_id
    print(f"New user followed: {user_id}")
    welcome_message = (
        "ขอบคุณที่เพิ่มเพื่อนกับ ตรอ. SK-Service ครับ!\n\n"
        "เพื่อรับบริการแจ้งเตือน พ.ร.บ./ประกันหมดอายุอัตโนมัติ "
        "กรุณาพิมพ์เบอร์โทรศัพท์ 10 หลักที่ท่านใช้ลงทะเบียนกับทางร้านส่งเข้ามาในแชทนี้ได้เลยครับ"
    )
    line_bot_api.reply_message(event.reply_token, TextMessage(text=welcome_message))

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """ทำงานเมื่อผู้ใช้ส่งข้อความเข้ามา"""
    user_id = event.source.user_id
    text = event.message.text.strip()
    
    if text.isdigit() and len(text) >= 9:
        customer = Customer.query.filter_by(phone=text).first()
        if customer:
            customer.line_user_id = user_id
            db.session.commit()
            reply_message = f"ลงทะเบียนสำเร็จ!\n\nบัญชี LINE ของคุณได้ผูกกับข้อมูลคุณ {customer.name} (ทะเบียน: {customer.plate}) เรียบร้อยแล้ว"
            line_bot_api.reply_message(event.reply_token, TextMessage(text=reply_message))
        else:
            reply_message = "ไม่พบข้อมูลลูกค้าสำหรับเบอร์โทรศัพท์นี้ครับ กรุณาตรวจสอบอีกครั้ง"
            line_bot_api.reply_message(event.reply_token, TextMessage(text=reply_message))
    else:
        reply_message = "กรุณาส่งเฉพาะตัวเลขเบอร์โทรศัพท์ 10 หลักเพื่อทำการลงทะเบียนนะครับ"
        line_bot_api.reply_message(event.reply_token, TextMessage(text=reply_message))

# --- 5. Scheduled Job และ LINE Pusher ---
def send_push_message(user_id, message_text):
    if not line_bot_api:
        print("Cannot send push message, LINE bot not configured.")
        return False
    try:
        line_bot_api.push_message(user_id, TextMessage(text=message_text))
        return True
    except Exception as e:
        print(f"Exception while sending to {user_id}: {e}")
        return False

def check_and_notify_customers():
    print(f"[{datetime.now()}] Running daily check for notifications...")
    with app.app_context():
        customers = Customer.query.filter(Customer.line_user_id != None, Customer.line_user_id != '').all()
        for customer in customers:
            message_to_send = None
            if customer.prb_days_left in [30, 15, 7, 1]:
                message_to_send = f"เรียนคุณ {customer.name},\n\nแจ้งเตือนจาก ตรอ. 🔔\nพ.ร.บ. ทะเบียนรถ {customer.plate} ของท่านจะหมดอายุในอีก {customer.prb_days_left} วัน (วันที่ {customer.prb_expiry.strftime('%d-%m-%Y')})\n\nสามารถเข้ามาต่อ พ.ร.บ. ล่วงหน้าที่ร้านได้เลยนะครับ"
            elif customer.ins_days_left in [90, 60, 30]:
                message_to_send = f"เรียนคุณ {customer.name},\n\nแจ้งเตือนจาก ตรอ. 🔔\nประกันภัยรถยนต์ทะเบียน {customer.plate} ของท่านจะหมดอายุในอีก {customer.ins_days_left} วัน (วันที่ {customer.ins_expiry.strftime('%d-%m-%Y')})\n\nติดต่อสอบถามเบี้ยประกันราคาพิเศษได้เลยนะครับ"
            if message_to_send:
                success = send_push_message(customer.line_user_id, message_to_send)
                status = "SUCCESS" if success else "FAILED"
                print(f"  - Notifying {customer.name}: {status}")
    print("Daily check finished.")

# --- 6. Routes and Context Processor ---
@app.context_processor
def inject_notification_counts():
    prb_alert_count = db.session.query(Customer).filter(Customer.prb_expiry != None, Customer.prb_expiry <= datetime.now().date() + timedelta(days=30)).count()
    ins_alert_count = db.session.query(Customer).filter(Customer.ins_expiry != None, Customer.ins_expiry <= datetime.now().date() + timedelta(days=90)).count()
    return dict(prb_alert_count=prb_alert_count, ins_alert_count=ins_alert_count)

# ... (All other routes like index, add, edit, delete are the same) ...
@app.route('/')
def index():
    customers = Customer.query.order_by(Customer.id.desc()).all()
    return render_template('index.html', customers=customers)
@app.route('/add', methods=['GET', 'POST'])
def add_customer():
    if request.method == 'POST':
        service_date = datetime.strptime(request.form['service_date'], '%Y-%m-%d').date() if request.form['service_date'] else None
        prb_expiry = datetime.strptime(request.form['prb_expiry'], '%Y-%m-%d').date() if request.form['prb_expiry'] else None
        ins_expiry = datetime.strptime(request.form['ins_expiry'], '%Y-%m-%d').date() if request.form['ins_expiry'] else None
        new_customer = Customer(
            name=request.form['name'], phone=request.form['phone'], plate=request.form['plate'],
            service=request.form['service'], service_date=service_date, prb_expiry=prb_expiry,
            ins_expiry=ins_expiry, line_user_id=request.form.get('line_user_id')
        )
        db.session.add(new_customer)
        db.session.commit()
        flash('เพิ่มข้อมูลลูกค้าเรียบร้อยแล้ว', 'success')
        return redirect(url_for('index'))
    return render_template('add.html')
@app.route('/edit/<int:customer_id>', methods=['GET', 'POST'])
def edit_customer(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer: return "Customer not found", 404
    if request.method == 'POST':
        customer.name = request.form['name']
        customer.phone = request.form['phone']
        customer.plate = request.form['plate']
        customer.service = request.form['service']
        customer.service_date = datetime.strptime(request.form['service_date'], '%Y-%m-%d').date() if request.form['service_date'] else None
        customer.prb_expiry = datetime.strptime(request.form['prb_expiry'], '%Y-%m-%d').date() if request.form['prb_expiry'] else None
        customer.ins_expiry = datetime.strptime(request.form['ins_expiry'], '%Y-%m-%d').date() if request.form['ins_expiry'] else None
        customer.line_user_id = request.form.get('line_user_id')
        db.session.commit()
        flash('แก้ไขข้อมูลลูกค้าเรียบร้อยแล้ว', 'success')
        return redirect(url_for('index'))
    return render_template('edit.html', customer=customer)
@app.route('/delete/<int:customer_id>', methods=['POST'])
def delete_customer(customer_id):
    customer = db.session.get(Customer, customer_id)
    if customer:
        db.session.delete(customer)
        db.session.commit()
        flash('ลบข้อมูลลูกค้าเรียบร้อยแล้ว', 'success')
    return redirect(url_for('index'))
@app.route('/expiring-prb')
def expiring_prb():
    thirty_days_from_now = datetime.now().date() + timedelta(days=30)
    expiring_list = db.session.query(Customer).filter(Customer.prb_expiry != None, Customer.prb_expiry <= thirty_days_from_now).order_by(Customer.prb_expiry.asc()).all()
    return render_template('expiring_prb.html', customers=expiring_list)
@app.route('/expiring-insurance')
def expiring_insurance():
    ninety_days_from_now = datetime.now().date() + timedelta(days=90)
    expiring_list = db.session.query(Customer).filter(Customer.ins_expiry != None, Customer.ins_expiry <= ninety_days_from_now).order_by(Customer.ins_expiry.asc()).all()
    return render_template('expiring_insurance.html', customers=expiring_list)

# --- 7. Custom CLI Command for build script ---
@app.cli.command("db-create")
def db_create():
    """คำสั่งสำหรับสร้างตารางในฐานข้อมูล"""
    db.create_all()
    print("Database tables created!")

# --- 8. Main Execution for Gunicorn on Render ---
# ตั้งค่า Scheduler ให้ทำงานเมื่อรันผ่าน Gunicorn
if __name__ != '__main__':
    scheduler.add_job(id='Daily Customer Notification', func=check_and_notify_customers, trigger='cron', hour=9, minute=0, timezone='Asia/Bangkok')
    scheduler.init_app(app)
    scheduler.start()

# ส่วนนี้จะไม่ได้ใช้เมื่อ Deploy บน Render แต่มีไว้สำหรับรันบนเครื่องตัวเอง
if __name__ == '__main__':
    app.run(debug=True, port=5001)

