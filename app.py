import os
import threading
import json
import requests
import configparser
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler

# --- 1. App Initialization and Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a_very_secure_secret_key_for_the_final_version'
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'tro_system.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
scheduler = APScheduler()

# --- 2. Database Model Definition (No changes) ---
class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    plate = db.Column(db.String(50), nullable=False)
    service = db.Column(db.String(100))
    service_date = db.Column(db.Date)
    prb_expiry = db.Column(db.Date, nullable=True)
    ins_expiry = db.Column(db.Date, nullable=True)
    line_user_id = db.Column(db.String(100), nullable=True)

    @property
    def prb_days_left(self):
        if self.prb_expiry:
            return (self.prb_expiry - datetime.now().date()).days
        return None

    @property
    def ins_days_left(self):
        if self.ins_expiry:
            return (self.ins_expiry - datetime.now().date()).days
        return None

# --- 3. LINE Messaging API Functions ---
def send_push_message(user_id, message_text):
    """ฟังก์ชันสำหรับส่งข้อความหาลูกค้าผ่าน Messaging API"""
    config = configparser.ConfigParser()
    config.read('config.ini')
    token = config.get('LINE_API', 'Channel_Access_Token', fallback=None)

    if not token or token == 'YOUR_TOKEN_HERE':
        print("ERROR: ยังไม่ได้ตั้งค่า Channel Access Token ในไฟล์ config.ini")
        return False

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message_text}]
    }
    
    try:
        response = requests.post('https://api.line.me/v2/bot/message/push', headers=headers, data=json.dumps(payload))
        if response.status_code == 200:
            return True
        else:
            print(f"Error sending to {user_id}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"Exception while sending to {user_id}: {e}")
        return False

# --- 4. Scheduled Job ---
def check_and_notify_customers():
    """
    ฟังก์ชันหลักที่จะรันอัตโนมัติทุกวัน
    เพื่อตรวจสอบและส่งแจ้งเตือนให้ลูกค้า
    """
    print(f"[{datetime.now()}] Running daily check for notifications...")
    with app.app_context():
        customers = Customer.query.filter(Customer.line_user_id != None, Customer.line_user_id != '').all()
        
        for customer in customers:
            message_to_send = None
            
            # ตรวจสอบเงื่อนไข พ.ร.บ. (แจ้งเตือนที่ 30, 15, 7, และ 1 วันก่อนหมดอายุ)
            if customer.prb_days_left in [30, 15, 7, 1]:
                message_to_send = (
                    f"เรียนคุณ {customer.name},\n\n"
                    f"แจ้งเตือนจาก ตรอ. SK-Service ครับ 🔔\n"
                    f"พ.ร.บ. ทะเบียนรถ {customer.plate} ของท่านจะหมดอายุในอีก {customer.prb_days_left} วัน "
                    f"(วันที่ {customer.prb_expiry.strftime('%d-%m-%Y')})\n\n"
                    f"สามารถเข้ามาต่อ พ.ร.บ. ล่วงหน้าที่ร้านได้เลยนะครับ"
                )
            
            # ตรวจสอบเงื่อนไข ประกัน (แจ้งเตือนที่ 90, 60, 30 วันก่อนหมดอายุ)
            elif customer.ins_days_left in [90, 60, 30]:
                 message_to_send = (
                    f"เรียนคุณ {customer.name},\n\n"
                    f"แจ้งเตือนจาก ตรอ. SK-Service ครับ 🔔\n"
                    f"ประกันภัยรถยนต์ทะเบียน {customer.plate} ของท่านจะหมดอายุในอีก {customer.ins_days_left} วัน "
                    f"(วันที่ {customer.ins_expiry.strftime('%d-%m-%Y')})\n\n"
                    f"ติดต่อสอบถามเบี้ยประกันราคาพิเศษได้ที่ร้านเลยนะครับ"
                )

            if message_to_send:
                success = send_push_message(customer.line_user_id, message_to_send)
                status = "SUCCESS" if success else "FAILED"
                print(f"  - Notifying {customer.name} ({customer.line_user_id}): {status}")
    print("Daily check finished.")


# --- 5. Routes and Context Processor (No major changes) ---
@app.context_processor
def inject_notification_counts():
    prb_alert_count = db.session.query(Customer).filter(Customer.prb_expiry != None, Customer.prb_expiry <= datetime.now().date() + timedelta(days=30)).count()
    ins_alert_count = db.session.query(Customer).filter(Customer.ins_expiry != None, Customer.ins_expiry <= datetime.now().date() + timedelta(days=90)).count()
    return dict(prb_alert_count=prb_alert_count, ins_alert_count=ins_alert_count)

# ... (All routes like index, add, edit, delete, expiring_prb, expiring_insurance are the same as before) ...
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


# --- 6. Main Execution ---
if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists(os.path.join(basedir, 'tro_system.db')):
            print("Creating database...")
            db.create_all()
    
    # ตั้งค่าให้ Scheduler รันฟังก์ชัน check_and_notify_customers ทุกวันตอน 9 โมงเช้า
    scheduler.add_job(id='Daily Customer Notification', func=check_and_notify_customers, trigger='cron', hour=9, minute=0)
    scheduler.init_app(app)
    scheduler.start()
    
    # รันเว็บเซิร์ฟเวอร์
    # app.run(debug=False, port=5001)
    app.run(debug=False)

