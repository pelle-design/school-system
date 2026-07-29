# ==================== IMPORTS ====================
import os
import re
import io
import csv
import json
import time
import secrets
import random
import string
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from markupsafe import escape
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_from_directory, jsonify, g
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from markupsafe import escape
import requests
import base64
import uuid
# ==================== APP CONFIGURATION ====================
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['UPLOAD_FOLDER'] = 'static/uploads'

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ==================== SQLITE DATABASE SETUP ====================
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'school_system.db')

def get_db():
    """Get database connection"""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.template_filter('format_date')
def format_date(value):
    if not value:
        return '-'
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d')
    return str(value)[:10] if len(str(value)) >= 10 else str(value)

@app.template_filter('format_datetime')
def format_datetime(value):
    if not value:
        return '-'
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d %H:%M')
    return str(value)[:16] if len(str(value)) >= 16 else str(value)

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    """Initialize database with all tables"""
    db = get_db()
    cursor = db.cursor()
    
    # Create tables one by one (avoiding complex SQLite issues)
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT DEFAULT '',
            role TEXT NOT NULL,
            phone TEXT,
            status INTEGER DEFAULT 1,
            child_id TEXT,
            profile_pic TEXT DEFAULT 'default_avatar.png',
            must_change_password INTEGER DEFAULT 0
        )
    ''')
    
    # Role limits table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS role_limits (
            role_name TEXT PRIMARY KEY,
            max_count INTEGER DEFAULT 1
        )
    ''')
    
    # Admission settings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admission_settings (
            id INTEGER PRIMARY KEY DEFAULT 1,
            is_open INTEGER DEFAULT 1,
            deadline DATE,
            closing_reason TEXT,
            fee_amount REAL DEFAULT 50000,
            payment_gateway TEXT DEFAULT 'MTN',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Students table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            class TEXT NOT NULL,
            photo_path TEXT DEFAULT 'default_avatar.png',
            fees_paid REAL DEFAULT 0,
            fees_balance REAL DEFAULT 0,
            fees_total REAL DEFAULT 0,
            admission_date DATE,
            parent_phone TEXT,
            date_of_birth DATE,
            age INTEGER,
            sex TEXT,
            preferred_house TEXT,
            disability TEXT,
            sports_activities TEXT,
            lin TEXT,
            admission_source TEXT DEFAULT 'local',
            admission_status TEXT DEFAULT 'approved',
            application_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            payment_status TEXT DEFAULT 'pending',
            payment_transaction_id TEXT,
            payment_date TIMESTAMP
            
        )
    ''')
    
    # Staff table (without GENERATED column)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_no TEXT UNIQUE,
            full_name TEXT NOT NULL,
            position TEXT NOT NULL,
            department TEXT,
            phone TEXT,
            email TEXT,
            nssf_number TEXT,
            tin_number TEXT,
            bank_account TEXT,
            bank_name TEXT,
            salary_basic REAL DEFAULT 0,
            salary_allowances REAL DEFAULT 0,
            salary_deductions REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Payroll table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payroll (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payroll_no TEXT UNIQUE,
            month_year DATE,
            total_amount REAL DEFAULT 0,
            approval_code TEXT,
            approval_status TEXT DEFAULT 'pending',
            approved_by TEXT,
            approved_at TIMESTAMP,
            recorded_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            headteacher_access_token TEXT,
            token_expires_at TIMESTAMP,
            management_approval_code TEXT,
            management_access_token TEXT,
            management_token_expires_at TIMESTAMP,
            management_approval_status TEXT DEFAULT 'pending',
            management_approved_by TEXT,
            management_approved_at TIMESTAMP,
            bank_authorization_token TEXT,
            bank_transaction_ref TEXT,
            bank_payment_status TEXT DEFAULT 'pending',
            bank_payment_response TEXT,
            token_resend_count INTEGER DEFAULT 0,
            last_resend_at TIMESTAMP
        )
    ''')
    
    # Salary payments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS salary_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER,
            payroll_id INTEGER,
            month_year DATE,
            basic REAL,
            allowances REAL,
            deductions REAL,
            gross_salary REAL,
            nssf_employee REAL,
            paye_tax REAL,
            net_salary REAL,
            payment_date DATE,
            payment_method TEXT,
            approval_code TEXT,
            approval_status TEXT DEFAULT 'pending',
            transaction_ref TEXT,
            recorded_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (staff_id) REFERENCES staff(id),
            FOREIGN KEY (payroll_id) REFERENCES payroll(id)
            
        )
    ''')
    
    # Marks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            subject TEXT,
            term TEXT,
            year INTEGER,
            ai1 REAL,
            ai2 REAL,
            ai3 REAL,
            ai_average REAL,
            ai_contribution REAL,
            eot_score REAL,
            total_score REAL,
            grade TEXT,
            identifier REAL,
            descriptor TEXT,
            teacher_initials TEXT,
            teacher_id INTEGER,
            paper1 REAL,
            paper2 REAL,
            points INTEGER,
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            UNIQUE(student_id, subject, term, year)
        )
    ''')
    
    # Attendance table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            date DATE,
            status TEXT,
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            UNIQUE(student_id, date)
        )
    ''')
    
    # Schedules table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            term_scope TEXT,
            content TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Grading system
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS grading_system (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            min_score REAL,
            max_score REAL,
            grade TEXT,
            descriptor TEXT
        )
    ''')
    
    # A-Level grading
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alevel_grading (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            min_score REAL,
            max_score REAL,
            grade TEXT,
            points INTEGER,
            is_subsidiary INTEGER DEFAULT 0
        )
    ''')
    
    # Identifier grading
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS identifier_grading (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            min_value REAL,
            max_value REAL,
            descriptor TEXT
        )
    ''')
    
    # Teacher comments
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teacher_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            term TEXT,
            year INTEGER,
            comment TEXT,
            headteacher_comment TEXT,
            class_teacher_comment_locked INTEGER DEFAULT 0,
            headteacher_comment_locked INTEGER DEFAULT 0,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
    ''')
    
    # Teacher class assignments
cursor.execute('''
    CREATE TABLE IF NOT EXISTS teacher_class_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER NOT NULL,

        class_name TEXT NOT NULL,

        subject TEXT,

        assignment_type TEXT NOT NULL,

        assigned_by TEXT,

        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (user_id) REFERENCES users(id),

        UNIQUE(user_id, class_name, subject, assignment_type)
    )
''')
    
    # Notifications
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_role TEXT,
            message TEXT,
            link TEXT,
            title TEXT DEFAULT 'Notification',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # School settings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS school_settings (
            id INTEGER PRIMARY KEY DEFAULT 1,
            next_term_begins DATE,
            next_term_ends DATE,
            headteacher_stamp TEXT,
            school_name TEXT DEFAULT 'YOUR SCHOOL NAME',
            school_address TEXT DEFAULT 'P.O. Box 123, Kampala, Uganda',
            school_phone TEXT DEFAULT 'Tel: +256 712 345678',
            school_email TEXT DEFAULT 'info@school.com',
            logo_url TEXT,
            nssf_employee_rate REAL DEFAULT 5.0,
            paye_rate REAL DEFAULT 10.0,
            paye_threshold REAL DEFAULT 235000
        )
    ''')
    
    # Predefined comments
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS predefined_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_type TEXT,
            comment_text TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Payments
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            amount REAL,
            payment_date DATE,
            receipt_no TEXT UNIQUE,
            payment_method TEXT,
            notes TEXT,
            recorded_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
    ''')
    
    # Budget categories
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            name TEXT,
            description TEXT,
            allocated_amount REAL,
            year INTEGER
        )
    ''')
    
    # Expenditures
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenditures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voucher_no TEXT UNIQUE,
            category_id INTEGER,
            description TEXT,
            amount REAL,
            expenditure_date DATE,
            payment_method TEXT,
            payee_name TEXT,
            payee_phone TEXT,
            status TEXT,
            recorded_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES budget_categories(id)
        )
    ''')
    
    # Inventory categories
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            warning_level INTEGER DEFAULT 10,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Inventory items
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            category_id INTEGER,
            unit TEXT DEFAULT 'pieces',
            quantity INTEGER DEFAULT 0,
            minimum_quantity INTEGER DEFAULT 10,
            maximum_quantity INTEGER DEFAULT 0,
            reorder_level INTEGER DEFAULT 5,
            location TEXT,
            supplier TEXT,
            purchase_date DATE,
            purchase_price REAL,
            current_value REAL,
            status TEXT DEFAULT 'working',
            condition_notes TEXT,
            last_maintenance DATE,
            next_maintenance DATE,
            responsible_person TEXT,
            responsible_role TEXT,
            image_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES inventory_categories(id)
        )
    ''')
    
    # Inventory transactions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            transaction_type TEXT,
            quantity INTEGER,
            unit_price REAL,
            total_amount REAL,
            transaction_date DATE,
            issued_to TEXT,
            issued_to_role TEXT,
            purpose TEXT,
            reference_no TEXT,
            recorded_by TEXT,
            approved_by TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES inventory_items(id)
        )
    ''')
    
    # Inventory alerts
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            alert_type TEXT,
            message TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES inventory_items(id)
        )
    ''')
    
    # Houses
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS houses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Sports activities
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sports_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    ''')
    
    # Payment webhooks
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payment_webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id TEXT,
            amount REAL,
            phone_number TEXT,
            student_id TEXT,
            reference TEXT,
            payment_method TEXT,
            raw_data TEXT,
            status TEXT,
            processed INTEGER DEFAULT 0,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Payment gateway config
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payment_gateway_config (
            id INTEGER PRIMARY KEY DEFAULT 1,
            gateway_name TEXT DEFAULT 'School Pay',
            api_key TEXT,
            api_secret TEXT,
            webhook_secret TEXT,
            callback_url TEXT,
            status TEXT DEFAULT 'inactive'
        )
    ''')
    
    # Bank transaction logs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bank_transaction_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payroll_id INTEGER,
            staff_id INTEGER,
            transaction_ref TEXT,
            amount REAL,
            recipient_account TEXT,
            recipient_phone TEXT,
            status TEXT,
            response TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (payroll_id) REFERENCES payroll(id),
            FOREIGN KEY (staff_id) REFERENCES staff(id)
        )
    ''')
    
    # Authorization logs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS authorization_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payroll_id INTEGER,
            action TEXT,
            performed_by TEXT,
            ip_address TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (payroll_id) REFERENCES payroll(id)
        )
    ''')
    
    # Insert default data
    cursor.execute("SELECT COUNT(*) FROM role_limits")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO role_limits (role_name, max_count) VALUES (?, ?)", 
                          [('admin', 1), ('headteacher', 1), ('management', 1), ('bursar', 1), ('dos', 1)])
    
    cursor.execute("SELECT COUNT(*) FROM admission_settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO admission_settings (id, is_open, fee_amount) VALUES (1, 1, 50000)")
    
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        from werkzeug.security import generate_password_hash
        hashed = generate_password_hash('admin123')
        cursor.execute("INSERT INTO users (username, password, full_name, role, status, phone, must_change_password) VALUES (?, ?, ?, 'admin', 1, '0700000000', 0)", 
                      ('admin', hashed, 'Administrator'))
    
    cursor.execute("SELECT COUNT(*) FROM school_settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO school_settings (id) VALUES (1)")
    
    cursor.execute("SELECT COUNT(*) FROM houses")
    if cursor.fetchone()[0] == 0:
        houses = [('AFRICA HOUSE', ''), ('EUROPE HOUSE', ''), ('NORTH AMERICA HOUSE', ''), ('SOUTH AMERICA HOUSE', ''),('ASIA HOUSE',''),('AUSTRALIA','')]
        cursor.executemany("INSERT INTO houses (name, description) VALUES (?, ?)", houses)
    
    cursor.execute("SELECT COUNT(*) FROM sports_activities")
    if cursor.fetchone()[0] == 0:
        sports = ['Football', 'Basketball', 'Netball', 'Athletics', 'Swimming', 'Tennis', 'Table Tennis', 'Volleyball', 'Chess', 'Scouts']
        cursor.executemany("INSERT INTO sports_activities (name) VALUES (?)", [(s,) for s in sports])
    
    cursor.execute("SELECT COUNT(*) FROM grading_system")
    if cursor.fetchone()[0] == 0:
        grading = [(80, 100, 'A', 'Excellent'), (70, 79, 'B', 'Very Good'), (60, 69, 'C', 'Good'), (50, 59, 'D', 'Pass'), (0, 49, 'E', 'Fail')]
        cursor.executemany("INSERT INTO grading_system (min_score, max_score, grade, descriptor) VALUES (?, ?, ?, ?)", grading)
    
    cursor.execute("SELECT COUNT(*) FROM identifier_grading")
    if cursor.fetchone()[0] == 0:
        identifier = [(2.4, 3.0, 'Excellent'), (1.8, 2.39, 'Very Good'), (1.2, 1.79, 'Good'), (0.6, 1.19, 'Satisfactory'), (0.0, 0.59, 'Needs Improvement')]
        cursor.executemany("INSERT INTO identifier_grading (min_value, max_value, descriptor) VALUES (?, ?, ?)", identifier)
    
    cursor.execute("SELECT COUNT(*) FROM alevel_grading")
    if cursor.fetchone()[0] == 0:
        alevel = [(80, 100, 'A', 5, 0), (70, 79, 'B', 4, 0), (60, 69, 'C', 3, 0), (50, 59, 'D', 2, 0), (0, 49, 'E', 1, 0)]
        cursor.executemany("INSERT INTO alevel_grading (min_score, max_score, grade, points, is_subsidiary) VALUES (?, ?, ?, ?, ?)", alevel)
    
    cursor.execute("SELECT COUNT(*) FROM inventory_categories")
    if cursor.fetchone()[0] == 0:
        categories = [
            ('Furniture', 'Desks, chairs, tables, cabinets, etc.', 5),
            ('Equipment', 'Computers, projectors, lab equipment, etc.', 3),
            ('Stationery', 'Pens, papers, notebooks, printing materials', 20),
            ('Food Items', 'Kitchen supplies, ingredients, meals', 10),
            ('Lab Equipment', 'Microscopes, beakers, test tubes, etc.', 2),
            ('Chemicals', 'Lab chemicals, cleaning agents', 5),
            ('Sports Equipment', 'Balls, nets, uniforms, etc.', 5),
            ('Electronics', 'TVs, speakers, cameras, etc.', 3),
            ('Books', 'Textbooks, library books, reference materials', 10),
            ('Maintenance', 'Tools, spare parts, repair items', 5)
        ]
        cursor.executemany("INSERT INTO inventory_categories (name, description, warning_level) VALUES (?, ?, ?)", categories)
    
    db.commit()
    print("Database initialized successfully!")

# Initialize database on startup
with app.app_context():
    if not os.path.exists(DATABASE):
        init_db()
    else:
        # Verify tables exist, create if missing
        init_db()


#csrf = CSRFProtect()
#csrf.init_app(app)

app.config.update(
    SESSION_COOKIE_SECURE=True,      # Only send over HTTPS
    SESSION_COOKIE_HTTPONLY=True,    # No JavaScript access
    SESSION_COOKIE_SAMESITE='Lax',   # CSRF protection
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2)
)

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

def validate_input(text, max_length=500, allow_html=False):
    """Validate and sanitize user input"""
    if not text:
        return ''
    
    # Limit length
    if len(text) > max_length:
        text = text[:max_length]
    
    if not allow_html:
        text = sanitize_input(text)
    
    return text
# ==================== HELPER FUNCTIONS ====================
def query_db(query, args=(), one=False):
    """Execute a query and return results"""
    cur = get_db().cursor()
    cur.execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def get_mtn_access_token():
    """Get access token from MTN MoMo API"""
    api_user = os.environ.get('MTN_API_USER', 'sandbox')
    api_key = os.environ.get('MTN_API_KEY', '')
    
    # For sandbox testing
    if api_key == '':
        return 'sandbox_token'
    
    auth_string = f"{api_user}:{api_key}"
    auth_bytes = auth_string.encode('ascii')
    auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
    
    url = "https://sandbox.mtn.com/collection/token/"
    headers = {
        'Authorization': f'Basic {auth_b64}',
        'Ocp-Apim-Subscription-Key': os.environ.get('MTN_SUBSCRIPTION_KEY', '')
    }
    
    response = requests.post(url, headers=headers)
    if response.status_code == 200:
        return response.json().get('access_token')
    return None

def request_momo_payment(phone_number, amount, reference, callback_url=None):
    """Request payment from customer's mobile money"""
    access_token = get_mtn_access_token()
    if not access_token:
        return {'success': False, 'message': 'Payment gateway unavailable'}
    
    # Format phone number (remove leading 0, add 256)
    if phone_number.startswith('0'):
        phone_number = '256' + phone_number[1:]
    elif phone_number.startswith('+'):
        phone_number = phone_number[1:]
    
    transaction_id = str(uuid.uuid4())
    url = "https://sandbox.mtn.com/collection/v1_0/requesttopay"
    
    payload = {
        "amount": str(amount),
        "currency": "UGX",
        "externalId": reference,
        "payer": {
            "partyIdType": "MSISDN",
            "partyId": phone_number
        },
        "payerMessage": "School Admission Fee",
        "payeeNote": "Payment for student admission"
    }
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'X-Reference-Id': transaction_id,
        'X-Target-Environment': 'sandbox',
        'Content-Type': 'application/json',
        'Ocp-Apim-Subscription-Key': os.environ.get('MTN_SUBSCRIPTION_KEY', '')
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 202:
            return {
                'success': True, 
                'transaction_id': transaction_id,
                'message': 'Payment request sent. Check your phone to complete payment.'
            }
        else:
            return {'success': False, 'message': f'Payment failed: {response.text}'}
    except Exception as e:
        return {'success': False, 'message': str(e)}

def check_payment_status(transaction_id):
    """Check status of a payment request"""
    access_token = get_mtn_access_token()
    if not access_token:
        return 'pending'
    
    url = f"https://sandbox.mtn.com/collection/v1_0/requesttopay/{transaction_id}"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'X-Target-Environment': 'sandbox',
        'Ocp-Apim-Subscription-Key': os.environ.get('MTN_SUBSCRIPTION_KEY', '')
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('status', 'pending').lower()
        return 'pending'
    except:
        return 'pending'

def execute_db(query, args=()):
    """Execute a query and commit"""
    db = get_db()
    cur = db.cursor()
    cur.execute(query, args)
    db.commit()
    cur.close()
    return cur.lastrowid

def sanitize_input(text):
    """Remove dangerous characters and escape HTML"""
    if not text:
        return ''
    # Remove script tags and javascript: URLs
    text = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'javascript:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'on\w+\s*=', '', text, flags=re.IGNORECASE)
    # Escape HTML entities
    return escape(text)

def dict_factory(cursor, row):
    """Convert row to dictionary"""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_db_dict():
    """Get database connection with dict factory"""
    db = get_db()
    db.row_factory = dict_factory
    return db

def allowed_file(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set

def check_permission(allowed_roles):
    """Check if logged-in user has one of the allowed roles"""
    if 'role' not in session:
        return False
    return session.get('role') in allowed_roles

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not check_permission(['admin']):
            abort(403)
        return f(*args, **kwargs)
    return decorated

def get_photo_url(photo_path):
    if photo_path and photo_path != 'default_avatar.png':
        return url_for('static', filename='uploads/' + photo_path)
    return url_for('static', filename='uploads/default_avatar.png')

def validate_and_format_phone(phone):
    if not phone:
        return None
    cleaned = re.sub(r'[^0-9+]', '', phone.strip())
    if cleaned.startswith('+'):
        digits = re.sub(r'\D', '', cleaned)
        if len(digits) >= 9:
            return cleaned
        return None
    digits = re.sub(r'\D', '', cleaned)
    if len(digits) == 9:
        return f'+256{digits}'
    elif len(digits) == 12 and digits.startswith('256'):
        return f'+{digits}'
    return None

def generate_unique_number(prefix, table_name, column_name, year_format=False):
    db = get_db_dict()
    cur = db.cursor()
    
    # Fix: Use the correct column for ordering based on table
    if table_name == 'students':
        cur.execute(f"SELECT {column_name} FROM {table_name} ORDER BY {column_name} DESC LIMIT 1")
    else:
        cur.execute(f"SELECT {column_name} FROM {table_name} ORDER BY id DESC LIMIT 1")
    
    last = cur.fetchone()
    cur.close()
    
    if year_format:
        current_year = datetime.now().year
        if last:
            last_value = last[column_name] if isinstance(last, dict) else last[0]
            if last_value and str(current_year) in str(last_value):
                try:
                    last_num = int(str(last_value).split('-')[-1])
                    new_num = last_num + 1
                except:
                    new_num = 1
            else:
                new_num = 1
        else:
            new_num = 1
        return f"{prefix}-{current_year}-{new_num:04d}"
    else:
        if last:
            last_value = last[column_name] if isinstance(last, dict) else last[0]
            try:
                last_num = int(str(last_value).split('-')[-1])
                new_num = last_num + 1
            except:
                new_num = 1
        else:
            new_num = 1
        return f"{prefix}-{new_num:04d}"

def generate_approval_code():
    return ''.join(random.choices('0123456789', k=6))

def generate_secure_token(hours=2):
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=hours)
    return token, expires_at

def send_sms(phone_number, message):
    print(f"[SMS] To: {phone_number} | {message}")
    return True

def send_email(recipient, subject, html_content):
    print(f"[EMAIL] To: {recipient} | Subject: {subject}")
    return True

def calculate_age(birth_date):
    today = datetime.now().date()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

# ==================== NOTIFICATION FUNCTIONS ====================

def add_notification(user_role, message, link=None, title=None):
    """Add a notification for a specific user role"""
    if title is None:
        title = "New Notification"
    
    execute_db("""
        INSERT INTO notifications (user_role, title, message, link, is_read, created_at) 
        VALUES (?, ?, ?, ?, 0, ?)
    """, (user_role, title, message, link, datetime.now()))

def get_notification_count(user_role):
    """Get count of unread notifications for a user role"""
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM notifications WHERE user_role = ? AND is_read = 0", (user_role,))
    result = cur.fetchone()
    cur.close()
    return result[0] if result else 0

def mark_all_notifications_read(user_role):
    """Mark all notifications as read for a user role"""
    execute_db("UPDATE notifications SET is_read = 1 WHERE user_role = ?", (user_role,))


# ==================== NOTIFICATION API ENDPOINTS (Works for ALL ROLES) ====================

@app.route('/get_notifications')
def get_notifications():
    """Generic endpoint for all roles to get notifications"""
    if not session.get('user_id'):
        return jsonify([])
    
    user_role = session.get('role')
    
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("""
        SELECT id, title, message, link, is_read, created_at 
        FROM notifications 
        WHERE user_role = ?
        ORDER BY created_at DESC 
        LIMIT 30
    """, (user_role,))
    
    notifications = cur.fetchall()
    cur.close()
    
    result = []
    for n in notifications:
        result.append({
            'id': n['id'],
            'title': n.get('title', 'Notification'),
            'message': n['message'],
            'link': n.get('link', ''),
            'is_read': n['is_read'],
            'created_at': n['created_at'][:19] if n['created_at'] else ''
        })
    
    return jsonify(result)


@app.route('/mark_notifications_read', methods=['POST'])
def mark_notifications_read():
    """Generic endpoint for all roles to mark notifications as read"""
    if not session.get('user_id'):
        return jsonify({'error': 'Not logged in'})
    
    user_role = session.get('role')
    
    try:
        execute_db("UPDATE notifications SET is_read = 1 WHERE user_role = ?", (user_role,))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ==================== DOS SPECIFIC ENDPOINTS (Keep for backward compatibility) ====================

@app.route('/dos/get_notifications')
def dos_get_notifications():
    """DOS specific endpoint - redirects to generic"""
    return get_notifications()


@app.route('/dos/mark_notifications_read', methods=['POST'])
def dos_mark_notifications_read():
    """DOS specific endpoint - redirects to generic"""
    return mark_notifications_read()


# ==================== HEADTEACHER SPECIFIC ENDPOINTS ====================

@app.route('/headteacher/get_notifications')
def headteacher_get_notifications():
    """Headteacher specific endpoint"""
    return get_notifications()


@app.route('/headteacher/mark_notifications_read', methods=['POST'])
def headteacher_mark_notifications_read():
    """Headteacher specific endpoint"""
    return mark_notifications_read()


# ==================== BURSAR SPECIFIC ENDPOINTS ====================

@app.route('/bursar/get_notifications')
def bursar_get_notifications():
    """Bursar specific endpoint"""
    return get_notifications()


@app.route('/bursar/mark_notifications_read', methods=['POST'])
def bursar_mark_notifications_read():
    """Bursar specific endpoint"""
    return mark_notifications_read()


# ==================== MANAGEMENT SPECIFIC ENDPOINTS ====================

@app.route('/management/get_notifications')
def management_get_notifications():
    """Management specific endpoint"""
    return get_notifications()


@app.route('/management/mark_notifications_read', methods=['POST'])
def management_mark_notifications_read():
    """Management specific endpoint"""
    return mark_notifications_read()


# ==================== STORES KEEPER SPECIFIC ENDPOINTS ====================

@app.route('/stores/get_notifications')
def stores_get_notifications():
    """Stores Keeper specific endpoint"""
    return get_notifications()


@app.route('/stores/mark_notifications_read', methods=['POST'])
def stores_mark_notifications_read():
    """Stores Keeper specific endpoint"""
    return mark_notifications_read()
# ==================== GRADING HELPERS ====================
def get_grade_and_descriptor(percentage):
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT grade, descriptor FROM grading_system WHERE ? BETWEEN min_score AND max_score", (percentage,))
    result = cur.fetchone()
    cur.close()
    
    if result:
        # Handle both dict and tuple
        if isinstance(result, dict):
            return result.get('grade', 'O'), result.get('descriptor', 'Fail')
        else:
            return result[0], result[1]
    
    return 'O', 'Fail'

def get_descriptor_by_identifier(identifier):
    cur = get_db().cursor()
    cur.execute("SELECT descriptor FROM identifier_grading WHERE ? BETWEEN min_value AND max_value LIMIT 1", (identifier,))
    result = cur.fetchone()
    cur.close()
    if result:
        if isinstance(result, dict):
            return result.get('descriptor', 'No descriptor defined')
        else:
            return result[0]
    return 'No descriptor defined'

def get_alevel_grade_and_points(score, is_subsidiary=False):
    if score is None:
        return 'N/A', 0
    if is_subsidiary:
        points = 1 if score >= 50 else 0
        grade = 'Pass' if points == 1 else 'Fail'
        return grade, points
    cur = get_db().cursor()
    cur.execute("SELECT grade, points FROM alevel_grading WHERE ? BETWEEN min_score AND max_score AND is_subsidiary=0 LIMIT 1", (score,))
    result = cur.fetchone()
    cur.close()
    if result:
        return result[0], result[1]
    return 'E', 1

def get_predefined_comments(comment_type):
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT id, comment_text FROM predefined_comments WHERE comment_type=? AND is_active=1 ORDER BY id", (comment_type,))
    comments = cur.fetchall()
    cur.close()
    return comments

# ==================== TEACHER ASSIGNMENT HELPERS ====================
def get_user_assignments(user_id=None):
    if user_id is None:
        user_id = session.get('user_id')
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM teacher_class_assignments WHERE user_id = ? ORDER BY assignment_type, class_name, subject", (user_id,))
    assignments = cur.fetchall()
    cur.close()
    return assignments

def get_user_classes(user_id=None, assignment_type=None):
    if user_id is None:
        user_id = session.get('user_id')
    db = get_db_dict()
    cur = db.cursor()
    if assignment_type:
        cur.execute("SELECT DISTINCT class_name FROM teacher_class_assignments WHERE user_id = ? AND assignment_type = ? ORDER BY class_name", 
                    (user_id, assignment_type))
    else:
        cur.execute("SELECT DISTINCT class_name FROM teacher_class_assignments WHERE user_id = ? ORDER BY class_name", (user_id,))
    rows = cur.fetchall()
    # Fix: Handle dictionary results
    classes = [row['class_name'] if isinstance(row, dict) else row[0] for row in rows]
    cur.close()
    return classes

# ==================== MARKS PROCESSING ====================
def process_marks_upload(file, subject, term, year, assigned_class, teacher_id, level='olevel', is_subsidiary=False):
    """Process marks upload using openpyxl (no pandas needed)"""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(file, data_only=True)
        sheet = wb.active
    except Exception as e:
        flash(f'Error reading Excel file: {str(e)}', 'danger')
        return 0
    
    # Helper function to get value from fetchone result
    def get_class_from_result(res):
        if not res:
            return None
        if isinstance(res, dict):
            return res.get('class')
        return res[0]
    
    # Get headers from first row
    headers = []
    for cell in sheet[1]:
        if cell.value:
            headers.append(str(cell.value).strip().lower())
        else:
            headers.append('')
    
    # Find column indices
    student_id_col = None
    subject_col = None
    eot_col = None
    teacher_init_col = None
    ai_columns = []
    paper1_col = None
    paper2_col = None
    
    for idx, h in enumerate(headers):
        if h == 'student_id':
            student_id_col = idx
        elif h == 'subject':
            subject_col = idx
        elif h == 'eot_score':
            eot_col = idx
        elif h == 'teacher_initials':
            teacher_init_col = idx
        elif h == 'paper1':
            paper1_col = idx
        elif h == 'paper2':
            paper2_col = idx
        elif h and h.startswith('ai') and len(h) > 2 and h[2:].isdigit():
            ai_columns.append((idx, h))
    
    if student_id_col is None:
        flash('Missing student_id column', 'danger')
        return 0
    
    count = 0
    
    if level == 'alevel':
        # A-Level processing
        if paper1_col is None or paper2_col is None:
            flash('Missing paper1 or paper2 columns', 'danger')
            return 0
        
        for row_idx in range(2, sheet.max_row + 1):
            student_id = sheet.cell(row=row_idx, column=student_id_col + 1).value
            if not student_id:
                continue
            student_id = str(student_id).strip()
            
            # Check if student belongs to assigned class
            cur = get_db().cursor()
            cur.execute("SELECT class FROM students WHERE student_id=?", (student_id,))
            res = cur.fetchone()
            cur.close()
            
            student_class = get_class_from_result(res)
            if not student_class or student_class != assigned_class:
                continue
            
            paper1_val = sheet.cell(row=row_idx, column=paper1_col + 1).value
            paper2_val = sheet.cell(row=row_idx, column=paper2_col + 1).value
            
            paper1 = float(paper1_val) if paper1_val is not None else None
            paper2 = float(paper2_val) if paper2_val is not None else None
            
            available = [s for s in [paper1, paper2] if s is not None]
            if not available:
                continue
            
            avg_score = sum(available) / len(available)
            grade, points = get_alevel_grade_and_points(avg_score, is_subsidiary)
            
            teacher_init = ''
            if teacher_init_col is not None:
                init_val = sheet.cell(row=row_idx, column=teacher_init_col + 1).value
                teacher_init = str(init_val).strip() if init_val else ''
            
            execute_db("""INSERT INTO marks (student_id, subject, term, year, paper1, paper2, total_score, grade, points, teacher_initials, teacher_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(student_id, subject, term, year) DO UPDATE SET 
                           paper1=excluded.paper1, paper2=excluded.paper2, total_score=excluded.total_score, 
                           grade=excluded.grade, points=excluded.points, teacher_initials=excluded.teacher_initials""",
                        (student_id, subject, term, year, paper1, paper2, avg_score, grade, points, teacher_init, teacher_id))
            count += 1
    else:
        # O-Level processing
        for row_idx in range(2, sheet.max_row + 1):
            student_id = sheet.cell(row=row_idx, column=student_id_col + 1).value
            if not student_id:
                continue
            student_id = str(student_id).strip()
            
            # Check if student belongs to assigned class
            cur = get_db().cursor()
            cur.execute("SELECT class FROM students WHERE student_id=?", (student_id,))
            res = cur.fetchone()
            cur.close()
            
            student_class = get_class_from_result(res)
            if not student_class or student_class != assigned_class:
                continue
            
            # Collect AI scores
            ai_scores = []
            for col_idx, col_name in ai_columns:
                val = sheet.cell(row=row_idx, column=col_idx + 1).value
                if val is not None:
                    try:
                        score = float(val)
                        if 0 <= score <= 3:
                            ai_scores.append(score)
                    except:
                        pass
            
            # Get EOT score
            eot = 0
            if eot_col is not None:
                eot_val = sheet.cell(row=row_idx, column=eot_col + 1).value
                if eot_val is not None:
                    try:
                        eot = float(eot_val)
                    except:
                        eot = 0
            
            # Get teacher initials
            teacher_init = ''
            if teacher_init_col is not None:
                init_val = sheet.cell(row=row_idx, column=teacher_init_col + 1).value
                teacher_init = str(init_val).strip() if init_val else ''
            
            if not ai_scores:
                continue
            
            ai_average = sum(ai_scores) / len(ai_scores)
            ai_contribution = (ai_average / 3.0) * 20
            eot_contribution = (eot / 100.0) * 80
            total_score = ai_contribution + eot_contribution
            grade, _ = get_grade_and_descriptor(total_score)
            identifier = (total_score / 100.0) * 3
            descriptor = get_descriptor_by_identifier(identifier)
            
            ai_values = [0] * 6
            for i, (col_idx, col_name) in enumerate(ai_columns[:6]):
                if i < len(ai_scores):
                    ai_values[i] = ai_scores[i]
            
            execute_db("""INSERT INTO marks (student_id, subject, term, year, ai1, ai2, ai3, ai_average, ai_contribution, eot_score, total_score, grade, identifier, descriptor, teacher_initials, teacher_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(student_id, subject, term, year) DO UPDATE SET 
                           ai1=excluded.ai1, ai2=excluded.ai2, ai3=excluded.ai3, 
                           ai_average=excluded.ai_average, ai_contribution=excluded.ai_contribution, eot_score=excluded.eot_score,
                           total_score=excluded.total_score, grade=excluded.grade, identifier=excluded.identifier,
                           descriptor=excluded.descriptor, teacher_initials=excluded.teacher_initials""",
                        (student_id, subject, term, year, ai_values[0], ai_values[1], ai_values[2],
                         ai_average, ai_contribution, eot, total_score, grade, identifier, descriptor, teacher_init, teacher_id))
            count += 1
    
    return count

# ==================== BANK PAYMENT PROCESSING ====================
def process_bank_payment(payroll):
    import random
    results = {'success': False, 'token': None, 'reference': None, 'error': None}
    if random.random() > 0.1:
        results['success'] = True
        results['token'] = f"TOKEN-{payroll['payroll_no']}"
        results['reference'] = f"REF-{payroll['payroll_no']}-{int(time.time())}"
    else:
        results['error'] = "Bank API temporarily unavailable"
    return results

# ==================== CONTEXT PROCESSORS ====================
@app.context_processor
def inject_now():
    return {'datetime': datetime}
    
@app.context_processor
def inject_notifications():
    if 'user_id' in session:
        role = session.get('role')
        if role in ['headteacher', 'bursar', 'management', 'admin']:
            try:
                db = get_db()
                cur = db.cursor()
                cur.execute("SELECT COUNT(*) FROM notifications WHERE user_role = ? AND is_read = 0", (role,))
                count_row = cur.fetchone()
                notification_count = count_row[0] if count_row else 0
                
                cur.execute("SELECT * FROM notifications WHERE user_role = ? AND is_read = 0 ORDER BY created_at DESC LIMIT 5", (role,))
                rows = cur.fetchall()
                notifications = []
                for row in rows:
                    notifications.append({
                        'id': row[0],
                        'user_role': row[1],
                        'message': row[2],
                        'link': row[3],
                        'is_read': row[4],
                        'created_at': row[5]
                    })
                cur.close()
                return {'notification_count': notification_count, 'notifications': notifications}
            except:
                return {'notification_count': 0, 'notifications': []}
    return {'notification_count': 0, 'notifications': []}

# ==================== TEMPLATE FILTERS ====================
@app.template_filter('currency')
def currency_filter(value):
    return "{:,.2f}".format(float(value)) if value else '0.00'

@app.template_filter('word_format')
def word_format(value):
    words = {1: 'One', 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight', 9: 'Nine', 10: 'Ten'}
    return words.get(int(value), str(value)) if value else 'Zero'

# ==================== AUTHENTICATION ROUTES ====================
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.after_request
def add_security_headers(response):
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; font-src 'self' https://cdnjs.cloudflare.com; img-src 'self' data:;"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = sanitize_input(request.form['username'].strip())
        password = request.form['password'].strip()
        
        cur = get_db().cursor()
        cur.execute("SELECT id, username, role, status, phone, must_change_password, password FROM users WHERE username=?", (username,))
        user = cur.fetchone()
        cur.close()
        
        if user and user[3] == 1:
            stored_password = user[6]
            if stored_password == password or check_password_hash(stored_password, password):
                session['user_id'] = user[0]
                session['username'] = user[1]
                session['role'] = user[2]  # Make sure role is stored
                session['phone'] = user[4]
                
                if user[5] == 1:
                    flash('Please change your password.', 'warning')
                    return redirect(url_for('change_password'))
                
                flash(f'Welcome {username}!', 'success')
                return redirect(url_for('dashboard'))
        
        flash('Invalid credentials.', 'danger')
        return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        new_pass = request.form['new_password'].strip()
        confirm = request.form['confirm_password'].strip()
        if new_pass != confirm:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('change_password'))
        
        # Hash the new password
        hashed_password = generate_password_hash(new_pass)
        execute_db("UPDATE users SET password=?, must_change_password=0 WHERE id=?", (hashed_password, session['user_id']))
        flash('Password changed successfully!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('change_password.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form['username'].strip()
        phone = validate_and_format_phone(request.form['phone'].strip())
        if not phone:
            flash('Invalid phone number format.', 'danger')
            return redirect(url_for('forgot_password'))
        new_pass = request.form['new_password'].strip()
        confirm = request.form['confirm_password'].strip()
        if new_pass != confirm:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('forgot_password'))
        
        cur = get_db().cursor()
        cur.execute("SELECT id FROM users WHERE username=? AND phone=?", (username, phone))
        user = cur.fetchone()
        cur.close()
        
        if user:
            hashed_password = generate_password_hash(new_pass)
            execute_db("UPDATE users SET password=?, must_change_password=0 WHERE id=?", (hashed_password, user[0]))
            flash('Password reset successfully.', 'success')
        else:
            flash('Username and phone number do not match.', 'danger')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'info')
    return redirect(url_for('login'))

# ==================== DASHBOARD ROUTES ====================
@app.route('/dashboard')
@login_required
def dashboard():
    role = session.get('role')
    
    if role == 'admin':
        search = request.args.get('search', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = 10
        cur = get_db().cursor()
        if search:
            cur.execute("SELECT COUNT(*) FROM users WHERE username LIKE ?", (f'%{search}%',))
        else:
            cur.execute("SELECT COUNT(*) FROM users")
        total = cur.fetchone()[0]
        total_pages = (total + per_page - 1) // per_page
        offset = (page - 1) * per_page
        if search:
            cur.execute("SELECT id, username, role, phone, status, profile_pic FROM users WHERE username LIKE ? ORDER BY id LIMIT ? OFFSET ?", 
                        (f'%{search}%', per_page, offset))
        else:
            cur.execute("SELECT id, username, role, phone, status, profile_pic FROM users ORDER BY id LIMIT ? OFFSET ?", 
                        (per_page, offset))
        users = cur.fetchall()
        cur.close()
        return render_template('dashboard.html', role=role, data={'users': users, 'total_pages': total_pages, 'current_page': page}, search=search)
    elif role == 'bursar':
        return redirect(url_for('bursar_dashboard'))
    else:
        return render_template('dashboard.html', role=role)

@app.route('/notifications')
@login_required
def view_all_notifications():
    role = session.get('role')
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM notifications WHERE user_role = ? ORDER BY created_at DESC", (role,))
    notifications = cur.fetchall()
    cur.close()
    return render_template('notifications.html', notifications=notifications)

@app.route('/notification/mark_read/<int:notification_id>')
@login_required
def mark_notification_read_route(notification_id):
    mark_notification_read(notification_id)
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/notification/mark_all_read')
@login_required
def mark_all_notifications_read_route():
    role = session.get('role')
    mark_all_notifications_read(role)
    flash('All notifications marked as read.', 'success')
    return redirect(request.referrer or url_for('dashboard'))

# ==================== ADMIN ROUTES ====================
@app.route('/admin/add_user', methods=['POST'])
@admin_required
def add_user():
    full_name = sanitize_input(request.form['full_name'].strip())
    username = sanitize_input(request.form['username'].strip())
    password = request.form['password'].strip()
    role = request.form['role'].strip()
    phone_raw = request.form.get('phone', '').strip()
    phone = validate_and_format_phone(phone_raw) if phone_raw else None
    child_id = request.form.get('child_id', '').strip() or None
    
    # Check if username already exists
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cur.fetchone():
        flash(f'Username "{username}" already exists! Please choose a different username.', 'danger')
        cur.close()
        return redirect(url_for('dashboard'))
    
    # Check role limits
    cur.execute("SELECT max_count FROM role_limits WHERE role_name = ?", (role,))
    limit = cur.fetchone()
    
    if limit:
        limit_value = limit[0] if isinstance(limit, (list, tuple)) else limit.get('max_count', 0)
        cur.execute("SELECT COUNT(*) as count FROM users WHERE role = ?", (role,))
        count_result = cur.fetchone()
        count = count_result[0] if isinstance(count_result, (list, tuple)) else count_result.get('count', 0)
        if count >= limit_value:
            flash(f'Cannot add. Only {limit_value} {role} allowed in the system.', 'danger')
            cur.close()
            return redirect(url_for('dashboard'))
    cur.close()
    
    hashed_password = generate_password_hash(password)
    
    try:
        execute_db("""INSERT INTO users (username, password, full_name, role, phone, status, child_id, profile_pic, must_change_password) 
                      VALUES (?, ?, ?, ?, ?, 1, ?, 'default_avatar.png', 1)""",
                   (username, hashed_password, full_name, role, phone, child_id))
        flash(f'User {full_name} ({username}) added. Password: {password}', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/admin/edit_user/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    if request.method == 'POST':
        full_name = sanitize_input(request.form.get('full_name', '').strip())
        username = request.form.get('username', '').strip()
        role = request.form.get('role', '').strip()
        phone = request.form.get('phone', '').strip()
        child_id = request.form.get('child_id', '').strip() or None
        file = request.files.get('profile_pic')
        
        profile_pic = None
        if file and file.filename and allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"user_{user_id}.{ext}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            profile_pic = filename
        
        try:
            if profile_pic:
                execute_db("UPDATE users SET username=?, full_name=?, role=?, phone=?, child_id=?, profile_pic=? WHERE id=?", 
                           (username, full_name, role, phone, child_id, profile_pic, user_id))
            else:
                execute_db("UPDATE users SET username=?, full_name=?, role=?, phone=?, child_id=? WHERE id=?", 
                           (username, full_name, role, phone, child_id, user_id))
            flash('User updated successfully.', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))
    
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT id, username, full_name, role, phone, child_id, profile_pic FROM users WHERE id=?", (user_id,))
    user = cur.fetchone()
    cur.close()
    
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('dashboard'))
    
    return render_template('edit_user.html', user=user)

@app.route('/admin/toggle_user/<int:user_id>')
@admin_required
def toggle_user(user_id):
    if user_id == session.get('user_id'):
        flash('Cannot toggle your own account.', 'warning')
        return redirect(url_for('dashboard'))
    cur = get_db().cursor()
    cur.execute("UPDATE users SET status = 1 - status WHERE id=?", (user_id,))
    cur.close()
    get_db().commit()
    flash('Status toggled.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/admin/delete_user/<int:user_id>')
@admin_required
def delete_user(user_id):
    if user_id == session.get('user_id'):
        flash('Cannot delete your own account.', 'warning')
        return redirect(url_for('dashboard'))
    execute_db("DELETE FROM users WHERE id=?", (user_id,))
    flash('User deleted.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/admin/role_counts')
def admin_role_counts():
    if not check_permission(['admin']):
        abort(403)
    
    cur = get_db().cursor()
    cur.execute("""
        SELECT role, COUNT(*) as count, (SELECT max_count FROM role_limits WHERE role_name = users.role) as max_count
        FROM users 
        GROUP BY role
    """)
    counts = cur.fetchall()
    cur.close()
    
    return render_template('admin/role_counts.html', counts=counts)

@app.route('/admin/school_settings', methods=['GET', 'POST'])
def school_settings():
    if not check_permission(['admin', 'headteacher']):
        abort(403)
    
    if request.method == 'POST':
        begins = request.form['next_term_begins']
        ends = request.form['next_term_ends']
        
        stamp_file = request.files.get('stamp')
        stamp_filename = None
        if stamp_file and stamp_file.filename and allowed_file(stamp_file.filename, ALLOWED_IMAGE_EXTENSIONS):
            stamp_filename = f"stamp_{int(datetime.now().timestamp())}.{stamp_file.filename.rsplit('.', 1)[1].lower()}"
            stamp_file.save(os.path.join(app.config['UPLOAD_FOLDER'], stamp_filename))
        
        school_name = request.form.get('school_name', 'YOUR SCHOOL NAME')
        school_address = request.form.get('school_address', 'P.O. Box 123, Kampala, Uganda')
        school_phone = request.form.get('school_phone', 'Tel: +256 712 345678')
        school_email = request.form.get('school_email', 'Email: info@school.com')
        
        logo_file = request.files.get('logo')
        logo_filename = None
        if logo_file and logo_file.filename and allowed_file(logo_file.filename, ALLOWED_IMAGE_EXTENSIONS):
            logo_filename = f"logo_{int(datetime.now().timestamp())}.{logo_file.filename.rsplit('.', 1)[1].lower()}"
            logo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], logo_filename))
        
        nssf_employee_rate = float(request.form.get('nssf_employee_rate', 5.0))
        paye_rate = float(request.form.get('paye_rate', 10.0))
        paye_threshold = float(request.form.get('paye_threshold', 235000))
        
        # Update school settings
        cur = get_db().cursor()
        cur.execute("UPDATE school_settings SET next_term_begins=?, next_term_ends=?, school_name=?, school_address=?, school_phone=?, school_email=?, nssf_employee_rate=?, paye_rate=?, paye_threshold=? WHERE id=1",
                    (begins, ends, school_name, school_address, school_phone, school_email, nssf_employee_rate, paye_rate, paye_threshold))
        if stamp_filename:
            cur.execute("UPDATE school_settings SET headteacher_stamp=? WHERE id=1", (stamp_filename,))
        if logo_filename:
            cur.execute("UPDATE school_settings SET logo_url=? WHERE id=1", (logo_filename,))
        get_db().commit()
        cur.close()
        flash('School settings updated successfully.', 'success')
    
    cur = get_db().cursor()
    cur.execute("SELECT next_term_begins, next_term_ends, headteacher_stamp, school_name, school_address, school_phone, school_email, logo_url, nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
    settings = cur.fetchone()
    cur.close()
    
    nssf_rate = settings[8] if settings and len(settings) > 8 else 5.0
    paye_rate_val = settings[9] if settings and len(settings) > 9 else 10.0
    paye_threshold_val = settings[10] if settings and len(settings) > 10 else 235000
    
    return render_template('admin/school_settings.html', settings=settings, nssf_rate=nssf_rate, paye_rate=paye_rate_val, paye_threshold=paye_threshold_val)

@app.route('/admin/nssf_paye_settings', methods=['GET', 'POST'])
def nssf_paye_settings():
    if not check_permission(['admin', 'bursar']):
        abort(403)
    
    if request.method == 'POST':
        nssf_employee = float(request.form['nssf_employee_rate'])
        paye_rate = float(request.form['paye_rate'])
        paye_threshold = float(request.form['paye_threshold'])
        execute_db("UPDATE school_settings SET nssf_employee_rate=?, paye_rate=?, paye_threshold=? WHERE id=1", 
                   (nssf_employee, paye_rate, paye_threshold))
        flash('NSSF and PAYE settings updated successfully.', 'success')
    
    cur = get_db().cursor()
    cur.execute("SELECT nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
    settings = cur.fetchone()
    cur.close()
    return render_template('admin/nssf_paye_settings.html', settings=settings)


# ==================== ADMISSION PORTAL ROUTES ====================
def extract_results_from_pdf(file_path):
    return {'english': 75, 'math': 68, 'science': 82, 'social_studies': 70, 'average': 73.75, 'qualifies': True}

def determine_admission_worth(results):
    min_average = 60
    min_english = 50
    min_math = 50
    qualifies = (results.get('average', 0) >= min_average and results.get('english', 0) >= min_english and results.get('math', 0) >= min_math)
    return {'qualifies': qualifies, 'average': results.get('average', 0), 'message': 'Congratulations! You qualify.' if qualifies else 'Sorry, you do not meet requirements.'}

def generate_admission_letter(student):
    return f"""<!DOCTYPE html><html><head><title>Admission Letter</title></head><body><h2>Admission Letter</h2><p>Dear {student['full_name']},</p><p>You have been admitted.</p></body></html>"""

@app.route('/admissions', methods=['GET', 'POST'])
def admissions_portal():
    # Check if admissions are open
    cur = get_db().cursor()
    cur.execute("SELECT is_open, deadline, closing_reason FROM admission_settings WHERE id=1")
    settings = cur.fetchone()
    cur.close()
    
    is_open = settings[0] if settings else 1
    deadline = settings[1] if settings else None
    closing_reason = settings[2] if settings else ''
    
    if not is_open:
        return render_template('admissions/closed.html', 
                              reason=closing_reason, 
                              deadline=deadline)
    
    if request.method == 'POST':
        full_name = request.form['full_name']
        date_of_birth = request.form['date_of_birth']
        sex = request.form['sex']
        preferred_house = request.form['preferred_house']
        disability = request.form.get('disability', '')
        sports_activities = request.form.getlist('sports_activities')
        lin = request.form['lin']
        phone = request.form['phone']
        email = request.form['email']
        
        birth_date = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
        age = calculate_age(birth_date)
        
        photo = request.files.get('photo')
        photo_filename = None
        if photo and photo.filename:
            ext = photo.filename.rsplit('.', 1)[1].lower()
            student_id_temp = f"TEMP-{int(datetime.now().timestamp())}"
            photo_filename = f"{student_id_temp}.{ext}"
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], photo_filename))
        
        results_file = request.files.get('results_pdf')
        results_data = None
        if results_file and results_file.filename:
            filename = secure_filename(f"results_{int(datetime.now().timestamp())}_{results_file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            results_file.save(filepath)
            results_data = extract_results_from_pdf(filepath)
        
        qualification = determine_admission_worth(results_data) if results_data else {'qualifies': False, 'message': 'Results not uploaded'}
        
        session['admission_data'] = {
            'full_name': full_name, 'date_of_birth': date_of_birth, 'age': age, 'sex': sex,
            'preferred_house': preferred_house, 'disability': disability,
            'sports_activities': ','.join(sports_activities), 'lin': lin, 'phone': phone,
            'email': email, 'photo_filename': photo_filename, 'qualification': qualification,
            'results_data': results_data
        }
        
        if qualification['qualifies']:
            return redirect(url_for('admission_payment'))
        else:
            flash(qualification['message'], 'danger')
            return redirect(url_for('admissions_portal'))
    
    # GET request - show form
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT name FROM houses ORDER BY name")
    houses = cur.fetchall()
    cur.execute("SELECT name FROM sports_activities ORDER BY name")
    sports = cur.fetchall()
    cur.close()
    return render_template('admissions/apply.html', houses=houses, sports=sports)

@app.route('/admissions/payment', methods=['GET', 'POST'])
def admission_payment():
    admission_data = session.get('admission_data')
    if not admission_data:
        flash('Please complete the application form first.', 'warning')
        return redirect(url_for('admissions_portal'))
    
    # Get admission fee from settings
    cur = get_db().cursor()
    cur.execute("SELECT is_open, fee_amount FROM admission_settings WHERE id=1")
    settings = cur.fetchone()
    cur.close()
    
    if not settings or settings[0] == 0:
        flash('Online admissions are currently closed.', 'danger')
        return redirect(url_for('admissions_portal'))
    
    amount = settings[1] if settings else 50000
    
    if request.method == 'POST':
        phone_number = request.form['phone_number']
        transaction_ref = f"ADM-{int(datetime.now().timestamp())}"
        
        # Request payment via mobile money
        result = request_momo_payment(phone_number, amount, transaction_ref)
        
        if result['success']:
            # Store pending payment in session
            session['payment_data'] = {
                'transaction_id': result['transaction_id'],
                'amount': amount,
                'phone': phone_number,
                'reference': transaction_ref
            }
            
            # Store admission data temporarily
            temp_student_id = f"TEMP-{int(datetime.now().timestamp())}"
            execute_db("""INSERT INTO students (student_id, full_name, class, parent_phone, date_of_birth, age, sex, 
                           preferred_house, disability, sports_activities, lin, admission_source, admission_status, 
                           payment_status, payment_transaction_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'online', 'pending', 'pending', ?)""",
                       (temp_student_id, admission_data['full_name'], 'Pending', admission_data.get('phone'),
                        admission_data.get('date_of_birth'), admission_data.get('age'), admission_data.get('sex'),
                        admission_data.get('preferred_house'), admission_data.get('disability'),
                        admission_data.get('sports_activities'), admission_data.get('lin'),
                        result['transaction_id']))
            
            flash('Payment request sent! Please check your phone and complete the payment.', 'info')
            return redirect(url_for('admission_payment_status', transaction_id=result['transaction_id']))
        else:
            flash(result['message'], 'danger')
            return redirect(url_for('admission_payment'))
    
    return render_template('admissions/payment.html', amount=amount, student_name=admission_data['full_name'])

@app.route('/admissions/payment/status/<transaction_id>')
def admission_payment_status(transaction_id):
    """Check payment status and complete admission if successful"""
    status = check_payment_status(transaction_id)
    
    if status == 'successful':
        # Update student record
        cur = get_db().cursor()
        cur.execute("""
            UPDATE students SET 
                payment_status = 'completed',
                payment_date = CURRENT_TIMESTAMP,
                admission_status = 'pending'
            WHERE payment_transaction_id = ?
        """, (transaction_id,))
        get_db().commit()
        cur.close()
        
        flash('Payment confirmed! Your application is pending review by the admissions office.', 'success')
        return redirect(url_for('admission_submitted'))
    
    elif status == 'failed':
        flash('Payment failed. Please try again.', 'danger')
        return redirect(url_for('admission_payment'))
    
    else:
        # Still pending - refresh page to check again
        return render_template('admissions/payment_pending.html', transaction_id=transaction_id)

@app.route('/admissions/submitted')
def admission_submitted():
    admission_data = session.get('admission_data')
    if not admission_data:
        return redirect(url_for('admissions_portal'))
    return render_template('admissions/submitted.html', data=admission_data)

# ==================== DOS MODULE ====================
SCHOOL_ABBR = "TSS"
def generate_student_id():
    return generate_unique_number(SCHOOL_ABBR, 'students', 'student_id', year_format=True)

@app.route('/dos/admit_student', methods=['GET', 'POST'])
def dos_admit():
    if not check_permission(['dos']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT name FROM houses ORDER BY name")
    houses = cur.fetchall()
    cur.execute("SELECT name FROM sports_activities ORDER BY name")
    sports = cur.fetchall()
    cur.close()
    
    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        class_name = request.form['class'].strip()
        date_of_birth = request.form.get('date_of_birth') or None
        sex = request.form.get('sex') or None
        preferred_house = request.form.get('preferred_house') or None
        lin = request.form.get('lin') or None
        disability = request.form.get('disability') or None
        sports_activities = request.form.getlist('sports_activities')
        parent_phone_raw = request.form.get('parent_phone', '').strip()
        parent_phone = validate_and_format_phone(parent_phone_raw) if parent_phone_raw else None
        photo = request.files.get('photo')
        
        age = None
        if date_of_birth:
            birth_date = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
            age = calculate_age(birth_date)
        
        student_id = generate_student_id()
        photo_filename = "default_avatar.png"
        if photo and photo.filename and allowed_file(photo.filename, ALLOWED_IMAGE_EXTENSIONS):
            ext = photo.filename.rsplit('.', 1)[1].lower()
            photo_filename = f"{student_id}.{ext}"
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], photo_filename))
        
        try:
            execute_db("""INSERT INTO students (student_id, full_name, class, photo_path, fees_paid, fees_balance, admission_date, parent_phone, 
                           date_of_birth, age, sex, preferred_house, disability, sports_activities, lin, admission_source, admission_status)
                           VALUES (?, ?, ?, ?, 0, 0, DATE('now'), ?, ?, ?, ?, ?, ?, ?, ?, 'local', 'approved')""",
                       (student_id, full_name, class_name, photo_filename, parent_phone, date_of_birth, age, sex, preferred_house, disability,
                        ','.join(sports_activities) if sports_activities else None, lin))
            flash(f'Student {full_name} admitted with ID {student_id}.', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dos_admit'))
    
    return render_template('dos/admit_student.html', houses=houses, sports=sports)

@app.route('/dos/admission_settings', methods=['GET', 'POST'])
def dos_admission_settings():  # Remove @admin_required
    if not check_permission(['dos']):
        abort(403)
    
    if request.method == 'POST':
        is_open = 1 if request.form.get('is_open') == 'on' else 0
        deadline = request.form.get('deadline') or None
        closing_reason = request.form.get('closing_reason', '')
        fee_amount = float(request.form.get('fee_amount', 50000))
        
        execute_db("""UPDATE admission_settings SET 
                      is_open=?, deadline=?, closing_reason=?, fee_amount=?, updated_at=CURRENT_TIMESTAMP 
                      WHERE id=1""",
                   (is_open, deadline, closing_reason, fee_amount))
        
        flash('Admission settings updated successfully.', 'success')
        return redirect(url_for('dos_admission_settings'))
    
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT is_open, deadline, closing_reason, fee_amount FROM admission_settings WHERE id=1")
    settings = cur.fetchone()
    
    # Get pending online applications
    cur.execute("SELECT student_id, full_name, lin, application_date FROM students WHERE admission_source='online' AND admission_status='pending' ORDER BY application_date DESC")
    pending = cur.fetchall()
    cur.close()
    
    return render_template('dos/admission_settings.html', 
                          settings=settings, 
                          pending=pending,
                          is_open=settings['is_open'] if settings else 1,
                          deadline=settings['deadline'] if settings else '',
                          closing_reason=settings['closing_reason'] if settings else '',
                          fee_amount=settings['fee_amount'] if settings else 50000)

@app.route('/dos/class_lists')
def dos_class_lists():
    if not check_permission(['dos']):
        abort(403)
    class_filter = request.args.get('class', '') or ''
    search = request.args.get('search', '') or ''
    term = request.args.get('term', 'Term 1')
    
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != '' ORDER BY class")
    classes = [row['class'] for row in cur.fetchall()]
    
    query = "SELECT student_id, full_name, class, photo_path, parent_phone, sex, age, preferred_house, lin, admission_source FROM students WHERE 1=1"
    params = []
    if class_filter:
        query += " AND class = ?"
        params.append(class_filter)
    if search:
        query += " AND (student_id LIKE ? OR full_name LIKE ?)"
        pattern = f"%{search}%"
        params.append(pattern)
        params.append(pattern)
    query += " ORDER BY full_name"
    cur.execute(query, params)
    students = cur.fetchall()
    
    for s in students:
        s['photo_url'] = get_photo_url(s.get('photo_path'))
    
    cur.close()
    return render_template('dos/class_lists.html', classes=classes, students=students, selected_class=class_filter, search=search, term=term)

@app.route('/dos/teacher_assignments', methods=['GET', 'POST'])
def dos_teacher_assignments():

    if not check_permission(['dos']):
        abort(403)

    db = get_db_dict()
    cur = db.cursor()

    # ==========================
    # ADD ASSIGNMENT
    # ==========================
    if request.method == 'POST':

        teacher_id = request.form.get('teacher_id')
        assignment_type = request.form.get('assignment_type')
        class_name = request.form.get('class_name')
        subject = request.form.get('subject') or None

        if assignment_type == 'classteacher':
            subject = None

        # Duplicate check
        cur.execute("""
            SELECT id
            FROM teacher_class_assignments
            WHERE user_id=?
            AND class_name=?
            AND assignment_type=?
            AND subject IS ?
        """, (
            teacher_id,
            class_name,
            assignment_type,
            subject
        ))

        if cur.fetchone():
            flash("This assignment already exists.", "warning")
            return redirect(url_for('dos_teacher_assignments'))


        # Only one class teacher per class
        if assignment_type == "classteacher":

            cur.execute("""
                SELECT id
                FROM teacher_class_assignments
                WHERE class_name=?
                AND assignment_type='classteacher'
            """, (class_name,))

            if cur.fetchone():
                flash(
                    f"{class_name} already has a class teacher.",
                    "danger"
                )
                return redirect(url_for('dos_teacher_assignments'))


        cur.execute("""
            INSERT INTO teacher_class_assignments
            (
                user_id,
                class_name,
                subject,
                assignment_type,
                assigned_by
            )
            VALUES (?,?,?,?,?)
        """, (
            teacher_id,
            class_name,
            subject,
            assignment_type,
            session.get('username')
        ))

        db.commit()

        flash(
            "Teacher assignment added successfully.",
            "success"
        )

        return redirect(url_for('dos_teacher_assignments'))



    # ==========================
    # GET TEACHERS FOR FORM
    # ==========================

    cur.execute("""
        SELECT id, username, full_name
        FROM users
        WHERE role IN
        (
            'teacher',
            'subject_teacher',
            'classteacher'
        )
        ORDER BY full_name
    """)

    teachers = cur.fetchall()



    # ==========================
    # GET CLASSES
    # ==========================

    cur.execute("""
        SELECT DISTINCT class
        FROM students
        WHERE class IS NOT NULL
        ORDER BY class
    """)

    classes = cur.fetchall()



    # ==========================
    # GET ASSIGNMENTS
    # ==========================

    cur.execute("""
        SELECT 
            tca.*,
            u.username,
            u.full_name,
            u.phone

        FROM teacher_class_assignments tca

        JOIN users u
        ON tca.user_id=u.id

        ORDER BY u.full_name
    """)

    assignments = cur.fetchall()


    cur.close()


    # Organize teachers
    teachers_data = {}

    for a in assignments:

        uid = a['user_id']

        if uid not in teachers_data:

            teachers_data[uid] = {
                "username": a['username'],
                "full_name": a['full_name'],
                "phone": a['phone'],
                "class_teacher": None,
                "subjects": []
            }


        if a['assignment_type'] == 'classteacher':

            teachers_data[uid]['class_teacher'] = a['class_name']

        else:

            teachers_data[uid]['subjects'].append({
                "class": a['class_name'],
                "subject": a['subject']
            })



    class_teachers = []
    subject_teachers = []
    both_roles = []


    for teacher in teachers_data.values():

        has_class = teacher['class_teacher'] is not None
        has_subject = len(teacher['subjects']) > 0


        if has_class and has_subject:

            teacher['classteacher_class'] = teacher['class_teacher']
            both_roles.append(teacher)


        elif has_class:

            teacher['class_name'] = teacher['class_teacher']
            class_teachers.append(teacher)


        elif has_subject:

            for s in teacher['subjects']:

                subject_teachers.append({
                    "username": teacher['username'],
                    "full_name": teacher['full_name'],
                    "phone": teacher['phone'],
                    "class_name": s['class'],
                    "subject": s['subject']
                })



    return render_template(
        'dos/teacher_assignments.html',
        teachers=teachers,
        classes=classes,
        class_teachers=class_teachers,
        subject_teachers=subject_teachers,
        both_roles=both_roles
    )

@app.route('/dos/remove_student/<student_id>', methods=['POST'])
def dos_remove_student(student_id):
    if not check_permission(['dos']):
        abort(403)
    cur = get_db().cursor()
    cur.execute("SELECT photo_path FROM students WHERE student_id=?", (student_id,))
    row = cur.fetchone()
    cur.close()
    if row and row[0] != 'default_avatar.png':
        path = os.path.join(app.config['UPLOAD_FOLDER'], row[0])
        if os.path.exists(path):
            os.remove(path)
    execute_db("DELETE FROM students WHERE student_id=?", (student_id,))
    flash(f'Student {student_id} removed.', 'success')
    return redirect(url_for('dos_class_lists'))

@app.route('/dos/promote', methods=['GET', 'POST'])
def dos_promote():
    if not check_permission(['dos']):
        abort(403)
    cur = get_db().cursor()
    cur.execute("SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != '' ORDER BY class")
    classes = [row[0] for row in cur.fetchall()]
    cur.close()
    if request.method == 'POST':
        from_class = request.form['from_class']
        match = re.search(r'(\d+)', from_class)
        if match:
            to_class = from_class.replace(str(match.group(1)), str(int(match.group(1)) + 1))
        else:
            to_class = from_class + " (Promoted)"
        execute_db("UPDATE students SET class=? WHERE class=?", (to_class, from_class))
        flash(f'{cur.rowcount} students promoted from {from_class} to {to_class}.', 'success')
    return render_template('dos/promote.html', classes=classes)

@app.route('/dos/attendance')
def dos_attendance():
    if not check_permission(['dos']):
        abort(403)
    cur = get_db().cursor()
    cur.execute("SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != '' ORDER BY class")
    classes = [row[0] for row in cur.fetchall()]
    cur.close()
    return render_template('dos/attendance.html', classes=classes)

@app.route('/dos/schedules', methods=['GET', 'POST'])
def dos_schedules():
    if not check_permission(['dos']):
        abort(403)
    if request.method == 'POST':
        schedule_type = request.form['schedule_type']
        term_scope = request.form['term_scope']
        content = request.form.get('schedule_text', '').strip()
        file = request.files.get('schedule_file')
        final_content = content
        if file and file.filename and allowed_file(file.filename, {'csv'}):
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            reader = csv.reader(stream)
            parsed = []
            for row in reader:
                if any(row):
                    parsed.append(",".join([escape(cell.strip()) for cell in row]))
            final_content = "\n".join(parsed)
        execute_db("INSERT INTO schedules (type, term_scope, content, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(type, term_scope) DO UPDATE SET content=?, updated_at=CURRENT_TIMESTAMP",
                   (schedule_type, term_scope, final_content, final_content))
        flash(f'{schedule_type.capitalize()} saved.', 'success')
        return redirect(url_for('dos_schedules'))
    cur = get_db().cursor()
    cur.execute("SELECT type, term_scope, content, updated_at FROM schedules ORDER BY type, term_scope DESC")
    schedules = cur.fetchall()
    cur.close()
    return render_template('dos/schedules.html', schedules=schedules)

# DOS Grading Management
@app.route('/dos/olevel_grading', methods=['GET', 'POST'])
def dos_olevel_grading():
    if not check_permission(['dos']):
        abort(403)
    if request.method == 'POST':
        file = request.files.get('grading_file')
        if not file or not file.filename:
            flash('Please upload an Excel file.', 'danger')
            return redirect(url_for('dos_olevel_grading'))
        try:
            from openpyxl import load_workbook
            wb = load_workbook(file, data_only=True)
            sheet = wb.active
            
            # Get headers from first row
            headers = []
            for cell in sheet[1]:
                if cell.value:
                    headers.append(str(cell.value).strip().lower())
                else:
                    headers.append('')
            
            # Find required column indices
            min_score_col = None
            max_score_col = None
            grade_col = None
            descriptor_col = None
            
            for idx, h in enumerate(headers):
                if h == 'min_score':
                    min_score_col = idx
                elif h == 'max_score':
                    max_score_col = idx
                elif h == 'grade':
                    grade_col = idx
                elif h == 'descriptor':
                    descriptor_col = idx
            
            if min_score_col is None or max_score_col is None or grade_col is None or descriptor_col is None:
                flash('Missing required columns: min_score, max_score, grade, descriptor', 'danger')
                return redirect(url_for('dos_olevel_grading'))
            
            execute_db("DELETE FROM grading_system")
            count = 0
            
            for row_idx in range(2, sheet.max_row + 1):
                min_val = sheet.cell(row=row_idx, column=min_score_col + 1).value
                max_val = sheet.cell(row=row_idx, column=max_score_col + 1).value
                grade_val = sheet.cell(row=row_idx, column=grade_col + 1).value
                desc_val = sheet.cell(row=row_idx, column=descriptor_col + 1).value
                
                if min_val is None or max_val is None or grade_val is None:
                    continue
                
                try:
                    execute_db("INSERT INTO grading_system (min_score, max_score, grade, descriptor) VALUES (?, ?, ?, ?)",
                               (float(min_val), float(max_val), str(grade_val).strip(), str(desc_val).strip() if desc_val else ''))
                    count += 1
                except:
                    continue
            
            flash(f'{count} O-Level grading rules uploaded.', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dos_olevel_grading'))
    
    cur = get_db().cursor()
    cur.execute("SELECT min_score, max_score, grade, descriptor FROM grading_system ORDER BY min_score DESC")
    rules = cur.fetchall()
    cur.close()
    return render_template('dos/olevel_grading.html', rules=rules)

@app.route('/dos/alevel_grading', methods=['GET', 'POST'])
def dos_alevel_grading():
    if not check_permission(['dos']):
        abort(403)
    if request.method == 'POST':
        file = request.files.get('grading_file')
        if not file or not file.filename:
            flash('Please upload an Excel file.', 'danger')
            return redirect(url_for('dos_alevel_grading'))
        try:
            from openpyxl import load_workbook
            wb = load_workbook(file, data_only=True)
            sheet = wb.active
            
            headers = []
            for cell in sheet[1]:
                headers.append(str(cell.value).strip().lower() if cell.value else '')
            
            min_score_col = None
            max_score_col = None
            grade_col = None
            points_col = None
            
            for idx, h in enumerate(headers):
                if h == 'min_score':
                    min_score_col = idx
                elif h == 'max_score':
                    max_score_col = idx
                elif h == 'grade':
                    grade_col = idx
                elif h == 'points':
                    points_col = idx
            
            if None in [min_score_col, max_score_col, grade_col, points_col]:
                flash('Missing required columns: min_score, max_score, grade, points', 'danger')
                return redirect(url_for('dos_alevel_grading'))
            
            execute_db("DELETE FROM alevel_grading WHERE is_subsidiary=0")
            count = 0
            
            for row_idx in range(2, sheet.max_row + 1):
                min_val = sheet.cell(row=row_idx, column=min_score_col + 1).value
                max_val = sheet.cell(row=row_idx, column=max_score_col + 1).value
                grade_val = sheet.cell(row=row_idx, column=grade_col + 1).value
                points_val = sheet.cell(row=row_idx, column=points_col + 1).value
                
                if None in [min_val, max_val, grade_val, points_val]:
                    continue
                
                try:
                    execute_db("INSERT INTO alevel_grading (min_score, max_score, grade, points, is_subsidiary) VALUES (?, ?, ?, ?, 0)",
                               (float(min_val), float(max_val), str(grade_val).strip(), int(points_val)))
                    count += 1
                except:
                    continue
            
            flash(f'{count} A-Level grading rules uploaded.', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dos_alevel_grading'))
    
    cur = get_db().cursor()
    cur.execute("SELECT min_score, max_score, grade, points FROM alevel_grading WHERE is_subsidiary=0 ORDER BY min_score DESC")
    rules = cur.fetchall()
    cur.close()
    return render_template('dos/alevel_grading.html', rules=rules)
    
@app.route('/dos/predefined_comments')
def dos_predefined_comments():
    if not check_permission(['dos']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM predefined_comments ORDER BY comment_type, id")
    comments = cur.fetchall()
    cur.close()
    return render_template('dos/predefined_comments.html', comments=comments)

@app.route('/dos/predefined_comments/add', methods=['POST'])
def dos_predefined_comments_add():
    if not check_permission(['dos']):
        abort(403)
    comment_type = request.form['comment_type']
    comment_text = request.form['comment_text'].strip()
    if not comment_text:
        flash('Comment text is required.', 'danger')
        return redirect(url_for('dos_predefined_comments'))
    execute_db("INSERT INTO predefined_comments (comment_type, comment_text, is_active) VALUES (?, ?, 1)", (comment_type, comment_text))
    flash('Comment added successfully.', 'success')
    return redirect(url_for('dos_predefined_comments'))

@app.route('/dos/predefined_comments/delete/<int:comment_id>')
def dos_predefined_comments_delete(comment_id):
    if not check_permission(['dos']):
        abort(403)
    execute_db("DELETE FROM predefined_comments WHERE id=?", (comment_id,))
    flash('Comment deleted successfully.', 'success')
    return redirect(url_for('dos_predefined_comments'))

@app.route('/dos/identifier_grading', methods=['GET', 'POST'])
def dos_identifier_grading():
    if not check_permission(['dos']):
        abort(403)
    if request.method == 'POST':
        file = request.files.get('grading_file')
        if not file or not file.filename:
            flash('Please upload an Excel file.', 'danger')
            return redirect(url_for('dos_identifier_grading'))
        try:
            from openpyxl import load_workbook
            wb = load_workbook(file, data_only=True)
            sheet = wb.active
            
            headers = []
            for cell in sheet[1]:
                headers.append(str(cell.value).strip().lower() if cell.value else '')
            
            min_col = None
            max_col = None
            desc_col = None
            
            for idx, h in enumerate(headers):
                if h == 'min_value':
                    min_col = idx
                elif h == 'max_value':
                    max_col = idx
                elif h == 'descriptor':
                    desc_col = idx
            
            if None in [min_col, max_col, desc_col]:
                flash('Missing required columns: min_value, max_value, descriptor', 'danger')
                return redirect(url_for('dos_identifier_grading'))
            
            execute_db("DELETE FROM identifier_grading")
            count = 0
            
            for row_idx in range(2, sheet.max_row + 1):
                min_val = sheet.cell(row=row_idx, column=min_col + 1).value
                max_val = sheet.cell(row=row_idx, column=max_col + 1).value
                desc_val = sheet.cell(row=row_idx, column=desc_col + 1).value
                
                if None in [min_val, max_val, desc_val]:
                    continue
                
                try:
                    execute_db("INSERT INTO identifier_grading (min_value, max_value, descriptor) VALUES (?, ?, ?)",
                               (float(min_val), float(max_val), str(desc_val).strip()))
                    count += 1
                except:
                    continue
            
            flash(f'{count} Identifier grading rules uploaded.', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dos_identifier_grading'))
    
    cur = get_db().cursor()
    cur.execute("SELECT min_value, max_value, descriptor FROM identifier_grading ORDER BY min_value DESC")
    rules = cur.fetchall()
    cur.close()
    return render_template('dos/identifier_grading.html', rules=rules)

@app.route('/dos/upload_teachers', methods=['GET', 'POST'])
def dos_upload_teachers():
    if not check_permission(['dos']):
        abort(403)
    
    if request.method == 'POST':
        file = request.files.get('excel_file')
        if not file or not file.filename:
            flash('Please upload an Excel file.', 'danger')
            return redirect(url_for('dos_upload_teachers'))
        
        try:
            from openpyxl import load_workbook
            wb = load_workbook(file, data_only=True)
            sheet = wb.active
            
            # Get headers
            headers = []
            for cell in sheet[1]:
                headers.append(str(cell.value).strip().lower() if cell.value else '')
            
            # Find columns
            col_map = {}
            for idx, h in enumerate(headers):
                if h in ['username', 'full_name', 'class_name', 'subject', 'assignment_type']:
                    col_map[h] = idx
            
            required = ['username', 'full_name', 'class_name', 'assignment_type']
            for r in required:
                if r not in col_map:
                    flash(f'Missing column: {r}', 'danger')
                    return redirect(url_for('dos_upload_teachers'))
            
            db = get_db_dict()
            cur = db.cursor()
            success = 0
            errors = []
            
            for row_idx in range(2, sheet.max_row + 1):
                try:
                    username = str(sheet.cell(row=row_idx, column=col_map['username'] + 1).value or '').strip()
                    full_name = str(sheet.cell(row=row_idx, column=col_map['full_name'] + 1).value or '').strip()
                    class_name = str(sheet.cell(row=row_idx, column=col_map['class_name'] + 1).value or '').strip()
                    assignment_type = str(sheet.cell(row=row_idx, column=col_map['assignment_type'] + 1).value or '').strip().lower()
                    subject = str(sheet.cell(row=row_idx, column=col_map.get('subject', 999) + 1).value or '').strip() if 'subject' in col_map else None
                    
                    if not username or not class_name or not assignment_type:
                        errors.append(f"Row {row_idx}: Missing username, class_name, or assignment_type")
                        continue
                    
                    # Validate assignment_type
                    if assignment_type not in ['classteacher', 'subject_teacher']:
                        errors.append(f"Row {row_idx}: Invalid assignment_type '{assignment_type}'. Must be 'classteacher' or 'subject_teacher'")
                        continue
                    
                    # For subject_teacher, subject is required
                    if assignment_type == 'subject_teacher' and not subject:
                        errors.append(f"Row {row_idx}: Subject is required for subject_teacher")
                        continue
                    
                    # Check if user exists, if not create
                    cur.execute("SELECT id, full_name FROM users WHERE username=?", (username,))
                    user = cur.fetchone()
                    
                    if not user:
                        # Create user with default password
                        default_password = 'password123'
                        hashed = generate_password_hash(default_password)
                        cur.execute("""
                            INSERT INTO users (username, full_name, password, role, status, must_change_password) 
                            VALUES (?, ?, ?, ?, 1, 1)
                        """, (username, full_name or username, hashed, 
                              'subject_teacher' if assignment_type == 'subject_teacher' else 'classteacher'))
                        user_id = cur.lastrowid
                        
                        # Add notification to DOS only (not to teacher)
                        add_notification(
                            'dos',  # Send to DOS role
                            f"New teacher created: {full_name or username}. Username: {username}, Password: {default_password}. Class: {class_name}, Type: {assignment_type}",
                            f"/dos/teacher_assignments"
                        )
                        
                        success += 1
                    else:
                        user_id = user['id']
                        # Update full_name if provided and different
                        if full_name and full_name != user['full_name']:
                            cur.execute("UPDATE users SET full_name=? WHERE id=?", (full_name, user_id))
                        # Update role if needed (DOS uploads can't override admin roles)
                        current_role = user['role'] if isinstance(user, dict) else user[2]
                        if current_role not in ['admin', 'headteacher', 'bursar']:
                            new_role = 'subject_teacher' if assignment_type == 'subject_teacher' else 'classteacher'
                            if current_role != new_role:
                                cur.execute("UPDATE users SET role=? WHERE id=?", (new_role, user_id))
                        success += 1
                    
                    # For class teacher, check if class already has one
                    if assignment_type == 'classteacher':
                        cur.execute("""
                            SELECT id FROM teacher_class_assignments 
                            WHERE class_name=? AND assignment_type='classteacher'
                        """, (class_name,))
                        existing_class_teacher = cur.fetchone()
                        
                        if existing_class_teacher:
                            errors.append(f"Row {row_idx}: Class '{class_name}' already has a class teacher! Skipped {username}")
                            continue
                    
                    # Check if this specific assignment already exists
                    cur.execute("""
                        SELECT id FROM teacher_class_assignments 
                        WHERE user_id=? AND class_name=? AND assignment_type=?
                    """, (user_id, class_name, assignment_type))
                    existing_assignment = cur.fetchone()
                    
                    if existing_assignment:
                        # Update existing assignment
                        if assignment_type == 'subject_teacher' and subject:
                            cur.execute("""
                                UPDATE teacher_class_assignments 
                                SET subject=?, assigned_by=?, assigned_at=CURRENT_TIMESTAMP
                                WHERE id=?
                            """, (subject, session.get('username'), existing_assignment['id']))
                            errors.append(f"Row {row_idx}: Updated existing assignment for {username} - {class_name} ({assignment_type})")
                        else:
                            errors.append(f"Row {row_idx}: Assignment already exists for {username} - {class_name} ({assignment_type})")
                    else:
                        # Insert new assignment
                        cur.execute("""
                            INSERT INTO teacher_class_assignments 
                            (user_id, class_name, subject, assignment_type, assigned_by)
                            VALUES (?, ?, ?, ?, ?)
                        """, (user_id, class_name, subject, assignment_type, session.get('username')))
                    
                except Exception as e:
                    errors.append(f"Row {row_idx}: {str(e)}")
                    app.logger.error(f"Error in row {row_idx}: {str(e)}")
                    continue
            
            db.commit()
            cur.close()
            
            flash(f'{success} teachers processed. {len(errors)} issues found.', 
                  'success' if success > 0 else 'warning')
            if errors:
                for e in errors[:10]:  # Show first 10 errors
                    flash(e, 'warning')
                    
        except Exception as e:
            app.logger.error(f"Upload error: {str(e)}")
            flash(f'Error uploading file: {str(e)}', 'danger')
        
        return redirect(url_for('dos_teacher_assignments'))
    
    return render_template('dos/upload_teachers.html')


def assign_user_to_class(user_id, class_name, subject=None, assignment_type='subject_teacher'):
    """Helper function to assign a teacher to a class with proper conflict handling"""
    try:
        db = get_db_dict()
        cur = db.cursor()
        
        # Check if assignment already exists
        cur.execute("""
            SELECT id FROM teacher_class_assignments 
            WHERE user_id=? AND class_name=? AND assignment_type=?
        """, (user_id, class_name, assignment_type))
        
        existing = cur.fetchone()
        
        if existing:
            # Update existing assignment
            if assignment_type == 'subject_teacher':
                cur.execute("""
                    UPDATE teacher_class_assignments 
                    SET subject=?, assigned_at=CURRENT_TIMESTAMP
                    WHERE id=?
                """, (subject, existing['id']))
            else:
                # For classteacher, just update timestamp
                cur.execute("""
                    UPDATE teacher_class_assignments 
                    SET assigned_at=CURRENT_TIMESTAMP
                    WHERE id=?
                """, (existing['id'],))
        else:
            # Insert new assignment
            cur.execute("""
                INSERT INTO teacher_class_assignments 
                (user_id, class_name, subject, assignment_type, assigned_by)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, class_name, subject, assignment_type, session.get('username')))
        
        db.commit()
        cur.close()
        return True
        
    except Exception as e:
        app.logger.error(f"Error in assign_user_to_class: {str(e)}")
        return False


@app.route('/dos/delete_assignment/<int:assignment_id>', methods=['POST'])
def dos_delete_assignment(assignment_id):
    if not check_permission(['dos']):
        return jsonify({'success': False, 'error': 'Permission denied'})
    
    try:
        db = get_db_dict()
        cur = db.cursor()
        cur.execute("DELETE FROM teacher_class_assignments WHERE id = ?", (assignment_id,))
        db.commit()
        cur.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/dos/edit_assignment/<int:assignment_id>', methods=['GET', 'POST'])
def dos_edit_assignment(assignment_id):
    if not check_permission(['dos']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    
    if request.method == 'POST':
        class_name = request.form.get('class_name')
        subject = request.form.get('subject')
        assignment_type = request.form.get('assignment_type')
        
        cur.execute("""
            UPDATE teacher_class_assignments 
            SET class_name=?, subject=?, assignment_type=?, assigned_by=?
            WHERE id=?
        """, (class_name, subject, assignment_type, session.get('username'), assignment_id))
        db.commit()
        cur.close()
        flash('Assignment updated successfully!', 'success')
        return redirect(url_for('dos_teacher_assignments'))
    
    # GET request - show edit form
    cur.execute("""
        SELECT tca.*, u.username, u.full_name 
        FROM teacher_class_assignments tca
        JOIN users u ON tca.user_id = u.id
        WHERE tca.id = ?
    """, (assignment_id,))
    assignment = cur.fetchone()
    cur.close()
    
    # Get all classes for dropdown
    cur = db.cursor()
    cur.execute("SELECT DISTINCT class FROM students ORDER BY class")
    classes = cur.fetchall()
    cur.close()
    
    return render_template('dos/edit_assignment.html', assignment=assignment, classes=classes)

@app.route('/dos/report_card/<student_id>')
def dos_report_card(student_id):
    if not check_permission(['dos']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    
    cur.execute("SELECT full_name, class, photo_path FROM students WHERE student_id=?", (student_id,))
    student = cur.fetchone()
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('dos_class_lists'))
    
    full_name, class_name, photo_path = student['full_name'], student['class'], student['photo_path']
    photo_url = get_photo_url(photo_path)
    
    term = request.args.get('term', 'Term 1')
    year = request.args.get('year', datetime.now().year)
    
    cur.execute("SELECT school_name, school_address, school_phone, school_email, logo_url FROM school_settings WHERE id=1")
    school = cur.fetchone()
    school_name = school['school_name'] if school else 'YOUR SCHOOL NAME'
    school_address = school['school_address'] if school else 'P.O. Box 123, Kampala, Uganda'
    school_phone = school['school_phone'] if school else 'Tel: +256 712 345678'
    school_email = school['school_email'] if school else 'Email: info@school.com'
    school_logo_url = school['logo_url'] if school else url_for('static', filename='images/logo.png')
    
    cur.execute("SELECT next_term_begins, next_term_ends, headteacher_stamp FROM school_settings WHERE id=1")
    settings = cur.fetchone()
    next_term_begins = settings['next_term_begins'] if settings else None
    next_term_ends = settings['next_term_ends'] if settings else None
    stamp_url = url_for('static', filename='uploads/' + settings['headteacher_stamp']) if settings and settings['headteacher_stamp'] else None
    
    cur.execute("SELECT comment, headteacher_comment FROM teacher_comments WHERE student_id=? AND term=? AND year=?", 
                (student_id, term, year))
    comments = cur.fetchone()
    teacher_comment = comments['comment'] if comments else ''
    headteacher_comment = comments['headteacher_comment'] if comments else ''
    
    class_upper = class_name.upper()
    is_alevel = class_upper in ['S5', 'S6', 'A-LEVEL', 'A LEVEL', 'S.5', 'S.6'] or (class_upper.startswith('S') and len(class_upper) >= 2 and class_upper[1] in ['5', '6'])
    
    if is_alevel:
        cur.execute("SELECT subject, paper1, paper2, total_score, grade, points, teacher_initials FROM marks WHERE student_id=? AND term=? AND year=? ORDER BY subject", 
                    (student_id, term, year))
        marks = cur.fetchall()
        total_points = sum(m['points'] for m in marks if m['points'] is not None) if marks else 0
        cur.close()
        return render_template('teacher/report_card_alevel.html',
            student_id=student_id, full_name=full_name, class_name=class_name, photo_url=photo_url,
            term=term, year=year, marks=marks, total_points=total_points,
            teacher_comment=teacher_comment, headteacher_comment=headteacher_comment,
            next_term_begins=next_term_begins, next_term_ends=next_term_ends, stamp_url=stamp_url,
            school_name=school_name, school_address=school_address, school_phone=school_phone,
            school_email=school_email, school_logo_url=school_logo_url, can_edit_comments=False)
    else:
        cur.execute("""SELECT subject, ai1, ai2, ai3, ai_average, ai_contribution, eot_score, total_score, grade, identifier, descriptor, teacher_initials
                       FROM marks WHERE student_id=? AND term=? AND year=? ORDER BY subject""", (student_id, term, year))
        marks = cur.fetchall()
        total_final = sum(m['total_score'] for m in marks) if marks else 0
        count = len(marks)
        avg_percent = total_final / count if count > 0 else 0
        avg_out_of_3 = round((avg_percent / 100) * 3, 2)
        general_grade, general_descriptor = get_grade_and_descriptor(avg_percent)
        cur.close()
        return render_template('teacher/report_card.html',
            student_id=student_id, full_name=full_name, class_name=class_name, photo_url=photo_url,
            term=term, year=year, marks=marks, avg_out_of_3=avg_out_of_3,
            general_grade=general_grade, general_descriptor=general_descriptor,
            teacher_comment=teacher_comment, headteacher_comment=headteacher_comment,
            next_term_begins=next_term_begins, next_term_ends=next_term_ends, stamp_url=stamp_url,
            school_name=school_name, school_address=school_address, school_phone=school_phone,
            school_email=school_email, school_logo_url=school_logo_url, can_edit_comments=False)

@app.route('/dos/admissions/pending')
def dos_pending_admissions():
    if not check_permission(['dos']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM students WHERE admission_source = 'online' AND admission_status = 'pending' ORDER BY application_date DESC")
    pending = cur.fetchall()
    cur.close()
    return render_template('dos/pending_admissions.html', pending=pending)

@app.route('/dos/admissions/approve/<student_id>')
def dos_approve_admission(student_id):
    if not check_permission(['dos']):
        abort(403)
    new_student_id = generate_student_id()
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM students WHERE student_id=? AND admission_source='online' AND admission_status='pending'", (student_id,))
    student = cur.fetchone()
    if not student:
        flash('Admission not found or already processed.', 'danger')
        return redirect(url_for('dos_pending_admissions'))
    cur.execute("UPDATE students SET student_id=?, admission_status='approved' WHERE student_id=?", (new_student_id, student_id))
    letter_content = generate_admission_letter({
        'full_name': student['full_name'], 'student_id': new_student_id,
        'class': student['class'], 'lin': student['lin'], 'preferred_house': student['preferred_house']
    })
    send_email(student['email'], 'Admission Letter - Approved', letter_content)
    db.commit()
    cur.close()
    flash(f'Admission approved for {student["full_name"]}. Student ID: {new_student_id}', 'success')
    return redirect(url_for('dos_pending_admissions'))

@app.route('/dos/admissions/reject/<student_id>')
def dos_reject_admission(student_id):
    if not check_permission(['dos']):
        abort(403)
    execute_db("UPDATE students SET admission_status='rejected' WHERE student_id=? AND admission_source='online' AND admission_status='pending'", (student_id,))
    flash('Admission rejected.', 'warning')
    return redirect(url_for('dos_pending_admissions'))

# ==================== UNIFIED TEACHER MODULE ====================
@app.route('/teacher/students')
def teacher_students():
    if not check_permission(['classteacher', 'subject_teacher']):
        abort(403)
    
    term = request.args.get('term', 'Term 1')
    user_id = session.get('user_id')
    assignments = get_user_assignments(user_id)
    
    if not assignments:
        flash('No classes assigned to you. Please contact admin.', 'danger')
        return redirect(url_for('dashboard'))
    
    available_classes = list(set([a['class_name'] for a in assignments]))
    selected_class = request.args.get('class_name', session.get('selected_class', available_classes[0]))
    session['selected_class'] = selected_class
    
    if selected_class not in available_classes:
        selected_class = available_classes[0]
        session['selected_class'] = selected_class
    
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT student_id, full_name, photo_path, parent_phone FROM students WHERE class=? ORDER BY full_name", (selected_class,))
    students = cur.fetchall()
    for s in students:
        s['photo_url'] = get_photo_url(s.get('photo_path'))
    cur.close()
    
    is_classteacher = any(a['assignment_type'] == 'classteacher' and a['class_name'] == selected_class for a in assignments)
    
    return render_template('teacher/students.html', students=students, selected_class=selected_class,
                           available_classes=available_classes, is_classteacher=is_classteacher, term=term)

@app.route('/teacher/attendance', methods=['GET', 'POST'])
def teacher_attendance():
    if not check_permission(['classteacher']):
        abort(403)
    selected_class = session.get('selected_class')
    if not selected_class:
        flash('No class selected', 'danger')
        return redirect(url_for('teacher_students'))
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    if request.method == 'POST':
        selected_date = request.form['date']
        for key, value in request.form.items():
            if key.startswith('status_'):
                student_id = key.split('_')[1]
                execute_db("INSERT INTO attendance (student_id, date, status) VALUES (?, ?, ?) ON CONFLICT(student_id, date) DO UPDATE SET status=?",
                           (student_id, selected_date, value, value))
        flash('Attendance saved.', 'success')
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT s.student_id, s.full_name, a.status FROM students s LEFT JOIN attendance a ON s.student_id = a.student_id AND a.date = ? WHERE s.class = ? ORDER BY s.full_name", 
                (selected_date, selected_class))
    records = cur.fetchall()
    cur.close()
    return render_template('teacher/attendance.html', records=records, selected_date=selected_date, assigned_class=selected_class)

@app.route("/save_manual_marks", methods=["POST"])
def save_manual_marks():

    student_ids = request.form.getlist("student_id[]")
    paper1 = request.form.getlist("paper1[]")
    paper2 = request.form.getlist("paper2[]")
    initials = request.form.getlist("teacher_initials[]")

    for sid, p1, p2, init in zip(student_ids, paper1, paper2, initials):

        # Insert or update database
        cursor.execute("""
            INSERT INTO alevel_marks
            (student_id, paper1, paper2, teacher_initials)
            VALUES (?, ?, ?, ?)
        """, (sid, p1, p2, init))

    db.commit()

    flash("Marks saved successfully.")
    return redirect(url_for("upload_marks"))
    
@app.route('/teacher/upload_marks', methods=['GET', 'POST'])
def teacher_upload_marks():
    if not check_permission(['classteacher', 'subject_teacher', 'dos']):
        abort(403)
    teacher_id = session.get('user_id')
    assignments = get_user_assignments(teacher_id)
    if not assignments:
        flash('No classes assigned.', 'danger')
        return redirect(url_for('dashboard'))
    available_classes = list(set([a['class_name'] for a in assignments]))
    selected_class = request.args.get('class_name', session.get('selected_class', available_classes[0]))
    session['selected_class'] = selected_class
    if selected_class not in available_classes:
        selected_class = available_classes[0]
    class_upper = selected_class.upper()
    level = 'alevel' if class_upper in ['S5', 'S6', 'A-LEVEL', 'A LEVEL','S.5', 'S.6'] or (class_upper.startswith('S') and len(class_upper) >= 2 and class_upper[1] in ['5', '6']) else 'olevel'
    current_year = datetime.now().year
    if request.method == 'POST':
        subject = request.form['subject'].strip()
        term = request.form['term'].strip()
        year = request.form['year'].strip()
        is_subsidiary = request.form.get('is_subsidiary') == 'on'
        file = request.files.get('marks_file')
        if not file or not file.filename:
            flash('Please upload an Excel file.', 'danger')
            return redirect(url_for('teacher_upload_marks', class_name=selected_class))
        count = process_marks_upload(file, subject, term, year, selected_class, teacher_id, level, is_subsidiary)
        flash(f'{count} marks uploaded for {subject} (Class: {selected_class}, {term} {year}).', 'success')
        return redirect(url_for('teacher_upload_marks', class_name=selected_class))
    return render_template(f'teacher/upload_marks_{level}.html', assigned_class=selected_class, current_year=current_year, 
                          teacher_classes=[{'class_name': c} for c in available_classes], selected_class=selected_class)

@app.route("/save_olevel_marks", methods=["POST"])
def save_olevel_marks():

    student_ids = request.form.getlist("student_id[]")
    ai1 = request.form.getlist("ai1[]")
    ai2 = request.form.getlist("ai2[]")
    ai3 = request.form.getlist("ai3[]")
    eot = request.form.getlist("eot_score[]")
    initials = request.form.getlist("teacher_initials[]")

    for sid, a1, a2, a3, e, init in zip(
        student_ids, ai1, ai2, ai3, eot, initials
    ):

        cursor.execute("""
            INSERT INTO olevel_marks
            (student_id, ai1, ai2, ai3,
             eot_score, teacher_initials)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (sid, a1, a2, a3, e, init))

    db.commit()

    flash("Marks saved successfully.", "success")
    return redirect(url_for("upload_olevel_marks"))

@app.route('/teacher/report_card/<student_id>')
def teacher_report_card(student_id):
    if not check_permission(['classteacher', 'subject_teacher', 'parent', 'dos', 'headteacher']):
        abort(403)
    
    role = session.get('role')
    db = get_db_dict()
    cur = db.cursor()
    
    if role in ['classteacher', 'subject_teacher']:
        selected_class = session.get('selected_class')
        if not selected_class:
            flash('No class selected', 'danger')
            return redirect(url_for('teacher_students'))
        cur.execute("SELECT class FROM students WHERE student_id=?", (student_id,))
        res = cur.fetchone()
        if not res or res['class'] != selected_class:
            flash('Student not in your class.', 'danger')
            return redirect(url_for('teacher_students'))
    elif role == 'parent':
        parent_phone = session.get('phone')
        if not parent_phone:
            flash('No phone linked.', 'danger')
            return redirect(url_for('dashboard'))
        cur.execute("SELECT parent_phone FROM students WHERE student_id=?", (student_id,))
        res = cur.fetchone()
        if not res or res['parent_phone'] != parent_phone:
            flash('Not authorized.', 'danger')
            return redirect(url_for('dashboard'))
    elif role == 'dos':
        cur.execute("SELECT class FROM students WHERE student_id=?", (student_id,))
        if not cur.fetchone():
            flash('Student not found.', 'danger')
            return redirect(url_for('dos_class_lists'))
    elif role == 'headteacher':
        cur.execute("SELECT class FROM students WHERE student_id=?", (student_id,))
        if not cur.fetchone():
            flash('Student not found.', 'danger')
            return redirect(url_for('dashboard'))
    
    cur.execute("SELECT full_name, class, photo_path FROM students WHERE student_id=?", (student_id,))
    student = cur.fetchone()
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('dashboard'))
    
    full_name, class_name, photo_path = student['full_name'], student['class'], student['photo_path']
    photo_url = get_photo_url(photo_path)
    
    term = request.args.get('term', 'Term 1')
    year = request.args.get('year', datetime.now().year)
    
    cur.execute("SELECT school_name, school_address, school_phone, school_email, logo_url FROM school_settings WHERE id=1")
    school = cur.fetchone()
    school_name = school['school_name'] if school else 'YOUR SCHOOL NAME'
    school_address = school['school_address'] if school else 'P.O. Box 123, Kampala, Uganda'
    school_phone = school['school_phone'] if school else 'Tel: +256 712 345678'
    school_email = school['school_email'] if school else 'Email: info@school.com'
    school_logo_url = school['logo_url'] if school else url_for('static', filename='images/logo.png')
    
    cur.execute("SELECT next_term_begins, next_term_ends, headteacher_stamp FROM school_settings WHERE id=1")
    settings = cur.fetchone()
    next_term_begins = settings['next_term_begins'] if settings else None
    next_term_ends = settings['next_term_ends'] if settings else None
    stamp_url = url_for('static', filename='uploads/' + settings['headteacher_stamp']) if settings and settings['headteacher_stamp'] else None
    
    cur.execute("SELECT comment, headteacher_comment, class_teacher_comment_locked, headteacher_comment_locked FROM teacher_comments WHERE student_id=? AND term=? AND year=?", 
                (student_id, term, year))
    comments = cur.fetchone()
    teacher_comment = comments['comment'] if comments else ''
    headteacher_comment = comments['headteacher_comment'] if comments else ''
    teacher_comment_locked = comments['class_teacher_comment_locked'] if comments else 0
    headteacher_comment_locked = comments['headteacher_comment_locked'] if comments else 0
    
    can_edit_class_comment = (role == 'classteacher' and not teacher_comment_locked)
    can_edit_head_comment = (role == 'headteacher' and not headteacher_comment_locked)
    can_view_only = role in ['subject_teacher', 'parent', 'dos']
    
    predefined_class_comments = get_predefined_comments('class_teacher')
    predefined_head_comments = get_predefined_comments('headteacher')
    
    class_upper = class_name.upper()
    is_alevel = class_upper in ['S5', 'S6', 'A-LEVEL', 'A LEVEL', 'S.5', 'S.6'] or (class_upper.startswith('S') and len(class_upper) >= 2 and class_upper[1] in ['5', '6'])
    
    if is_alevel:
        cur.execute("SELECT subject, paper1, paper2, total_score, grade, points, teacher_initials FROM marks WHERE student_id=? AND term=? AND year=? ORDER BY subject", 
                    (student_id, term, year))
        marks = cur.fetchall()
        total_points = sum(m['points'] for m in marks if m['points'] is not None) if marks else 0
        cur.close()
        return render_template('teacher/report_card_alevel.html',
            student_id=student_id, full_name=full_name, class_name=class_name, photo_url=photo_url,
            term=term, year=year, marks=marks, total_points=total_points,
            teacher_comment=teacher_comment, headteacher_comment=headteacher_comment,
            teacher_comment_locked=teacher_comment_locked, headteacher_comment_locked=headteacher_comment_locked,
            next_term_begins=next_term_begins, next_term_ends=next_term_ends, stamp_url=stamp_url,
            can_edit_class_comment=can_edit_class_comment, can_edit_head_comment=can_edit_head_comment, can_view_only=can_view_only,
            school_name=school_name, school_address=school_address, school_phone=school_phone,
            school_email=school_email, school_logo_url=school_logo_url,
            predefined_class_comments=predefined_class_comments,
            predefined_head_comments=predefined_head_comments)
    else:
        cur.execute("""SELECT subject, ai1, ai2, ai3, ai_average, ai_contribution, eot_score, total_score, grade, identifier, descriptor, teacher_initials
                       FROM marks WHERE student_id=? AND term=? AND year=? ORDER BY subject""", (student_id, term, year))
        marks = cur.fetchall()
        total_final = sum(m['total_score'] for m in marks) if marks else 0
        count = len(marks)
        avg_percent = total_final / count if count > 0 else 0
        avg_out_of_3 = round((avg_percent / 100) * 3, 2)
        general_grade, general_descriptor = get_grade_and_descriptor(avg_percent)
        cur.close()
        return render_template('teacher/report_card.html',
            student_id=student_id, full_name=full_name, class_name=class_name, photo_url=photo_url,
            term=term, year=year, marks=marks, avg_out_of_3=avg_out_of_3,
            general_grade=general_grade, general_descriptor=general_descriptor,
            teacher_comment=teacher_comment, headteacher_comment=headteacher_comment,
            teacher_comment_locked=teacher_comment_locked, headteacher_comment_locked=headteacher_comment_locked,
            next_term_begins=next_term_begins, next_term_ends=next_term_ends, stamp_url=stamp_url,
            can_edit_class_comment=can_edit_class_comment, can_edit_head_comment=can_edit_head_comment, can_view_only=can_view_only,
            school_name=school_name, school_address=school_address, school_phone=school_phone,
            school_email=school_email, school_logo_url=school_logo_url,
            predefined_class_comments=predefined_class_comments,
            predefined_head_comments=predefined_head_comments)

@app.route('/teacher/save_comment', methods=['POST'])
def teacher_save_comment():
    if not check_permission(['classteacher']):
        abort(403)
    student_id = request.form['student_id']
    term = request.form['term']
    year = request.form['year']
    comment = request.form.get('comment', '').strip()
    custom_comment = request.form.get('custom_comment', '').strip()
    final_comment = custom_comment if custom_comment else comment
    
    cur = get_db().cursor()
    cur.execute("SELECT class_teacher_comment_locked FROM teacher_comments WHERE student_id=? AND term=? AND year=?", (student_id, term, year))
    existing = cur.fetchone()
    cur.close()
    
    if existing and existing[0] == 1:
        flash('Comment cannot be edited as it has been locked.', 'danger')
        return redirect(url_for('teacher_report_card', student_id=student_id, term=term, year=year))
    
    execute_db("INSERT INTO teacher_comments (student_id, term, year, comment, class_teacher_comment_locked) VALUES (?, ?, ?, ?, 1) ON CONFLICT(student_id, term, year) DO UPDATE SET comment=?, class_teacher_comment_locked=1",
               (student_id, term, year, final_comment, final_comment))
    flash('Comment saved and locked.', 'success')
    return redirect(url_for('teacher_report_card', student_id=student_id, term=term, year=year))

@app.route('/teacher/edit_student/<student_id>', methods=['GET', 'POST'])
def teacher_edit_student(student_id):
    if not check_permission(['classteacher']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    
    # Get student details
    cur.execute("SELECT * FROM students WHERE student_id = ?", (student_id,))
    student = cur.fetchone()
    
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('teacher_students'))
    
    # Get teacher's assigned class
    cur.execute("""
        SELECT class_name FROM teacher_class_assignments 
        WHERE user_id = ? AND assignment_type = 'classteacher'
    """, (session.get('user_id'),))
    result = cur.fetchone()
    assigned_class = result['class_name'] if isinstance(result, dict) else result[0] if result else None
    
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        class_name = request.form.get('class', '').strip()
        admission_date = request.form.get('admission_date', '')
        date_of_birth = request.form.get('date_of_birth', '')
        sex = request.form.get('sex', '')
        preferred_house = request.form.get('preferred_house', '')
        disability = request.form.get('disability', '')
        parent_email = request.form.get('parent_email', '')
        address = request.form.get('address', '')
        
        # Calculate age from date of birth
        age = None
        if date_of_birth:
            try:
                birth_date = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
                today = datetime.now().date()
                age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            except:
                age = None
        
        # Handle photo upload
        photo_path = student.get('photo_path', 'default_avatar.png')
        photo = request.files.get('photo')
        if photo and photo.filename and allowed_file(photo.filename, ALLOWED_IMAGE_EXTENSIONS):
            ext = photo.filename.rsplit('.', 1)[1].lower()
            photo_filename = f"{student_id}.{ext}"
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], photo_filename))
            photo_path = photo_filename
        
        # Update student record
        cur.execute("""
            UPDATE students 
            SET full_name = ?, parent_phone = ?, class = ?, admission_date = ?, 
                date_of_birth = ?, age = ?, sex = ?, preferred_house = ?, 
                disability = ?, parent_email = ?, address = ?, photo_path = ?
            WHERE student_id = ?
        """, (full_name, parent_phone, class_name, admission_date, date_of_birth, age, 
              sex, preferred_house, disability, parent_email, address, photo_path, student_id))
        
        db.commit()
        cur.close()
        
        flash(f'Student {full_name} updated successfully!', 'success')
        return redirect(url_for('teacher_students'))
    
    cur.close()
    return render_template('teacher/edit_student.html', student=student, assigned_class=assigned_class)

@app.route('/teacher/remove_student/<student_id>', methods=['POST'])
def teacher_remove_student(student_id):
    if not check_permission(['classteacher', 'dos']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    
    # First check if student exists
    cur.execute("SELECT full_name, class FROM students WHERE student_id = ?", (student_id,))
    student = cur.fetchone()
    
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('teacher_students'))
    
    # For class teacher, verify student is in their class
    if session.get('role') == 'classteacher':
        cur.execute("""
            SELECT class_name FROM teacher_class_assignments 
            WHERE user_id = ? AND assignment_type = 'classteacher'
        """, (session.get('user_id'),))
        result = cur.fetchone()
        assigned_class = result['class_name'] if isinstance(result, dict) else result[0] if result else None
        
        student_class = student['class'] if isinstance(student, dict) else student[1]
        
        if assigned_class != student_class:
            flash('You can only remove students from your own class.', 'danger')
            cur.close()
            return redirect(url_for('teacher_students'))
    
    # Delete the student
    cur.execute("DELETE FROM students WHERE student_id = ?", (student_id,))
    db.commit()
    cur.close()
    
    flash(f'Student {student["full_name"] if isinstance(student, dict) else student[0]} removed successfully.', 'success')
    return redirect(url_for('teacher_students'))

@app.route('/teacher/upload_students', methods=['GET', 'POST'])
def teacher_upload_students():
    if not check_permission(['classteacher']):
        abort(403)
    
    if request.method == 'POST':
        file = request.files.get('excel_file')
        if not file or not file.filename:
            flash('Please upload an Excel or CSV file.', 'danger')
            return redirect(url_for('teacher_upload_students'))
        
        try:
            from openpyxl import load_workbook
            import csv
            import io
            
            # Get teacher's assigned class
            db = get_db_dict()
            cur = db.cursor()
            cur.execute("""
                SELECT class_name FROM teacher_class_assignments 
                WHERE user_id = ? AND assignment_type = 'classteacher'
            """, (session.get('user_id'),))
            result = cur.fetchone()
            
            if not result:
                flash('You are not assigned as a class teacher.', 'danger')
                return redirect(url_for('teacher_upload_students'))
            
            assigned_class = result['class_name'] if isinstance(result, dict) else result[0]
            
            success_count = 0
            error_count = 0
            errors = []
            row_index = 2
            
            # Handle Excel file
            if file.filename.endswith('.xlsx') or file.filename.endswith('.xls'):
                wb = load_workbook(file, data_only=True)
                sheet = wb.active
                
                # Get headers to find correct columns
                headers = []
                for cell in sheet[1]:
                    headers.append(str(cell.value).strip().lower() if cell.value else '')
                
                # Find column indices
                full_name_col = None
                parent_phone_col = None
                
                for idx, h in enumerate(headers):
                    if h in ['full_name', 'name', 'student_name']:
                        full_name_col = idx
                    elif h in ['parent_phone', 'phone', 'parent_contact']:
                        parent_phone_col = idx
                
                # Default to first two columns if not found
                if full_name_col is None:
                    full_name_col = 0
                if parent_phone_col is None:
                    parent_phone_col = 1
                
                # Iterate through rows
                for row_idx in range(2, sheet.max_row + 1):
                    full_name = str(sheet.cell(row=row_idx, column=full_name_col + 1).value or '').strip()
                    parent_phone = str(sheet.cell(row=row_idx, column=parent_phone_col + 1).value or '').strip()
                    
                    if not full_name:
                        errors.append(f"Row {row_idx}: Missing full_name")
                        error_count += 1
                        continue
                    
                    # Generate unique student ID
                    student_id = generate_student_id()
                    
                    # Insert student
                    cur.execute("""
                        INSERT INTO students (student_id, full_name, class, parent_phone, admission_status, fees_total, fees_paid, fees_balance)
                        VALUES (?, ?, ?, ?, 'approved', 0, 0, 0)
                    """, (student_id, full_name, assigned_class, parent_phone))
                    
                    success_count += 1
                    row_index = row_idx
            
            # Handle CSV file
            elif file.filename.endswith('.csv'):
                content = file.read().decode('utf-8')
                csv_reader = csv.reader(io.StringIO(content))
                headers = next(csv_reader)  # Skip header row
                
                # Find column indices
                full_name_col = None
                parent_phone_col = None
                
                for idx, h in enumerate(headers):
                    h_lower = h.strip().lower()
                    if h_lower in ['full_name', 'name', 'student_name']:
                        full_name_col = idx
                    elif h_lower in ['parent_phone', 'phone', 'parent_contact']:
                        parent_phone_col = idx
                
                if full_name_col is None:
                    full_name_col = 0
                if parent_phone_col is None:
                    parent_phone_col = 1
                
                for row_idx, row in enumerate(csv_reader, start=2):
                    if len(row) <= max(full_name_col, parent_phone_col):
                        continue
                    
                    full_name = row[full_name_col].strip() if full_name_col < len(row) else ''
                    parent_phone = row[parent_phone_col].strip() if parent_phone_col < len(row) else ''
                    
                    if not full_name:
                        errors.append(f"Row {row_idx}: Missing full_name")
                        error_count += 1
                        continue
                    
                    # Generate unique student ID
                    student_id = generate_student_id()
                    
                    # Insert student
                    cur.execute("""
                        INSERT INTO students (student_id, full_name, class, parent_phone, admission_status, fees_total, fees_paid, fees_balance)
                        VALUES (?, ?, ?, ?, 'approved', 0, 0, 0)
                    """, (student_id, full_name, assigned_class, parent_phone))
                    
                    success_count += 1
            
            else:
                flash('Unsupported file format. Please upload .xlsx, .xls, or .csv', 'danger')
                return redirect(url_for('teacher_upload_students'))
            
            db.commit()
            cur.close()
            
            # Add notification for DOS
            add_notification('dos', f'Class teacher uploaded {success_count} students to class {assigned_class}', '/dos/class_lists')
            
            flash(f'Uploaded {success_count} students to class {assigned_class}. Errors: {error_count}', 
                  'success' if success_count > 0 else 'danger')
            if errors:
                for e in errors[:5]:
                    flash(e, 'warning')
                    
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
        
        return redirect(url_for('teacher_students'))
    
    return render_template('teacher/upload_students.html')

@app.route('/teacher/print_all_report_cards')
def teacher_print_all_report_cards():
    if not check_permission(['classteacher']):
        abort(403)
    
    selected_class = session.get('selected_class')
    if not selected_class:
        selected_class = session.get('assigned_class')
    if not selected_class:
        flash('No class assigned to you.', 'danger')
        return redirect(url_for('teacher_students'))
    
    term = request.args.get('term', 'Term 1')
    year = request.args.get('year', datetime.now().year)
    
    db = get_db_dict()
    cur = db.cursor()
    
    cur.execute("SELECT student_id, full_name, photo_path FROM students WHERE class=? ORDER BY full_name", (selected_class,))
    students_data = cur.fetchall()
    
    if not students_data:
        flash(f'No students found in class {selected_class}.', 'warning')
        return redirect(url_for('teacher_students'))
    
    cur.execute("SELECT school_name, school_address, school_phone, school_email, logo_url FROM school_settings WHERE id=1")
    school_data = cur.fetchone()
    if school_data:
        school_name = school_data['school_name'] if school_data['school_name'] else 'YOUR SCHOOL NAME'
        school_address = school_data['school_address'] if school_data['school_address'] else 'P.O. Box 123, Kampala, Uganda'
        school_phone = school_data['school_phone'] if school_data['school_phone'] else 'Tel: +256 712 345678'
        school_email = school_data['school_email'] if school_data['school_email'] else 'Email: info@school.com'
        school_logo_url = school_data['logo_url'] if school_data['logo_url'] else url_for('static', filename='images/logo.png')
    else:
        school_name = 'YOUR SCHOOL NAME'
        school_address = 'P.O. Box 123, Kampala, Uganda'
        school_phone = 'Tel: +256 712 345678'
        school_email = 'Email: info@school.com'
        school_logo_url = url_for('static', filename='images/logo.png')
    
    cur.execute("SELECT next_term_begins, next_term_ends, headteacher_stamp FROM school_settings WHERE id=1")
    settings = cur.fetchone()
    next_term_begins = settings['next_term_begins'] if settings else None
    next_term_ends = settings['next_term_ends'] if settings else None
    stamp_url = url_for('static', filename='uploads/' + settings['headteacher_stamp']) if settings and settings['headteacher_stamp'] else None
    
    class_upper = selected_class.upper()
    is_alevel = class_upper in ['S5', 'S6', 'A-LEVEL', 'A LEVEL', 'S.5', 'S.6'] or (class_upper.startswith('S') and len(class_upper) >= 2 and class_upper[1] in ['5', '6'])
    
    all_reports = []
    for student in students_data:
        student_id = student['student_id']
        full_name = student['full_name']
        photo_path = student['photo_path']
        photo_url = get_photo_url(photo_path)
        
        cur.execute("SELECT comment, headteacher_comment FROM teacher_comments WHERE student_id=? AND term=? AND year=?", (student_id, term, year))
        comments_row = cur.fetchone()
        teacher_comment = comments_row['comment'] if comments_row else ''
        headteacher_comment = comments_row['headteacher_comment'] if comments_row else ''
        
        if is_alevel:
            cur.execute("SELECT subject, paper1, paper2, total_score, grade, points, teacher_initials FROM marks WHERE student_id=? AND term=? AND year=? ORDER BY subject", 
                        (student_id, term, year))
            marks = cur.fetchall()
            total_points = sum(m['points'] for m in marks if m['points'] is not None) if marks else 0
            all_reports.append({'student_id': student_id, 'full_name': full_name, 'photo_url': photo_url, 'marks': marks,
                                'total_points': total_points, 'teacher_comment': teacher_comment, 'headteacher_comment': headteacher_comment})
        else:
            cur.execute("""SELECT subject, ai1, ai2, ai3, ai_average, ai_contribution, eot_score, total_score, grade, identifier, descriptor, teacher_initials
                           FROM marks WHERE student_id=? AND term=? AND year=? ORDER BY subject""", (student_id, term, year))
            marks = cur.fetchall()
            total_final = sum(m['total_score'] for m in marks) if marks else 0
            count = len(marks)
            avg_percent = total_final / count if count > 0 else 0
            avg_out_of_3 = round((avg_percent / 100) * 3, 2)
            general_grade, general_descriptor = get_grade_and_descriptor(avg_percent)
            all_reports.append({'student_id': student_id, 'full_name': full_name, 'photo_url': photo_url, 'marks': marks,
                                'avg_out_of_3': avg_out_of_3, 'general_grade': general_grade, 'general_descriptor': general_descriptor,
                                'teacher_comment': teacher_comment, 'headteacher_comment': headteacher_comment})
    
    cur.close()
    template = 'teacher/print_all_report_cards_alevel.html' if is_alevel else 'teacher/print_all_report_cards.html'
    return render_template(template, reports=all_reports, class_name=selected_class, term=term, year=year,
                          next_term_begins=next_term_begins, next_term_ends=next_term_ends, stamp_url=stamp_url,
                          school_name=school_name, school_address=school_address, school_phone=school_phone,
                          school_email=school_email, school_logo_url=school_logo_url)

# ==================== BURSAR MODULE ====================
def generate_receipt_number():
    return generate_unique_number('RCP', 'payments', 'receipt_no', year_format=True)

def send_fee_sms(phone_number, student_name, amount, balance):
    if not phone_number:
        return False
    message = f"Payment of UGX {amount:,.2f} received for {student_name}. Balance: UGX {balance:,.2f}. Thank you."
    return send_sms(phone_number, message)

def calculate_nssf_and_paye(gross_salary):
    cur = get_db().cursor()
    cur.execute("SELECT nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
    rates = cur.fetchone()
    cur.close()
    nssf_employee_rate = rates[0] if rates else 5.0
    paye_rate = rates[1] if rates else 10.0
    paye_threshold = rates[2] if rates else 235000
    nssf_employee = (gross_salary * nssf_employee_rate) / 100
    taxable_amount = max(0, gross_salary - paye_threshold)
    paye_tax = (taxable_amount * paye_rate) / 100
    return {'nssf_employee': round(nssf_employee, 2), 'paye_tax': round(paye_tax, 2)}

@app.route('/bursar/dashboard')
def bursar_dashboard():
    if not check_permission(['bursar']):
        abort(403)
    
    db = get_db()
    cur = db.cursor()
    
    # Get totals safely
    cur.execute("SELECT SUM(fees_total) as total_fees, SUM(fees_paid) as total_paid, SUM(fees_balance) as total_balance FROM students")
    row = cur.fetchone()
    totals = {
        'total_fees': row[0] if row and row[0] else 0,
        'total_paid': row[1] if row and row[1] else 0,
        'total_balance': row[2] if row and row[2] else 0
    }
    
    cur.execute("SELECT COUNT(*) FROM students WHERE fees_balance > 0")
    defaulter_count = cur.fetchone()[0] or 0
    
    cur.execute("SELECT COUNT(*) FROM students")
    total_students = cur.fetchone()[0] or 0
    
    # Recent payments
    cur.execute("""
        SELECT p.*, s.full_name, s.class 
        FROM payments p 
        JOIN students s ON p.student_id = s.student_id 
        ORDER BY p.payment_date DESC 
        LIMIT 10
    """)
    recent_payments = cur.fetchall()
    cur.close()
    
    return render_template('bursar/dashboard.html', 
                          totals=totals,
                          defaulter_count=defaulter_count,
                          total_students=total_students,
                          recent_payments=recent_payments)

@app.route('/bursar/students')
def bursar_students():
    if not check_permission(['bursar']):
        abort(403)
    
    search = request.args.get('search', '').strip()
    class_filter = request.args.get('class', '').strip()
    
    db = get_db_dict()
    cur = db.cursor()
    
    query = "SELECT student_id, full_name, class, parent_phone, fees_total, fees_paid, fees_balance FROM students WHERE 1=1"
    params = []
    
    if search:
        query += " AND (student_id LIKE ? OR full_name LIKE ?)"
        pattern = f"%{search}%"
        params.extend([pattern, pattern])
    if class_filter:
        query += " AND class = ?"
        params.append(class_filter)
    
    query += " ORDER BY full_name"
    cur.execute(query, params)
    students = cur.fetchall()
    
    # Get distinct classes - FIXED
    cur.execute("SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != '' ORDER BY class")
    rows = cur.fetchall()
    classes = []
    for row in rows:
        if isinstance(row, dict):
            classes.append(row.get('class'))
        else:
            classes.append(row[0])
    
    cur.close()
    return render_template('bursar/students.html', students=students, classes=classes, search=search, class_filter=class_filter)

@app.route('/bursar/student/<student_id>')
def bursar_student_detail(student_id):
    if not check_permission(['bursar']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT student_id, full_name, class, parent_phone, fees_total, fees_paid, fees_balance FROM students WHERE student_id=?", (student_id,))
    student = cur.fetchone()
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('bursar_students'))
    cur.execute("SELECT * FROM payments WHERE student_id=? ORDER BY payment_date DESC", (student_id,))
    payments = cur.fetchall()
    cur.close()
    return render_template('bursar/student_detail.html', student=student, payments=payments)

@app.route('/bursar/record_payment', methods=['POST'])
def bursar_record_payment():
    if not check_permission(['bursar']):
        abort(403)
    student_id = request.form['student_id']
    amount = float(request.form['amount'])
    payment_method = request.form.get('payment_method', 'Cash')
    notes = request.form.get('notes', '')
    receipt_no = generate_receipt_number()
    
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT full_name, parent_phone, fees_paid, fees_balance FROM students WHERE student_id=?", (student_id,))
    student = cur.fetchone()
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('bursar_students'))
    cur.execute("INSERT INTO payments (student_id, amount, payment_date, receipt_no, payment_method, notes, recorded_by) VALUES (?, ?, DATE('now'), ?, ?, ?, ?)",
                (student_id, amount, receipt_no, payment_method, notes, session.get('username')))
    new_paid = student['fees_paid'] + amount
    new_balance = student['fees_balance'] - amount
    cur.execute("UPDATE students SET fees_paid=?, fees_balance=? WHERE student_id=?", (new_paid, new_balance, student_id))
    db.commit()
    cur.close()
    if student['parent_phone']:
        send_fee_sms(student['parent_phone'], student['full_name'], amount, new_balance)
    flash(f'Payment recorded. Receipt: {receipt_no}', 'success')
    return redirect(url_for('bursar_student_detail', student_id=student_id))

@app.route('/bursar/print_receipts')
def bursar_print_receipts():
    if not check_permission(['bursar']):
        abort(403)
    receipt_ids = request.args.get('ids', '')
    receipts = []
    if receipt_ids:
        ids = [int(x) for x in receipt_ids.split(',') if x.isdigit()]
        if ids:
            placeholders = ','.join(['?'] * len(ids))
            db = get_db_dict()
            cur = db.cursor()
            cur.execute(f"SELECT p.*, s.full_name, s.class FROM payments p JOIN students s ON p.student_id = s.student_id WHERE p.id IN ({placeholders}) ORDER BY p.payment_date DESC", ids)
            receipts = cur.fetchall()
            cur.close()
    return render_template('bursar/print_receipts.html', receipts=receipts)

@app.route('/bursar/send_reminder/<student_id>')
def bursar_send_reminder(student_id):
    if not check_permission(['bursar']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT full_name, parent_phone, fees_balance FROM students WHERE student_id=?", (student_id,))
    student = cur.fetchone()
    cur.close()
    if student and student['parent_phone']:
        send_sms(student['parent_phone'], f"Fees reminder: UGX {student['fees_balance']:,.2f} outstanding for {student['full_name']}.")
        flash('Reminder sent.', 'success')
    else:
        flash('No parent phone.', 'warning')
    return redirect(url_for('bursar_student_detail', student_id=student_id))

@app.route('/bursar/bulk_reminder', methods=['POST'])
def bursar_bulk_reminder():
    if not check_permission(['bursar']):
        abort(403)
    class_filter = request.form.get('class', '')
    db = get_db_dict()
    cur = db.cursor()
    query = "SELECT full_name, parent_phone, fees_balance FROM students WHERE fees_balance > 0"
    if class_filter:
        query += " AND class = ?"
        cur.execute(query, (class_filter,))
    else:
        cur.execute(query)
    students = cur.fetchall()
    cur.close()
    sent = 0
    for s in students:
        if s['parent_phone']:
            send_sms(s['parent_phone'], f"Fees reminder: UGX {s['fees_balance']:,.2f} outstanding for {s['full_name']}.")
            sent += 1
    flash(f'{sent} reminders sent.', 'success')
    return redirect(url_for('bursar_students'))

@app.route('/bursar/clearance/<student_id>')
def bursar_clearance(student_id):
    if not check_permission(['bursar']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT student_id, full_name, class, parent_phone, fees_balance, fees_total, fees_paid, photo_path FROM students WHERE student_id=?", (student_id,))
    student = cur.fetchone()
    cur.close()
    
    if not student:
        flash('Student not found', 'danger')
        return redirect(url_for('bursar_students'))
    
    # Add default values for missing fields
    student['fees_total'] = student.get('fees_total') or 0
    student['fees_paid'] = student.get('fees_paid') or 0
    student['fees_balance'] = student.get('fees_balance') or 0
    student['photo_url'] = get_photo_url(student.get('photo_path'))
    
    return render_template('bursar/clearance.html', student=student)

@app.route('/bursar/bulk_clearance')
def bursar_bulk_clearance():
    if not check_permission(['bursar']):
        abort(403)
    
    class_filter = request.args.get('class', '')
    db = get_db_dict()
    cur = db.cursor()
    
    query = "SELECT student_id, full_name, class, parent_phone, fees_balance, fees_total, fees_paid, photo_path FROM students WHERE fees_balance <= 0"
    params = []
    
    if class_filter:
        query += " AND class = ?"
        params.append(class_filter)
        cur.execute(query, params)
    else:
        cur.execute(query)
    
    students = cur.fetchall()
    cur.close()
    
    for s in students:
        s['fees_total'] = s.get('fees_total') or 0
        s['fees_paid'] = s.get('fees_paid') or 0
        s['fees_balance'] = s.get('fees_balance') or 0
        s['photo_url'] = get_photo_url(s.get('photo_path'))
    
    return render_template('bursar/bulk_clearance.html', students=students)

@app.route('/bursar/webhook/process')
def bursar_process_webhooks():
    if not check_permission(['bursar']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM payment_webhooks WHERE processed=0")
    webhooks = cur.fetchall()
    processed = 0
    for w in webhooks:
        if w.get('student_id'):
            cur.execute("SELECT full_name, parent_phone, fees_paid, fees_balance FROM students WHERE student_id=?", (w['student_id'],))
            student = cur.fetchone()
            if student:
                receipt_no = generate_receipt_number()
                cur.execute("INSERT INTO payments (student_id, amount, payment_date, receipt_no, payment_method, notes, recorded_by) VALUES (?, ?, DATE('now'), ?, ?, ?, ?)",
                           (w['student_id'], w['amount'], receipt_no, w.get('payment_method', 'Mobile Money'), 
                            f"Auto from webhook: {w.get('transaction_id', '')}", 'System'))
                new_paid = student['fees_paid'] + w['amount']
                new_balance = student['fees_balance'] - w['amount']
                cur.execute("UPDATE students SET fees_paid=?, fees_balance=? WHERE student_id=?", (new_paid, new_balance, w['student_id']))
                db.commit()
                if student.get('parent_phone'):
                    send_fee_sms(student['parent_phone'], student['full_name'], w['amount'], new_balance)
        cur.execute("UPDATE payment_webhooks SET processed=1 WHERE id=?", (w['id'],))
        processed += 1
    db.commit()
    cur.close()
    flash(f'Processed {processed} pending webhooks.', 'success')
    return redirect(url_for('bursar_dashboard'))

@app.route('/bursar/webhook/payment', methods=['POST'])
def bursar_payment_webhook():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid data'}), 400
    execute_db("""INSERT INTO payment_webhooks (transaction_id, amount, phone_number, student_id, reference, payment_method, raw_data, status, processed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'received', 0)""",
               (data.get('transaction_id'), data.get('amount'), data.get('phone_number'), data.get('student_id'),
                data.get('reference'), data.get('payment_method'), json.dumps(data)))
    return jsonify({'status': 'received'}), 200

# ==================== STAFF PAYROLL ====================
def generate_staff_no():
    return generate_unique_number('STF', 'staff', 'staff_no', year_format=True)

def generate_payroll_no():
    year_month = datetime.now().strftime("%Y%m")
    cur = get_db().cursor()
    cur.execute("SELECT payroll_no FROM payroll WHERE payroll_no LIKE ? ORDER BY payroll_no DESC LIMIT 1", (f'PR-{year_month}-%',))
    last = cur.fetchone()
    cur.close()
    if last:
        last_num = int(last[0].split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1
    return f"PR-{year_month}-{new_num:04d}"

@app.route('/bursar/staff')
def bursar_staff():
    if not check_permission(['bursar']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM staff ORDER BY full_name")
    staff = cur.fetchall()
    
    # Get NSSF and PAYE rates - handle dictionary result
    cur.execute("SELECT nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
    rates_row = cur.fetchone()
    
    if rates_row:
        nssf_rate = rates_row['nssf_employee_rate'] if 'nssf_employee_rate' in rates_row else 5.0
        paye_rate = rates_row['paye_rate'] if 'paye_rate' in rates_row else 10.0
        paye_threshold = rates_row['paye_threshold'] if 'paye_threshold' in rates_row else 235000
    else:
        nssf_rate = 5.0
        paye_rate = 10.0
        paye_threshold = 235000
    
    # Calculate totals and add NSSF/PAYE to each staff
    total_basic = 0
    total_allowances = 0
    total_gross = 0
    total_nssf = 0
    total_paye = 0
    total_deductions = 0
    total_net = 0
    
    for s in staff:
        gross = (s['salary_basic'] or 0) + (s['salary_allowances'] or 0)
        nssf = (gross * nssf_rate) / 100
        taxable = max(0, gross - paye_threshold)
        paye = (taxable * paye_rate) / 100
        net = gross - nssf - paye - (s['salary_deductions'] or 0)
        
        s['gross'] = float(gross)
        s['nssf'] = float(round(nssf, 2))
        s['paye'] = float(round(paye, 2))
        s['net'] = float(round(net, 2))
        s['salary_net'] = float(round(net, 2))
        
        total_basic += float(s['salary_basic'] or 0)
        total_allowances += float(s['salary_allowances'] or 0)
        total_gross += float(gross)
        total_nssf += float(nssf)
        total_paye += float(paye)
        total_deductions += float(s['salary_deductions'] or 0)
        total_net += float(net)
    
    cur.close()
    
    return render_template('bursar/staff.html', 
                          staff=staff,
                          total_basic=total_basic,
                          total_allowances=total_allowances,
                          total_gross=total_gross,
                          total_nssf=total_nssf,
                          total_paye=total_paye,
                          total_deductions=total_deductions,
                          total_net=total_net,
                          nssf_rate=nssf_rate,
                          paye_rate=paye_rate,
                          paye_threshold=paye_threshold)

@app.route('/bursar/staff/add', methods=['GET', 'POST'])
def bursar_staff_add():
    if not check_permission(['bursar']):
        abort(403)
    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        position = request.form['position'].strip()
        department = request.form.get('department', '').strip()
        phone = validate_and_format_phone(request.form.get('phone', ''))
        email = request.form.get('email', '').strip()
        nssf_number = request.form.get('nssf_number', '').strip()
        tin_number = request.form.get('tin_number', '').strip()
        bank_account = request.form.get('bank_account', '').strip()
        bank_name = request.form.get('bank_name', '').strip()
        salary_basic = float(request.form.get('salary_basic', 0))
        salary_allowances = float(request.form.get('salary_allowances', 0))
        salary_deductions = float(request.form.get('salary_deductions', 0))
        staff_no = generate_staff_no()
        
        execute_db("""INSERT INTO staff (staff_no, full_name, position, department, phone, email, nssf_number, tin_number, bank_account, bank_name, salary_basic, salary_allowances, salary_deductions)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   (staff_no, full_name, position, department, phone, email, nssf_number, tin_number,
                    bank_account, bank_name, salary_basic, salary_allowances, salary_deductions))
        flash(f'Staff {full_name} added. Staff No: {staff_no}', 'success')
        return redirect(url_for('bursar_staff'))
    return render_template('bursar/staff_add.html')

@app.route('/bursar/payroll/generate', methods=['GET', 'POST'])
def bursar_generate_payroll():
    if not check_permission(['bursar']):
        abort(403)
    
    if request.method == 'POST':
        month_year = request.form['month_year']
        selected_staff = request.form.getlist('staff_ids')
        if not selected_staff:
            flash('No staff selected.', 'danger')
            return redirect(url_for('bursar_generate_payroll'))
        
        db = get_db_dict()
        cur = db.cursor()
        
        # Get rates from school settings
        cur.execute("SELECT nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
        rates = cur.fetchone()
        
        # Safe extraction - works for both tuple and dictionary
        if rates:
            if isinstance(rates, dict):
                nssf_rate = rates.get('nssf_employee_rate', 5.0)
                paye_rate = rates.get('paye_rate', 10.0)
                paye_threshold = rates.get('paye_threshold', 235000)
            else:
                nssf_rate = rates[0] if len(rates) > 0 else 5.0
                paye_rate = rates[1] if len(rates) > 1 else 10.0
                paye_threshold = rates[2] if len(rates) > 2 else 235000
        else:
            nssf_rate = 5.0
            paye_rate = 10.0
            paye_threshold = 235000
        
        # Get selected staff with bank details
        placeholders = ','.join(['?'] * len(selected_staff))
        cur.execute(f"""
            SELECT id, full_name, position, salary_basic, salary_allowances, 
                   salary_deductions, bank_name, bank_account, phone 
            FROM staff 
            WHERE id IN ({placeholders})
        """, selected_staff)
        staff_list = cur.fetchall()
        
        total_amount = 0
        for staff in staff_list:
            gross = (staff['salary_basic'] or 0) + (staff['salary_allowances'] or 0)
            nssf = (gross * nssf_rate) / 100
            taxable = max(0, gross - paye_threshold)
            paye = (taxable * paye_rate) / 100
            net = gross - nssf - paye - (staff['salary_deductions'] or 0)
            total_amount += net
        
        payroll_no = generate_payroll_no()
        approval_code = generate_approval_code()
        token, expires_at = generate_secure_token(2)
        
        # FIXED: Added approval_status column
        cur.execute("""
            INSERT INTO payroll (
                payroll_no, month_year, total_amount, approval_code, 
                headteacher_access_token, token_expires_at, recorded_by, approval_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (payroll_no, month_year, total_amount, approval_code, token, expires_at, 
              session.get('username'), 'pending'))
        payroll_id = cur.lastrowid
        
        for staff in staff_list:
            gross = (staff['salary_basic'] or 0) + (staff['salary_allowances'] or 0)
            nssf = (gross * nssf_rate) / 100
            taxable = max(0, gross - paye_threshold)
            paye = (taxable * paye_rate) / 100
            net_salary = gross - nssf - paye - (staff['salary_deductions'] or 0)
            
            cur.execute("""
                INSERT INTO salary_payments (
                    staff_id, payroll_id, month_year, basic, allowances, deductions, 
                    gross_salary, nssf_employee, paye_tax, net_salary, approval_code, recorded_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                staff['id'], payroll_id, month_year, 
                staff['salary_basic'] or 0, 
                staff['salary_allowances'] or 0,
                staff['salary_deductions'] or 0, 
                gross, nssf, paye, net_salary, 
                approval_code, session.get('username')
            ))
        
        db.commit()
        cur.close()
        
        approval_link = url_for('headteacher_approval_access', token=token, _external=True)
        cur = get_db().cursor()
        cur.execute("SELECT phone FROM users WHERE role='headteacher' AND status=1 LIMIT 1")
        headteacher = cur.fetchone()
        cur.close()
        
        if headteacher:
            phone = headteacher[0] if isinstance(headteacher, (tuple, list)) else headteacher.get('phone')
            if phone:
                send_sms(phone, ...)
        
        add_notification('headteacher', f"Payroll {payroll_no} needs approval. Code: {approval_code}", f"/headteacher/approval/{token}")
        flash(f'Payroll {payroll_no} created. Approval link sent to Headteacher.', 'success')
        return redirect(url_for('bursar_payroll_list'))
    
    # GET request - FIXED: Get rates and bank details
    db = get_db_dict()
    cur = db.cursor()
    
    # Get rates from school settings to pass to template
    cur.execute("SELECT nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
    rates = cur.fetchone()
    
    if rates:
        if isinstance(rates, dict):
            nssf_rate = rates.get('nssf_employee_rate', 5.0)
            paye_rate = rates.get('paye_rate', 10.0)
            paye_threshold = rates.get('paye_threshold', 235000)
        else:
            nssf_rate = rates[0] if len(rates) > 0 else 5.0
            paye_rate = rates[1] if len(rates) > 1 else 10.0
            paye_threshold = rates[2] if len(rates) > 2 else 235000
    else:
        nssf_rate = 5.0
        paye_rate = 10.0
        paye_threshold = 235000
    
    # Get staff list with bank details (not SELECT *)
    cur.execute("""
        SELECT id, full_name, position, salary_basic, salary_allowances, 
               salary_deductions, bank_name, bank_account, phone 
        FROM staff 
        WHERE status='active' 
        ORDER BY full_name
    """)
    staff_list = cur.fetchall()
    cur.close()
    
    return render_template('bursar/generate_payroll.html', 
                         staff_list=staff_list,
                         nssf_rate=nssf_rate,
                         paye_rate=paye_rate,
                         paye_threshold=paye_threshold)

@app.route('/bursar/payroll/list')
def bursar_payroll_list():
    if not check_permission(['bursar']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT p.*, COUNT(sp.id) as staff_count FROM payroll p LEFT JOIN salary_payments sp ON p.id = sp.payroll_id GROUP BY p.id ORDER BY p.created_at DESC")
    payrolls = cur.fetchall()
    cur.close()
    return render_template('bursar/payroll_list.html', payrolls=payrolls)

@app.route('/bursar/delete_payroll/<int:payroll_id>')
def bursar_delete_payroll(payroll_id):
    if not check_permission(['bursar']):
        abort(403)
    cur = get_db().cursor()
    cur.execute("SELECT approval_status FROM payroll WHERE id=?", (payroll_id,))
    payroll = cur.fetchone()
    cur.close()
    if not payroll:
        flash('Payroll not found.', 'danger')
        return redirect(url_for('bursar_payroll_list'))
    if payroll[0] != 'pending':
        flash('Only pending payrolls can be deleted.', 'warning')
        return redirect(url_for('bursar_payroll_list'))
    try:
        execute_db("DELETE FROM salary_payments WHERE payroll_id=?", (payroll_id,))
        execute_db("DELETE FROM payroll WHERE id=?", (payroll_id,))
        flash('Payroll deleted successfully.', 'success')
    except Exception as e:
        flash(f'Error deleting payroll: {str(e)}', 'danger')
    return redirect(url_for('bursar_payroll_list'))

@app.route('/bursar/view_payroll/<int:payroll_id>')
def bursar_view_payroll(payroll_id):
    if not check_permission(['bursar']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM payroll WHERE id=?", (payroll_id,))
    payroll = cur.fetchone()
    if not payroll:
        flash('Payroll not found.', 'danger')
        return redirect(url_for('bursar_payroll_list'))
    cur.execute("""SELECT sp.*, s.full_name, s.position, s.bank_account, s.bank_name, s.phone, s.staff_no
                   FROM salary_payments sp JOIN staff s ON sp.staff_id = s.id WHERE sp.payroll_id = ?""", (payroll_id,))
    staff_list = cur.fetchall()
    cur.close()
    total_basic = sum(s['basic'] for s in staff_list) if staff_list else 0
    total_allowances = sum(s['allowances'] for s in staff_list) if staff_list else 0
    total_deductions = sum(s['deductions'] for s in staff_list) if staff_list else 0
    return render_template('bursar/view_payroll.html', payroll=payroll, staff_list=staff_list,
                          total_basic=total_basic, total_allowances=total_allowances, total_deductions=total_deductions)
    
@app.route('/bursar/print_payroll')
def bursar_print_payroll():
    if not check_permission(['bursar']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    
    # Get tax rates
    cur.execute("SELECT nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
    rates = cur.fetchone()
    
    if rates:
        if isinstance(rates, dict):
            nssf_rate = rates.get('nssf_employee_rate', 5.0)
            paye_rate = rates.get('paye_rate', 10.0)
            paye_threshold = rates.get('paye_threshold', 235000)
        else:
            nssf_rate = rates[0] if len(rates) > 0 else 5.0
            paye_rate = rates[1] if len(rates) > 1 else 10.0
            paye_threshold = rates[2] if len(rates) > 2 else 235000
    else:
        nssf_rate = 5.0
        paye_rate = 10.0
        paye_threshold = 235000
    
    # Get all staff
    cur.execute("""
        SELECT staff_no, full_name, position, salary_basic, salary_allowances, salary_deductions,
               bank_name, bank_account, phone
        FROM staff 
        ORDER BY full_name
    """)
    staff_list = cur.fetchall()
    cur.close()
    
    # Calculate all values for each staff member
    total_basic = 0
    total_allowances = 0
    total_gross = 0
    total_nssf = 0
    total_paye = 0
    total_deductions = 0
    total_net = 0
    
    for staff in staff_list:
        gross = (staff['salary_basic'] or 0) + (staff['salary_allowances'] or 0)
        nssf = (gross * nssf_rate) / 100
        taxable = max(0, gross - paye_threshold)
        paye = (taxable * paye_rate) / 100
        net = gross - nssf - paye - (staff['salary_deductions'] or 0)
        
        staff['gross'] = gross
        staff['nssf'] = round(nssf, 2)
        staff['paye'] = round(paye, 2)
        staff['salary_net'] = round(net, 2)
        
        total_basic += (staff['salary_basic'] or 0)
        total_allowances += (staff['salary_allowances'] or 0)
        total_gross += gross
        total_nssf += nssf
        total_paye += paye
        total_deductions += (staff['salary_deductions'] or 0)
        total_net += net
    
    return render_template('bursar/print_payroll.html', 
                         staff_list=staff_list,
                         total_basic=total_basic,
                         total_allowances=total_allowances,
                         total_gross=total_gross,
                         total_nssf=total_nssf,
                         total_paye=total_paye,
                         total_deductions=total_deductions,
                         total_net=total_net,
                         nssf_rate=nssf_rate,
                         paye_rate=paye_rate,
                         paye_threshold=paye_threshold)

@app.route('/bursar/print_fees_list')
def bursar_print_fees_list():
    if not check_permission(['bursar']):
        abort(403)
    class_filter = request.args.get('class', '')
    status_filter = request.args.get('status', '')
    db = get_db_dict()
    cur = db.cursor()
    if status_filter == 'defaulters':
        query = "SELECT student_id, full_name, class, fees_paid, fees_balance FROM students WHERE fees_balance > 0"
        params = []
        if class_filter:
            query += " AND class = ?"
            params.append(class_filter)
        query += " ORDER BY class, full_name"
        cur.execute(query, params)
    else:
        query = "SELECT student_id, full_name, class, fees_paid, fees_balance FROM students WHERE 1=1"
        params = []
        if class_filter:
            query += " AND class = ?"
            params.append(class_filter)
        query += " ORDER BY class, full_name"
        cur.execute(query, params)
    students = cur.fetchall()
    cur.close()
    total_paid = sum(s['fees_paid'] for s in students) if students else 0
    total_balance = sum(s['fees_balance'] for s in students) if students else 0
    return render_template('bursar/print_fees_list.html', students=students, class_filter=class_filter,
                          status_filter=status_filter, total_paid=total_paid, total_balance=total_balance)

@app.route('/bursar/budget')
def bursar_budget():
    if not check_permission(['bursar']):
        abort(403)
    year = request.args.get('year', datetime.now().year)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM budget_categories WHERE year=? ORDER BY code", (year,))
    categories = cur.fetchall()
    cur.execute("""SELECT c.code, c.name, c.allocated_amount, SUM(e.amount) as spent FROM budget_categories c 
                   LEFT JOIN expenditures e ON c.id = e.category_id AND e.status='paid' WHERE c.year=? GROUP BY c.id""", (year,))
    summary = cur.fetchall()
    cur.close()
    return render_template('bursar/budget.html', categories=categories, summary=summary, year=year)

@app.route('/bursar/budget/add', methods=['POST'])
def bursar_budget_add():
    if not check_permission(['bursar']):
        abort(403)
    execute_db("INSERT INTO budget_categories (code, name, description, allocated_amount, year) VALUES (?, ?, ?, ?, ?)",
               (request.form['code'], request.form['name'], request.form.get('description', ''), float(request.form['allocated_amount']), request.form['year']))
    flash('Budget category added.', 'success')
    return redirect(url_for('bursar_budget', year=request.form['year']))

@app.route('/bursar/expenditure')
def bursar_expenditure():
    if not check_permission(['bursar']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT e.*, c.code, c.name as category_name FROM expenditures e JOIN budget_categories c ON e.category_id = c.id ORDER BY e.expenditure_date DESC")
    expenditures = cur.fetchall()
    cur.execute("SELECT id, code, name FROM budget_categories ORDER BY code")
    categories = cur.fetchall()
    cur.close()
    return render_template('bursar/expenditure.html', expenditures=expenditures, categories=categories)

@app.route('/bursar/expenditure/add', methods=['POST'])
def bursar_expenditure_add():
    if not check_permission(['bursar']):
        abort(403)
    voucher_no = generate_unique_number('VCH', 'expenditures', 'voucher_no', year_format=True)
    execute_db("""INSERT INTO expenditures (voucher_no, category_id, description, amount, expenditure_date, payment_method, payee_name, payee_phone, status, recorded_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
               (voucher_no, request.form['category_id'], request.form['description'], float(request.form['amount']), request.form['expenditure_date'],
                request.form.get('payment_method', 'Cash'), request.form.get('payee_name', ''),
                validate_and_format_phone(request.form.get('payee_phone', '')), request.form.get('status', 'paid'), session.get('username')))
    flash(f'Expenditure recorded. Voucher: {voucher_no}', 'success')
    return redirect(url_for('bursar_expenditure'))

@app.route('/bursar/income_report')
def bursar_income_report():
    if not check_permission(['bursar']):
        abort(403)
    start = request.args.get('start_date', datetime.now().replace(day=1).strftime('%Y-%m-%d'))
    end = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT DATE(payment_date) as date, SUM(amount) as total FROM payments WHERE payment_date BETWEEN ? AND ? GROUP BY DATE(payment_date) ORDER BY date DESC", (start, end))
    daily = cur.fetchall()
    cur.execute("SELECT payment_method, SUM(amount) as total FROM payments WHERE payment_date BETWEEN ? AND ? GROUP BY payment_method", (start, end))
    by_method = cur.fetchall()
    cur.execute("SELECT SUM(amount) as total_income FROM payments WHERE payment_date BETWEEN ? AND ?", (start, end))
    total = cur.fetchone()
    cur.close()
    return render_template('bursar/income_report.html', daily=daily, by_method=by_method, total=total, start_date=start, end_date=end)

@app.route('/bursar/expenditure_report')
def bursar_expenditure_report():
    if not check_permission(['bursar']):
        abort(403)
    start = request.args.get('start_date', datetime.now().replace(day=1).strftime('%Y-%m-%d'))
    end = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("""SELECT c.code, c.name, SUM(e.amount) as total_spent FROM expenditures e 
                   JOIN budget_categories c ON e.category_id = c.id 
                   WHERE e.expenditure_date BETWEEN ? AND ? AND e.status='paid' 
                   GROUP BY c.id ORDER BY total_spent DESC""", (start, end))
    by_category = cur.fetchall()
    cur.execute("SELECT SUM(amount) as total_expenditure FROM expenditures WHERE expenditure_date BETWEEN ? AND ? AND status='paid'", (start, end))
    total = cur.fetchone()
    cur.close()
    return render_template('bursar/expenditure_report.html', by_category=by_category, total=total, start_date=start, end_date=end)

@app.route('/bursar/school_pay/config', methods=['GET', 'POST'])
def bursar_school_pay_config():
    if not check_permission(['bursar']):
        abort(403)
    if request.method == 'POST':
        execute_db("UPDATE payment_gateway_config SET api_key=?, api_secret=?, webhook_secret=?, callback_url=?, status=? WHERE id=1",
                   (request.form['api_key'], request.form['api_secret'], request.form['webhook_secret'], request.form['callback_url'], request.form.get('status', 'inactive')))
        flash('Configuration saved.', 'success')
    cur = get_db().cursor()
    cur.execute("SELECT * FROM payment_gateway_config WHERE id=1")
    config = cur.fetchone()
    cur.close()
    return render_template('bursar/school_pay_config.html', config=config)

# ==================== HEADTEACHER & MANAGEMENT APPROVAL ====================
@app.route('/headteacher/approvals')
def headteacher_approvals():
    if not check_permission(['headteacher']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("""
        SELECT id, payroll_no, month_year, total_amount, approval_status, 
               approval_code, created_at, recorded_by
        FROM payroll 
        WHERE approval_status = 'pending' 
        ORDER BY created_at DESC
    """)
    pending = cur.fetchall()
    cur.close()
    
    return render_template('headteacher/approvals.html', pending=pending)

@app.route('/headteacher/approval/<token>', methods=['GET', 'POST'])
def headteacher_approval_access(token):
    if not check_permission(['headteacher']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM payroll WHERE headteacher_access_token=? AND approval_status='pending'", (token,))
    payroll = cur.fetchone()
    
    if not payroll:
        flash('Invalid approval link.', 'danger')
        return redirect(url_for('headteacher_approvals'))
    
    # FIXED: Get columns from salary_payments, not staff
    cur.execute("""
        SELECT sp.*, s.full_name, s.position
        FROM salary_payments sp
        JOIN staff s ON sp.staff_id = s.id
        WHERE sp.payroll_id = ?
    """, (payroll['id'],))
    staff_list = cur.fetchall()
    
    if payroll['approval_status'] != 'pending':
        flash(f'This payroll has already been {payroll["approval_status"]}.', 'warning')
        return redirect(url_for('headteacher_approvals'))
    
    if payroll.get('token_expires_at'):
        from datetime import datetime
        expires_value = payroll['token_expires_at']
        
        if isinstance(expires_value, str):
            # Handle milliseconds by splitting at the dot
            if '.' in expires_value:
                expires_value = expires_value.split('.')[0]
            expires_dt = datetime.strptime(expires_value, '%Y-%m-%d %H:%M:%S')
        else:
            expires_dt = expires_value
        
        if expires_dt <= datetime.now():
            flash('This approval link has expired. Please request a new link.', 'danger')
            return redirect(url_for('headteacher_approvals'))
    
    if request.method == 'POST':
        approval_code = request.form.get('approval_code')
        action = request.form.get('action')
        
        if payroll['approval_code'] != approval_code:
            flash('Invalid approval code.', 'danger')
            return redirect(url_for('headteacher_approval_access', token=token))
        
        if action == 'approve':
            mgmt_code = generate_approval_code()
            mgmt_token, mgmt_expires = generate_secure_token(2)
            
            cur.execute("""UPDATE payroll SET approval_status='approved', approved_by=?, approved_at=CURRENT_TIMESTAMP, 
                           management_approval_code=?, management_access_token=?, management_token_expires_at=?, 
                           management_approval_status='pending' WHERE id=?""",
                       ('Headteacher', mgmt_code, mgmt_token, mgmt_expires, payroll['id']))
            cur.execute("UPDATE salary_payments SET approval_status='approved' WHERE payroll_id=?", (payroll['id'],))
            db.commit()
            
            management_link = url_for('management_authorization_access', token=mgmt_token, _external=True)
            expires_str = mgmt_expires.strftime('%Y-%m-%d %H:%M:%S')
            cur.execute("SELECT phone FROM users WHERE role='management' AND status=1")
            management_users = cur.fetchall()
            for mgmt in management_users:
                phone = mgmt['phone'] if isinstance(mgmt, dict) else mgmt[0]
                if phone:
                    send_sms(phone, f"BANK AUTHORIZATION NEEDED: Payroll {payroll['payroll_no']} - UGX {payroll['total_amount']:,.2f}. Code: {mgmt_code}. Expires: {expires_str}. Link: {management_link}")
            add_notification('management', f"Payroll {payroll['payroll_no']} needs bank authorization. Code: {mgmt_code}", f"/management/authorization/{mgmt_token}")
            flash('Payroll approved. Management notified for bank authorization.', 'success')
            
        elif action == 'reject':
            cur.execute("UPDATE payroll SET approval_status='rejected', approved_by=?, approved_at=CURRENT_TIMESTAMP WHERE id=?", ('Headteacher', payroll['id']))
            cur.execute("UPDATE salary_payments SET approval_status='rejected' WHERE payroll_id=?", (payroll['id'],))
            db.commit()
            add_notification('bursar', f"Payroll {payroll['payroll_no']} was REJECTED by Headteacher.", '/bursar/payroll/list')
            flash('Payroll rejected.', 'warning')
        
        cur.close()
        return redirect(url_for('headteacher_approvals'))
    
    remaining_minutes = None
    if payroll.get('token_expires_at'):
        from datetime import datetime
        expires_value = payroll['token_expires_at']
        if '.' in expires_value:
            expires_value = expires_value.split('.')[0]
        try:
            remaining = datetime.strptime(expires_value, '%Y-%m-%d %H:%M:%S') - datetime.now()
            remaining_minutes = int(remaining.total_seconds() / 60)
        except:
            remaining_minutes = None
    
    cur.close()
    return render_template('headteacher/approve_payroll_secure.html', 
                          payroll=payroll, 
                          remaining_minutes=remaining_minutes,
                          staff_list=staff_list)

@app.route('/headteacher/reject_payroll/<int:payroll_id>')
def headteacher_reject_payroll(payroll_id):
    if not check_permission(['headteacher']):
        abort(403)
    cur = get_db().cursor()
    cur.execute("SELECT * FROM payroll WHERE id=? AND approval_status='pending'", (payroll_id,))
    payroll = cur.fetchone()
    cur.close()
    if not payroll:
        flash('Payroll not found or already processed.', 'danger')
        return redirect(url_for('headteacher_approvals'))
    try:
        execute_db("UPDATE payroll SET approval_status='rejected', approved_by=?, approved_at=CURRENT_TIMESTAMP WHERE id=?", ('Headteacher', payroll_id))
        execute_db("UPDATE salary_payments SET approval_status='rejected' WHERE payroll_id=?", (payroll_id,))
        add_notification('bursar', f"Payroll {payroll[1]} has been REJECTED by Headteacher.", '/bursar/payroll/list')
        flash(f'Payroll {payroll[1]} has been rejected.', 'warning')
    except Exception as e:
        flash(f'Error rejecting payroll: {str(e)}', 'danger')
    return redirect(url_for('headteacher_approvals'))

@app.route('/headteacher/resend_token/<int:payroll_id>')
def headteacher_resend_token(payroll_id):
    if not check_permission(['headteacher']):
        abort(403)
    cur = get_db().cursor()
    cur.execute("SELECT * FROM payroll WHERE id=? AND approval_status='pending'", (payroll_id,))
    payroll = cur.fetchone()
    cur.close()
    if not payroll:
        flash('Payroll not found or already processed.', 'danger')
        return redirect(url_for('headteacher_approvals'))
    if payroll.get('token_resend_count', 0) >= 3:
        flash('Maximum token resend limit reached (3). Please create a new payroll.', 'danger')
        return redirect(url_for('headteacher_approvals'))
    new_token, new_expires = generate_secure_token(2)
    execute_db("UPDATE payroll SET headteacher_access_token=?, token_expires_at=?, token_resend_count=token_resend_count+1, last_resend_at=CURRENT_TIMESTAMP WHERE id=?",
               (new_token, new_expires, payroll_id))
    approval_link = url_for('headteacher_approval_access', token=new_token, _external=True)
    expires_str = new_expires.strftime('%Y-%m-%d %H:%M:%S')
    cur = get_db().cursor()
    cur.execute("SELECT phone FROM users WHERE role='headteacher' AND status=1 LIMIT 1")
    headteacher = cur.fetchone()
    cur.close()
    if headteacher and headteacher[0]:
        send_sms(headteacher[0], f"NEW LINK: Payroll {payroll[1]} - UGX {payroll[4]:,.2f}. Code: {payroll[5]}. Expires: {expires_str}. Link: {approval_link}")
    flash(f'New approval link sent! Expires at {expires_str}.', 'success')
    return redirect(url_for('headteacher_approvals'))

@app.route('/headteacher/view_payroll/<int:payroll_id>')
def headteacher_view_payroll(payroll_id):
    if not check_permission(['headteacher']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM payroll WHERE id=?", (payroll_id,))
    payroll = cur.fetchone()
    if not payroll:
        flash('Payroll not found.', 'danger')
        return redirect(url_for('headteacher_approvals'))
    cur.execute("SELECT sp.*, s.full_name, s.position FROM salary_payments sp JOIN staff s ON sp.staff_id = s.id WHERE sp.payroll_id=?", (payroll_id,))
    staff_list = cur.fetchall()
    cur.close()
    return render_template('headteacher/view_payroll.html', payroll=payroll, staff_list=staff_list)
@app.route('/headteacher/students')
def headteacher_students():
    if not check_permission(['headteacher']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    
    # Get all students with their details
    cur.execute("""
        SELECT student_id, full_name, class, parent_phone, admission_status, fees_balance 
        FROM students 
        WHERE admission_status = 'approved'
        ORDER BY class, full_name
    """)
    students = cur.fetchall()
    
    # Get distinct classes for filtering
    cur.execute("SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != '' ORDER BY class")
    rows = cur.fetchall()
    classes = []
    for row in rows:
        if isinstance(row, dict):
            classes.append(row.get('class'))
        else:
            classes.append(row[0])
    
    cur.close()
    return render_template('headteacher/students.html', students=students, classes=classes)

@app.route('/headteacher/update_comment', methods=['POST'])
def headteacher_update_comment():
    if not check_permission(['headteacher']):
        abort(403)
    student_id = request.form['student_id']
    term = request.form['term']
    year = request.form['year']
    comment = request.form.get('comment', '').strip()
    custom_comment = request.form.get('custom_comment', '').strip()
    final_comment = custom_comment if custom_comment else comment
    cur = get_db().cursor()
    cur.execute("SELECT headteacher_comment_locked FROM teacher_comments WHERE student_id=? AND term=? AND year=?", (student_id, term, year))
    existing = cur.fetchone()
    cur.close()
    if existing and existing[0] == 1:
        flash('Comment cannot be edited as it has been locked.', 'danger')
        return redirect(url_for('teacher_report_card', student_id=student_id, term=term, year=year))
    execute_db("INSERT INTO teacher_comments (student_id, term, year, headteacher_comment, headteacher_comment_locked) VALUES (?, ?, ?, ?, 1) ON CONFLICT(student_id, term, year) DO UPDATE SET headteacher_comment=?, headteacher_comment_locked=1",
               (student_id, term, year, final_comment, final_comment))
    flash('Headteacher comment saved and locked.', 'success')
    return redirect(url_for('teacher_report_card', student_id=student_id, term=term, year=year))

@app.route('/management/pending')
def management_pending_authorizations():
    if not check_permission(['management']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("""SELECT p.*, COUNT(sp.id) as staff_count FROM payroll p LEFT JOIN salary_payments sp ON p.id = sp.payroll_id 
                   WHERE p.management_approval_status = 'pending' AND p.approval_status = 'approved' GROUP BY p.id ORDER BY p.created_at DESC""")
    pending = cur.fetchall()
    cur.close()
    return render_template('management/pending.html', pending=pending)

@app.route('/management/authorization/<token>', methods=['GET', 'POST'])
def management_authorization_access(token):
    if not check_permission(['management']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM payroll WHERE management_access_token=? AND management_approval_status='pending' AND approval_status='approved'", (token,))
    payroll = cur.fetchone()
    if not payroll:
        flash('Invalid authorization link.', 'danger')
        return redirect(url_for('management_pending_authorizations'))
    if payroll['management_approval_status'] != 'pending':
        flash(f'This authorization has already been {payroll["management_approval_status"]}.', 'warning')
        return redirect(url_for('management_pending_authorizations'))
    if payroll['approval_status'] != 'approved':
        flash('Payroll has not been approved by Headteacher yet.', 'warning')
        return redirect(url_for('management_pending_authorizations'))
    if payroll.get('management_token_expires_at') and payroll['management_token_expires_at'] <= datetime.now():
        flash('This authorization link has expired. Please request a new link.', 'danger')
        return redirect(url_for('management_pending_authorizations'))
    if request.method == 'POST':
        auth_code = request.form.get('auth_code')
        action = request.form.get('action')
        if payroll['management_approval_code'] != auth_code:
            flash('Invalid authorization code.', 'danger')
            return redirect(url_for('management_authorization_access', token=token))
        if action == 'authorize':
            result = process_bank_payment(payroll)
            if result['success']:
                cur.execute("""UPDATE payroll SET management_approval_status='approved', management_approved_by='Management', 
                               management_approved_at=CURRENT_TIMESTAMP, bank_authorization_token=?, bank_transaction_ref=?, 
                               bank_payment_status='completed' WHERE id=?""", (result['token'], result['reference'], payroll['id']))
                cur.execute("UPDATE salary_payments SET approval_status='paid', payment_date=DATE('now'), transaction_ref=? WHERE payroll_id=?", 
                           (result['reference'], payroll['id']))
                db.commit()
                add_notification('bursar', f"Payroll {payroll['payroll_no']} has been paid. Reference: {result['reference']}", '/bursar/payroll/list')
                flash(f'Payment authorized and processed! Reference: {result["reference"]}', 'success')
            else:
                cur.execute("UPDATE payroll SET bank_payment_status='failed', bank_payment_response=? WHERE id=?", (result['error'], payroll['id']))
                db.commit()
                flash(f'Payment failed: {result["error"]}', 'danger')
        elif action == 'reject':
            cur.execute("UPDATE payroll SET management_approval_status='rejected', management_approved_by='Management', management_approved_at=CURRENT_TIMESTAMP WHERE id=?", (payroll['id'],))
            cur.execute("UPDATE salary_payments SET approval_status='rejected' WHERE payroll_id=?", (payroll['id'],))
            db.commit()
            add_notification('headteacher', f"Payroll {payroll['payroll_no']} authorization was REJECTED by Management.", '/headteacher/approvals')
            add_notification('bursar', f"Payroll {payroll['payroll_no']} was REJECTED by Management.", '/bursar/payroll/list')
            flash('Payment authorization rejected.', 'warning')
        cur.close()
        return redirect(url_for('management_pending_authorizations'))
    
    remaining_minutes = None
    if payroll.get('management_token_expires_at'):
        remaining = payroll['management_token_expires_at'] - datetime.now()
        remaining_minutes = int(remaining.total_seconds() / 60)
    cur.close()
    return render_template('management/authorize_payment_secure.html', payroll=payroll, remaining_minutes=remaining_minutes)

@app.route('/management/view_payroll/<int:payroll_id>')
def management_view_payroll(payroll_id):
    if not check_permission(['management']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT * FROM payroll WHERE id=?", (payroll_id,))
    payroll = cur.fetchone()
    if not payroll:
        flash('Payroll not found.', 'danger')
        return redirect(url_for('management_pending_authorizations'))
    cur.execute("""SELECT sp.*, s.full_name, s.position, s.bank_account, s.bank_name, s.phone, s.nssf_number, s.tin_number
                   FROM salary_payments sp JOIN staff s ON sp.staff_id = s.id WHERE sp.payroll_id = ?""", (payroll_id,))
    staff_list = cur.fetchall()
    cur.close()
    return render_template('management/view_payroll.html', payroll=payroll, staff_list=staff_list)

@app.route('/management/reject_authorization/<int:payroll_id>')
def management_reject_authorization(payroll_id):
    if not check_permission(['management']):
        abort(403)
    cur = get_db().cursor()
    cur.execute("SELECT * FROM payroll WHERE id=? AND management_approval_status='pending' AND approval_status='approved'", (payroll_id,))
    payroll = cur.fetchone()
    cur.close()
    if not payroll:
        flash('Payroll not found or already processed.', 'danger')
        return redirect(url_for('management_pending_authorizations'))
    try:
        execute_db("UPDATE payroll SET management_approval_status='rejected', management_approved_by='Management', management_approved_at=CURRENT_TIMESTAMP WHERE id=?", (payroll_id,))
        execute_db("UPDATE salary_payments SET approval_status='rejected' WHERE payroll_id=?", (payroll_id,))
        add_notification('headteacher', f"Payroll {payroll[1]} authorization has been REJECTED by Management.", '/headteacher/approvals')
        add_notification('bursar', f"Payroll {payroll[1]} authorization has been REJECTED by Management.", '/bursar/payroll/list')
        flash(f'Payroll {payroll[1]} authorization has been rejected.', 'warning')
    except Exception as e:
        flash(f'Error rejecting authorization: {str(e)}', 'danger')
    return redirect(url_for('management_pending_authorizations'))

@app.route('/management/resend_token/<int:payroll_id>')
def management_resend_token(payroll_id):
    if not check_permission(['management']):
        abort(403)
    cur = get_db().cursor()
    cur.execute("SELECT * FROM payroll WHERE id=? AND management_approval_status='pending' AND approval_status='approved'", (payroll_id,))
    payroll = cur.fetchone()
    cur.close()
    if not payroll:
        flash('Payroll not found or already authorized.', 'danger')
        return redirect(url_for('management_pending_authorizations'))
    if payroll.get('token_resend_count', 0) >= 3:
        flash('Maximum token resend limit reached (3). Please contact headteacher.', 'danger')
        return redirect(url_for('management_pending_authorizations'))
    new_token, new_expires = generate_secure_token(2)
    execute_db("UPDATE payroll SET management_access_token=?, management_token_expires_at=?, token_resend_count=token_resend_count+1, last_resend_at=CURRENT_TIMESTAMP WHERE id=?",
               (new_token, new_expires, payroll_id))
    auth_link = url_for('management_authorization_access', token=new_token, _external=True)
    expires_str = new_expires.strftime('%Y-%m-%d %H:%M:%S')
    cur = get_db().cursor()
    cur.execute("SELECT phone FROM users WHERE role='management' AND status=1 LIMIT 1")
    management_user = cur.fetchone()
    cur.close()
    if management_user and management_user[0]:
        send_sms(management_user[0], f"NEW LINK: Authorize Payroll {payroll[1]} - UGX {payroll[4]:,.2f}. Code: {payroll[8]}. Expires: {expires_str}. Link: {auth_link}")
    flash(f'New authorization link sent! Expires at {expires_str}.', 'success')
    return redirect(url_for('management_pending_authorizations'))

# ==================== INVENTORY MODULE ====================
def generate_item_code(category_name):
    prefix = category_name[:3].upper()
    year = datetime.now().strftime("%Y")
    cur = get_db().cursor()
    cur.execute("SELECT item_code FROM inventory_items WHERE item_code LIKE ? ORDER BY item_code DESC LIMIT 1", (f'{prefix}-{year}-%',))
    last = cur.fetchone()
    cur.close()
    if last:
        last_num = int(last[0].split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1
    return f"{prefix}-{year}-{new_num:04d}"

def check_low_stock_alerts():
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("""SELECT i.*, c.name as category_name, c.warning_level FROM inventory_items i 
                   JOIN inventory_categories c ON i.category_id = c.id WHERE i.quantity <= i.reorder_level AND i.status = 'working'""")
    low_stock_items = cur.fetchall()
    for item in low_stock_items:
        cur.execute("SELECT id FROM inventory_alerts WHERE item_id=? AND alert_type='low_stock' AND is_read=0", (item['id'],))
        existing = cur.fetchone()
        if not existing:
            execute_db("INSERT INTO inventory_alerts (item_id, alert_type, message) VALUES (?, 'low_stock', ?)",
                       (item['id'], f"Stock for {item['name']} is low! Current: {item['quantity']}, Reorder level: {item['reorder_level']}"))
            add_notification('stores_keeper', f"LOW STOCK ALERT: {item['name']} has only {item['quantity']} {item['unit']} left!", '/inventory/items')
            add_notification('admin', f"LOW STOCK ALERT: {item['name']} needs reordering!", '/inventory/items')
            add_notification('bursar', f"LOW STOCK ALERT: {item['name']} needs reordering!", '/inventory/items')
    cur.close()

@app.route('/inventory/dashboard')
def inventory_dashboard():
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) as total_items FROM inventory_items")
    total_items = cur.fetchone()
    cur.execute("SELECT COUNT(*) as low_stock FROM inventory_items WHERE quantity <= reorder_level AND status='working'")
    low_stock = cur.fetchone()
    cur.execute("SELECT COUNT(*) as spoilt FROM inventory_items WHERE status='spoilt'")
    spoilt = cur.fetchone()
    cur.execute("SELECT COUNT(*) as under_repair FROM inventory_items WHERE status='under_repair'")
    under_repair = cur.fetchone()
    cur.execute("SELECT SUM(quantity) as total_quantity FROM inventory_items WHERE status='working'")
    total_quantity = cur.fetchone()
    cur.execute("SELECT SUM(current_value) as total_value FROM inventory_items")
    total_value = cur.fetchone()
    cur.execute("""SELECT t.*, i.name as item_name, i.item_code FROM inventory_transactions t 
                   JOIN inventory_items i ON t.item_id = i.id ORDER BY t.created_at DESC LIMIT 10""")
    recent_transactions = cur.fetchall()
    cur.execute("""SELECT a.*, i.name as item_name, i.quantity, i.reorder_level FROM inventory_alerts a 
                   JOIN inventory_items i ON a.item_id = i.id WHERE a.is_read = 0 ORDER BY a.created_at DESC""")
    alerts = cur.fetchall()
    cur.close()
    return render_template('inventory/dashboard.html', total_items=total_items, low_stock=low_stock, spoilt=spoilt,
                          under_repair=under_repair, total_quantity=total_quantity, total_value=total_value,
                          recent_transactions=recent_transactions, alerts=alerts)

@app.route('/inventory/items')
def inventory_items():
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    category = request.args.get('category', '')
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    db = get_db_dict()
    cur = db.cursor()
    query = """SELECT i.*, c.name as category_name FROM inventory_items i JOIN inventory_categories c ON i.category_id = c.id WHERE 1=1"""
    params = []
    if category:
        query += " AND c.name = ?"
        params.append(category)
    if status:
        query += " AND i.status = ?"
        params.append(status)
    if search:
        query += " AND (i.name LIKE ? OR i.item_code LIKE ?)"
        pattern = f"%{search}%"
        params.extend([pattern, pattern])
    query += " ORDER BY i.category_id, i.name"
    cur.execute(query, params)
    items = cur.fetchall()
    cur.execute("SELECT * FROM inventory_categories ORDER BY name")
    categories = cur.fetchall()
    cur.close()
    return render_template('inventory/items.html', items=items, categories=categories, category=category, status=status, search=search)

@app.route('/inventory/item/add', methods=['GET', 'POST'])
def inventory_item_add():
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    
    db = get_db_dict()
    cur = db.cursor()
    
    if request.method == 'POST':
        try:
            category_id = request.form.get('category_id')
            if not category_id:
                flash('Please select a category.', 'danger')
                return redirect(url_for('inventory_item_add'))
            
            name = request.form.get('name', '').strip()
            if not name:
                flash('Item name is required.', 'danger')
                return redirect(url_for('inventory_item_add'))
            
            unit = request.form.get('unit', 'pieces')
            
            # Handle numeric values with defaults
            try:
                quantity = int(request.form.get('quantity', 0))
            except:
                quantity = 0
            
            try:
                minimum_quantity = int(request.form.get('minimum_quantity', 10))
            except:
                minimum_quantity = 10
            
            try:
                reorder_level = int(request.form.get('reorder_level', 5))
            except:
                reorder_level = 5
            
            location = request.form.get('location', '')
            supplier = request.form.get('supplier', '')
            
            # Handle purchase price - convert empty string to 0
            purchase_price_str = request.form.get('purchase_price', '0')
            try:
                purchase_price = float(purchase_price_str) if purchase_price_str else 0
            except:
                purchase_price = 0
            
            current_value = quantity * purchase_price
            status = request.form.get('status', 'working')
            responsible_person = request.form.get('responsible_person', '')
            responsible_role = request.form.get('responsible_role', '')
            
            # Get category name for item code
            cur.execute("SELECT name FROM inventory_categories WHERE id=?", (category_id,))
            category = cur.fetchone()
            if not category:
                flash('Invalid category selected.', 'danger')
                return redirect(url_for('inventory_item_add'))
            
            # Generate item code
            prefix = category['name'][:3].upper()
            year = datetime.now().strftime("%Y")
            cur.execute("SELECT item_code FROM inventory_items WHERE item_code LIKE ? ORDER BY item_code DESC LIMIT 1", (f'{prefix}-{year}-%',))
            last = cur.fetchone()
            if last:
                last_num = int(last['item_code'].split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            item_code = f"{prefix}-{year}-{new_num:04d}"
            
            # Handle image upload
            image_file = request.files.get('image')
            image_path = None
            if image_file and image_file.filename:
                if allowed_file(image_file.filename, ALLOWED_IMAGE_EXTENSIONS):
                    filename = secure_filename(f"item_{item_code}_{image_file.filename}")
                    image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image_path = filename
            
            cur.execute("""
                INSERT INTO inventory_items 
                (item_code, name, category_id, unit, quantity, minimum_quantity, reorder_level, 
                 location, supplier, purchase_price, current_value, status, responsible_person, 
                 responsible_role, image_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (item_code, name, category_id, unit, quantity, minimum_quantity, reorder_level,
                  location, supplier, purchase_price, current_value, status, responsible_person,
                  responsible_role, image_path))
            
            item_id = cur.lastrowid
            
            # Record initial stock transaction
            cur.execute("""
                INSERT INTO inventory_transactions 
                (item_id, transaction_type, quantity, unit_price, total_amount, transaction_date, recorded_by, notes)
                VALUES (?, 'purchase', ?, ?, ?, DATE('now'), ?, 'Initial stock')
            """, (item_id, quantity, purchase_price, current_value, session.get('username')))
            
            db.commit()
            flash(f'Item {name} added successfully. Code: {item_code}', 'success')
            
        except Exception as e:
            db.rollback()
            flash(f'Error: {str(e)}', 'danger')
            import traceback
            traceback.print_exc()
        finally:
            cur.close()
        
        return redirect(url_for('inventory_items'))
    
    # GET request - show form
    cur.execute("SELECT * FROM inventory_categories ORDER BY name")
    categories = cur.fetchall()
    cur.close()
    return render_template('inventory/item_add.html', categories=categories)

@app.route('/inventory/item/edit/<int:item_id>', methods=['GET', 'POST'])
def inventory_item_edit(item_id):
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    if request.method == 'POST':
        name = request.form['name']
        unit = request.form['unit']
        minimum_quantity = int(request.form.get('minimum_quantity', 0))
        reorder_level = int(request.form.get('reorder_level', 5))
        location = request.form.get('location', '')
        supplier = request.form.get('supplier', '')
        status = request.form.get('status', 'working')
        responsible_person = request.form.get('responsible_person', '')
        responsible_role = request.form.get('responsible_role', '')
        execute_db("""UPDATE inventory_items SET name=?, unit=?, minimum_quantity=?, reorder_level=?, location=?, supplier=?, status=?,
                       responsible_person=?, responsible_role=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                   (name, unit, minimum_quantity, reorder_level, location, supplier, status, responsible_person, responsible_role, item_id))
        flash('Item updated successfully.', 'success')
        return redirect(url_for('inventory_items'))
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT i.*, c.name as category_name FROM inventory_items i JOIN inventory_categories c ON i.category_id = c.id WHERE i.id=?", (item_id,))
    item = cur.fetchone()
    cur.execute("SELECT * FROM inventory_categories ORDER BY name")
    categories = cur.fetchall()
    cur.close()
    return render_template('inventory/item_edit.html', item=item, categories=categories)

@app.route('/inventory/issue/<int:item_id>', methods=['POST'])
def inventory_issue_item(item_id):
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    quantity = int(request.form['quantity'])
    issued_to = request.form['issued_to']
    issued_to_role = request.form['issued_to_role']
    purpose = request.form['purpose']
    notes = request.form.get('notes', '')
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT name, quantity, current_value, unit FROM inventory_items WHERE id=?", (item_id,))
    item = cur.fetchone()
    if not item:
        flash('Item not found.', 'danger')
        return redirect(url_for('inventory_items'))
    if item['quantity'] < quantity:
        flash(f'Insufficient stock! Available: {item["quantity"]} {item["unit"]}', 'danger')
        return redirect(url_for('inventory_items'))
    new_quantity = item['quantity'] - quantity
    cur.execute("UPDATE inventory_items SET quantity=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_quantity, item_id))
    cur.execute("""INSERT INTO inventory_transactions (item_id, transaction_type, quantity, transaction_date, issued_to, issued_to_role, purpose, notes, recorded_by)
                   VALUES (?, 'issued', ?, DATE('now'), ?, ?, ?, ?, ?)""",
               (item_id, quantity, issued_to, issued_to_role, purpose, notes, session.get('username')))
    db.commit()
    cur.close()
    check_low_stock_alerts()
    flash(f'{quantity} {item["unit"]} of {item["name"]} issued to {issued_to}.', 'success')
    return redirect(url_for('inventory_items'))

@app.route('/inventory/receive/<int:item_id>', methods=['POST'])
def inventory_receive_item(item_id):
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    quantity = int(request.form['quantity'])
    unit_price = float(request.form.get('unit_price', 0))
    supplier = request.form.get('supplier', '')
    notes = request.form.get('notes', '')
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT name, quantity, current_value, unit FROM inventory_items WHERE id=?", (item_id,))
    item = cur.fetchone()
    if not item:
        flash('Item not found.', 'danger')
        return redirect(url_for('inventory_items'))
    new_quantity = item['quantity'] + quantity
    total_amount = quantity * unit_price
    new_value = item['current_value'] + total_amount
    cur.execute("UPDATE inventory_items SET quantity=?, current_value=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_quantity, new_value, item_id))
    cur.execute("""INSERT INTO inventory_transactions (item_id, transaction_type, quantity, unit_price, total_amount, transaction_date, supplier, notes, recorded_by)
                   VALUES (?, 'received', ?, ?, ?, DATE('now'), ?, ?, ?)""",
               (item_id, quantity, unit_price, total_amount, supplier, notes, session.get('username')))
    db.commit()
    cur.execute("UPDATE inventory_alerts SET is_read=1 WHERE item_id=? AND alert_type='low_stock'", (item_id,))
    db.commit()
    cur.close()
    flash(f'{quantity} {item["unit"]} of {item["name"]} received.', 'success')
    return redirect(url_for('inventory_items'))

@app.route('/inventory/update_status/<int:item_id>', methods=['POST'])
def inventory_update_status(item_id):
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    status = request.form['status']
    condition_notes = request.form.get('condition_notes', '')
    quantity_affected = int(request.form.get('quantity_affected', 0))
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("SELECT name, quantity FROM inventory_items WHERE id=?", (item_id,))
    item = cur.fetchone()
    if not item:
        flash('Item not found.', 'danger')
        return redirect(url_for('inventory_items'))
    if status in ['spoilt', 'used_up'] and quantity_affected > 0:
        new_quantity = item['quantity'] - quantity_affected
        cur.execute("UPDATE inventory_items SET quantity=?, status=?, condition_notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", 
                   (new_quantity, status, condition_notes, item_id))
        cur.execute("INSERT INTO inventory_transactions (item_id, transaction_type, quantity, notes, recorded_by) VALUES (?, ?, ?, ?, ?)",
                   (item_id, status, quantity_affected, condition_notes, session.get('username')))
    else:
        cur.execute("UPDATE inventory_items SET status=?, condition_notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", 
                   (status, condition_notes, item_id))
    db.commit()
    cur.close()
    flash(f'Item status updated to {status}.', 'success')
    return redirect(url_for('inventory_items'))

@app.route('/inventory/transactions')
def inventory_transactions():
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    
    item_id = request.args.get('item_id', '')
    db = get_db_dict()
    cur = db.cursor()
    
    if item_id:
        cur.execute("""
            SELECT t.*, i.name as item_name, i.item_code
            FROM inventory_transactions t
            JOIN inventory_items i ON t.item_id = i.id
            WHERE t.item_id = ?
            ORDER BY t.created_at DESC
        """, (item_id,))
    else:
        cur.execute("""
            SELECT t.*, i.name as item_name, i.item_code
            FROM inventory_transactions t
            JOIN inventory_items i ON t.item_id = i.id
            ORDER BY t.created_at DESC
        """)
    
    transactions = cur.fetchall()
    
    cur.execute("SELECT id, name, item_code FROM inventory_items ORDER BY name")
    items = cur.fetchall()
    cur.close()
    
    return render_template('inventory/transactions.html', 
                          transactions=transactions, 
                          items=items, 
                          selected_item=item_id)

@app.route('/inventory/alerts')
def inventory_alerts():
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    db = get_db_dict()
    cur = db.cursor()
    cur.execute("""SELECT a.*, i.name as item_name, i.quantity, i.reorder_level, i.unit FROM inventory_alerts a 
                   JOIN inventory_items i ON a.item_id = i.id WHERE a.is_read = 0 ORDER BY a.created_at DESC""")
    alerts = cur.fetchall()
    cur.close()
    return render_template('inventory/alerts.html', alerts=alerts)

@app.route('/inventory/alert/read/<int:alert_id>')
def inventory_alert_read(alert_id):
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    execute_db("UPDATE inventory_alerts SET is_read=1 WHERE id=?", (alert_id,))
    flash('Alert acknowledged.', 'success')
    return redirect(url_for('inventory_alerts'))

@app.route('/inventory/reports')
def inventory_reports():
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    
    # Initialize all variables with default values
    by_category = []
    by_status = []
    low_stock_items = []
    recent_issues = []
    total_items = 0
    total_quantity = 0
    low_stock_count = 0
    total_value = 0
    
    try:
        db = get_db()
        cur = db.cursor()
        
        # Total items
        cur.execute("SELECT COUNT(*) FROM inventory_items")
        row = cur.fetchone()
        total_items = row[0] if row else 0
        
        # Total quantity
        cur.execute("SELECT SUM(quantity) FROM inventory_items WHERE status='working'")
        row = cur.fetchone()
        total_quantity = row[0] if row and row[0] else 0
        
        # Low stock count
        cur.execute("SELECT COUNT(*) FROM inventory_items WHERE quantity <= reorder_level AND status='working'")
        row = cur.fetchone()
        low_stock_count = row[0] if row else 0
        
        # Total value
        cur.execute("SELECT SUM(current_value) FROM inventory_items")
        row = cur.fetchone()
        total_value = row[0] if row and row[0] else 0
        
        # Stock by category
        cur.execute("""
            SELECT c.name, COUNT(i.id), SUM(i.quantity), SUM(i.current_value)
            FROM inventory_categories c
            LEFT JOIN inventory_items i ON c.id = i.category_id
            GROUP BY c.id
        """)
        rows = cur.fetchall()
        for row in rows:
            by_category.append({
                'category': row[0] or 'Unknown',
                'item_count': row[1] or 0,
                'total_quantity': row[2] or 0,
                'total_value': row[3] or 0
            })
        
        # Stock by status
        cur.execute("SELECT status, COUNT(*), SUM(quantity) FROM inventory_items GROUP BY status")
        rows = cur.fetchall()
        for row in rows:
            by_status.append({
                'status': row[0] or 'Unknown',
                'count': row[1] or 0,
                'quantity': row[2] or 0
            })
        
        # Low stock items
        cur.execute("""
            SELECT i.id, i.item_code, i.name, i.quantity, i.reorder_level, i.unit, c.name
            FROM inventory_items i
            LEFT JOIN inventory_categories c ON i.category_id = c.id
            WHERE i.quantity <= i.reorder_level AND i.status = 'working'
            ORDER BY i.quantity ASC
        """)
        rows = cur.fetchall()
        for row in rows:
            low_stock_items.append({
                'id': row[0],
                'item_code': row[1],
                'name': row[2],
                'quantity': row[3],
                'reorder_level': row[4],
                'unit': row[5],
                'category_name': row[6] or 'Unknown'
            })
        
        # Recent issues
        cur.execute("""
            SELECT t.transaction_date, t.quantity, t.issued_to, t.purpose, t.recorded_by, i.name
            FROM inventory_transactions t
            LEFT JOIN inventory_items i ON t.item_id = i.id
            WHERE t.transaction_type = 'issued'
            ORDER BY t.created_at DESC LIMIT 20
        """)
        rows = cur.fetchall()
        for row in rows:
            recent_issues.append({
                'transaction_date': row[0],
                'quantity': row[1],
                'issued_to': row[2],
                'purpose': row[3],
                'recorded_by': row[4],
                'item_name': row[5] or 'Unknown'
            })
        
        cur.close()
        
    except Exception as e:
        print(f"Error in inventory_reports: {str(e)}")
        flash(f'Error loading reports: {str(e)}', 'danger')
    
    return render_template('inventory/reports.html',
                          by_category=by_category,
                          by_status=by_status,
                          low_stock_items=low_stock_items,
                          recent_issues=recent_issues,
                          total_items=total_items,
                          total_quantity=total_quantity,
                          low_stock_count=low_stock_count,
                          total_value=total_value)

@app.route('/inventory/print_report')
def inventory_print_report():
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    category = request.args.get('category', '')
    db = get_db_dict()
    cur = db.cursor()
    if category:
        cur.execute("SELECT i.*, c.name as category_name FROM inventory_items i JOIN inventory_categories c ON i.category_id = c.id WHERE c.name = ? ORDER BY i.name", (category,))
    else:
        cur.execute("SELECT i.*, c.name as category_name FROM inventory_items i JOIN inventory_categories c ON i.category_id = c.id ORDER BY c.name, i.name")
    items = cur.fetchall()
    cur.close()
    return render_template('inventory/print_report.html', items=items, category=category)

@app.route('/inventory/alert/count')
def inventory_alert_count():
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        return jsonify({'count': 0})
    cur = get_db().cursor()
    cur.execute("SELECT COUNT(*) FROM inventory_alerts WHERE is_read = 0")
    count = cur.fetchone()[0]
    cur.close()
    return jsonify({'count': count})

# ==================== UPLOADS & MISC ====================
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ==================== MOBILE API ENDPOINTS ====================
@app.route('/mobile/login', methods=['POST'])
def mobile_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    cur = get_db().cursor()
    cur.execute("SELECT id, username, role, status FROM users WHERE username=? AND password=?", (username, password))
    user = cur.fetchone()
    cur.close()
    if user and user[3] == 1:
        token, _ = generate_secure_token()
        return jsonify({'success': True, 'token': token, 'role': user[2], 'username': user[1]})
    return jsonify({'success': False, 'message': 'Invalid credentials'})

@app.route('/mobile/dashboard', methods=['GET'])
def mobile_dashboard():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    role = session.get('role')
    if role == 'admin':
        cur = get_db().cursor()
        cur.execute("SELECT COUNT(*) as total_users FROM users")
        users = cur.fetchone()
        cur.execute("SELECT COUNT(*) as total_students FROM students")
        students = cur.fetchone()
        cur.close()
        return jsonify({'total_users': users[0] if users else 0, 'total_students': students[0] if students else 0})
    return jsonify({})


@app.route('/debug_db')
def debug_db():
    import sqlite3
    conn = sqlite3.connect('school_system.db')
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, status FROM users")
    users = cur.fetchall()
    conn.close()
    
    if not users:
        return "No users found in database!"
    
    result = "<h2>Users in Database:</h2>"
    for u in users:
        result += f"<p>ID: {u[0]}, Username: {u[1]}, Role: {u[2]}, Status: {u[3]}</p>"
    result += "<br><a href='/login'>Go to Login</a>"
    return result

@app.route('/force_admin')
def force_admin():
    import sqlite3
    from werkzeug.security import generate_password_hash
    
    conn = sqlite3.connect('school_system.db')
    cur = conn.cursor()
    
    cur.execute("DELETE FROM users WHERE username = 'admin'")
    hashed = generate_password_hash('admin123')
    cur.execute("INSERT INTO users (username, password, role, status, phone, must_change_password) VALUES (?, ?, 'admin', 1, '0700000000', 0)", ('admin', hashed))
    
    conn.commit()
    conn.close()
    
    return "Admin created! Username: admin, Password: admin123. <a href='/login'>Login here</a>"

if __name__ == '__main__':
    app.run(debug=True)
