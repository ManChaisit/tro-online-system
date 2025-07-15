import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

# --- 1. การตั้งค่า App และฐานข้อมูล ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a_very_secure_secret_key_for_stable_version'
basedir = os.path.abspath(os.path.dirname(__file__))
# ตั้งค่าให้ใช้ฐานข้อมูล SQLite สำหรับการทำงานบนเครื่อง (Local)
# เมื่อจะขึ้นออนไลน์ ค่อยเปลี่ยนไปใช้ os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'tro_system.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- 2. การนิยามโครงสร้างตารางข้อมูล (Model) ---
# เราจะนำคอลัมน์ line_user_id ออกไปก่อนเพื่อความเรียบง่าย
class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    plate = db.Column(db.String(50), nullable=False)
    service = db.Column(db.String(100))
    service_date = db.Column(db.Date)
    prb_expiry = db.Column(db.Date, nullable=True)
    ins_expiry = db.Column(db.Date, nullable=True)

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

# --- 3. ฟังก์ชันสำหรับส่งข้อมูลไปทุกหน้า (Context Processor) ---
@app.context_processor
def inject_notification_counts():
    prb_alert_count = db.session.query(Customer).filter(Customer.prb_expiry != None, Customer.prb_expiry <= datetime.now().date() + timedelta(days=30)).count()
    ins_alert_count = db.session.query(Customer).filter(Customer.ins_expiry != None, Customer.ins_expiry <= datetime.now().date() + timedelta(days=90)).count()
    return dict(prb_alert_count=prb_alert_count, ins_alert_count=ins_alert_count)

# --- 4. การกำหนดเส้นทาง (Routes) ---
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
            ins_expiry=ins_expiry
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
    expiring_list = db.session.query(Customer).filter(
        Customer.prb_expiry != None,
        Customer.prb_expiry <= thirty_days_from_now
    ).order_by(Customer.prb_expiry.asc()).all()
    return render_template('expiring_prb.html', customers=expiring_list)

@app.route('/expiring-insurance')
def expiring_insurance():
    ninety_days_from_now = datetime.now().date() + timedelta(days=90)
    expiring_list = db.session.query(Customer).filter(
        Customer.ins_expiry != None,
        Customer.ins_expiry <= ninety_days_from_now
    ).order_by(Customer.ins_expiry.asc()).all()
    return render_template('expiring_insurance.html', customers=expiring_list)

# --- 5. การรันโปรแกรม ---
if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists(os.path.join(basedir, 'tro_system.db')):
            print("Creating database...")
            db.create_all()
    app.run(debug=True, port=5001)
