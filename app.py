import os
import re
import math
import io
import csv
import json
import time
import secrets
import random
import string
import pandas as pd
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_from_directory, jsonify
from flask_mysqldb import MySQL
from werkzeug.utils import secure_filename
from functools import wraps
from markupsafe import escape
from MySQLdb.cursors import DictCursor

# ==================== APP CONFIGURATION ====================
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'school_system'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
mysql = MySQL(app)


# ==================== HELPER FUNCTIONS ====================
def allowed_file(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set

def check_permission(allowed_roles):
    return 'role' in session and session.get('role') in allowed_roles

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

@app.context_processor
def inject_notifications():
    """Make notifications available to all templates"""
    if 'user_id' in session:
        role = session.get('role')
        if role in ['headteacher', 'bursar', 'management', 'admin']:
            notification_count = get_notification_count(role)
            notifications = get_notifications(role, limit=5)
            return {
                'notification_count': notification_count,
                'notifications': notifications
            }
    return {
        'notification_count': 0,
        'notifications': []
    }

def get_photo_url(photo_path):
    """Return proper photo URL, handling None and default_avatar.png"""
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

def generate_unique_number(prefix, table, column, year_format=True):
    year = datetime.now().strftime("%Y%m") if year_format else ""
    cur = mysql.connection.cursor()
    cur.execute(f"SELECT {column} FROM {table} WHERE {column} LIKE %s ORDER BY {column} DESC LIMIT 1", (f'{prefix}-{year}-%' if year_format else f'{prefix}-%',))
    last = cur.fetchone()
    cur.close()
    if last:
        last_num = int(last[0].split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1
    return f"{prefix}-{year}-{new_num:04d}" if year_format else f"{prefix}-{new_num:04d}"

def generate_approval_code():
    return ''.join(random.choices('0123456789', k=6))

def send_sms(phone_number, message):
    print(f"[SMS] To: {phone_number} | {message}")
    return True

def add_notification(user_role, message, link=None):
    cur = mysql.connection.cursor()
    cur.execute("INSERT INTO notifications (user_role, message, link, is_read, created_at) VALUES (%s, %s, %s, 0, NOW())", (user_role, message, link))
    mysql.connection.commit()
    cur.close()

# Grading Helpers
def get_grade_and_descriptor(score):
    cur = mysql.connection.cursor()
    cur.execute("SELECT grade, descriptor FROM grading_system WHERE %s BETWEEN min_score AND max_score LIMIT 1", (score,))
    result = cur.fetchone()
    cur.close()
    if result:
        return result[0], result[1]
    return 'N/A', 'No grade defined'

def get_descriptor_by_identifier(identifier):
    cur = mysql.connection.cursor()
    cur.execute("SELECT descriptor FROM identifier_grading WHERE %s BETWEEN min_value AND max_value LIMIT 1", (identifier,))
    result = cur.fetchone()
    cur.close()
    if result:
        return result[0]
    return 'No descriptor defined'

def get_alevel_grade_and_points(score, is_subsidiary=False):
    if score is None:
        return 'N/A', 0
    if is_subsidiary:
        points = 1 if score >= 50 else 0
        grade = 'Pass' if points == 1 else 'Fail'
        return grade, points
    cur = mysql.connection.cursor()
    cur.execute("SELECT grade, points FROM alevel_grading WHERE %s BETWEEN min_score AND max_score AND is_subsidiary=0 LIMIT 1", (score,))
    result = cur.fetchone()
    cur.close()
    if result:
        return result[0], result[1]
    return 'E', 1

def generate_secure_token(hours=2):
    """Generate a secure random token with expiration"""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=hours)
    return token, expires_at

# Teacher Assignment Helpers
def get_user_assignments(user_id=None):
    if user_id is None:
        user_id = session.get('user_id')
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT * FROM teacher_class_assignments WHERE user_id = %s ORDER BY assignment_type, class_name, subject", (user_id,))
    assignments = cur.fetchall()
    cur.close()
    return assignments

def get_user_classes(user_id=None, assignment_type=None):
    if user_id is None:
        user_id = session.get('user_id')
    cur = mysql.connection.cursor(DictCursor)
    if assignment_type:
        cur.execute("SELECT DISTINCT class_name FROM teacher_class_assignments WHERE user_id = %s AND assignment_type = %s ORDER BY class_name", (user_id, assignment_type))
    else:
        cur.execute("SELECT DISTINCT class_name FROM teacher_class_assignments WHERE user_id = %s ORDER BY class_name", (user_id,))
    classes = [row['class_name'] for row in cur.fetchall()]
    cur.close()
    return classes

# Add this helper function (if not already present)
def add_notification(user_role, message, link=None):
    """Add a notification for a specific user role"""
    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO notifications (user_role, message, link, is_read, created_at)
        VALUES (%s, %s, %s, 0, NOW())
    """, (user_role, message, link))
    mysql.connection.commit()
    cur.close()

def get_notifications(user_role, limit=10):
    """Get unread notifications for a user role"""
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("""
        SELECT * FROM notifications 
        WHERE user_role = %s AND is_read = 0
        ORDER BY created_at DESC LIMIT %s
    """, (user_role, limit))
    notifications = cur.fetchall()
    cur.close()
    return notifications

def get_notification_count(user_role):
    """Get count of unread notifications for a user role"""
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM notifications 
        WHERE user_role = %s AND is_read = 0
    """, (user_role,))
    count = cur.fetchone()[0]
    cur.close()
    return count

def mark_notification_read(notification_id):
    """Mark a specific notification as read"""
    cur = mysql.connection.cursor()
    cur.execute("UPDATE notifications SET is_read = 1 WHERE id = %s", (notification_id,))
    mysql.connection.commit()
    cur.close()

def mark_all_notifications_read(user_role):
    """Mark all notifications for a user role as read"""
    cur = mysql.connection.cursor()
    cur.execute("UPDATE notifications SET is_read = 1 WHERE user_role = %s", (user_role,))
    mysql.connection.commit()
    cur.close()

# Add route to mark notification as read
@app.route('/notification/mark_read/<int:notification_id>')
@login_required
def mark_notification_read_route(notification_id):
    role = session.get('role')
    mark_notification_read(notification_id)
    return redirect(request.referrer or url_for('dashboard'))

# Add route to mark all notifications as read
@app.route('/notification/mark_all_read')
@login_required
def mark_all_notifications_read_route():
    role = session.get('role')
    mark_all_notifications_read(role)
    flash('All notifications marked as read.', 'success')
    return redirect(request.referrer or url_for('dashboard'))

def assign_user_to_class(user_id, class_name, subject=None, assignment_type='subject_teacher'):
    cur = mysql.connection.cursor()
    cur.execute("""INSERT INTO teacher_class_assignments (user_id, class_name, subject, assignment_type, assigned_by)
                   VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE subject = VALUES(subject), assigned_by = VALUES(assigned_by)""",
                (user_id, class_name, subject, assignment_type, session.get('username', 'admin')))
    mysql.connection.commit()
    cur.close()

# Marks Processing (Unified for both O-Level and A-Level)
def process_marks_upload(file, subject, term, year, assigned_class, teacher_id, level='olevel', is_subsidiary=False):
    try:
        df = pd.read_excel(file)
    except:
        flash('Error reading Excel file', 'danger')
        return 0
    
    df.columns = [str(col).strip().lower() for col in df.columns]
    
    if 'student_id' not in df.columns:
        flash('Missing student_id column', 'danger')
        return 0
    
    cur = mysql.connection.cursor()
    count = 0
    
    if level == 'alevel':
        # A-Level: paper1, paper2
        for _, row in df.iterrows():
            student_id = str(row['student_id']).strip()
            cur.execute("SELECT class FROM students WHERE student_id=%s", (student_id,))
            res = cur.fetchone()
            if not res or res[0] != assigned_class:
                continue
            
            paper1 = float(row['paper1']) if pd.notna(row.get('paper1')) else None
            paper2 = float(row['paper2']) if pd.notna(row.get('paper2')) else None
            available = [s for s in [paper1, paper2] if s is not None]
            if not available:
                continue
            
            avg_score = sum(available) / len(available)
            grade, points = get_alevel_grade_and_points(avg_score, is_subsidiary)
            teacher_init = str(row.get('teacher_initials', '')) if pd.notna(row.get('teacher_initials')) else ''
            
            cur.execute("""INSERT INTO marks (student_id, subject, term, year, paper1, paper2, total_score, grade, points, teacher_initials, teacher_id)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE paper1=%s, paper2=%s, total_score=%s, grade=%s, points=%s, teacher_initials=%s""",
                        (student_id, subject, term, year, paper1, paper2, avg_score, grade, points, teacher_init, teacher_id,
                         paper1, paper2, avg_score, grade, points, teacher_init))
            count += 1
    else:
        # O-Level: AI scores + EOT
        ai_columns = [col for col in df.columns if col.startswith('ai') and col[2:].isdigit()]
        for _, row in df.iterrows():
            student_id = str(row['student_id']).strip()
            cur.execute("SELECT class FROM students WHERE student_id=%s", (student_id,))
            res = cur.fetchone()
            if not res or res[0] != assigned_class:
                continue
            
            ai_scores = []
            for ai_col in ai_columns:
                if ai_col in row and pd.notna(row[ai_col]):
                    try:
                        score = float(row[ai_col])
                        if 0 <= score <= 3:
                            ai_scores.append(score)
                    except:
                        pass
            
            ai_average = sum(ai_scores) / len(ai_scores) if ai_scores else 0
            ai_contribution = (ai_average / 3.0) * 20 if ai_scores else 0
            eot = float(row['eot_score']) if 'eot_score' in df.columns and pd.notna(row['eot_score']) else 0
            eot_contribution = (eot / 100.0) * 80
            total_score = ai_contribution + eot_contribution
            grade, _ = get_grade_and_descriptor(total_score) if ai_scores and eot else ('N/A', '')
            identifier = (total_score / 100.0) * 3
            descriptor = get_descriptor_by_identifier(identifier)
            teacher_init = str(row.get('teacher_initials', '')) if pd.notna(row.get('teacher_initials')) else ''
            
            ai_values = [0] * 6
            for i, col in enumerate(ai_columns[:6]):
                ai_values[i] = ai_scores[i] if i < len(ai_scores) else 0
            
            cur.execute("""INSERT INTO marks (student_id, subject, term, year, ai1, ai2, ai3, ai4, ai5, ai6, ai_average, ai_contribution, eot_score, total_score, grade, identifier, descriptor, teacher_initials, teacher_id)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE ai1=%s, ai2=%s, ai3=%s, ai4=%s, ai5=%s, ai6=%s, ai_average=%s, ai_contribution=%s, eot_score=%s, total_score=%s, grade=%s, identifier=%s, descriptor=%s, teacher_initials=%s""",
                        (student_id, subject, term, year, ai_values[0], ai_values[1], ai_values[2], ai_values[3], ai_values[4], ai_values[5],
                         ai_average, ai_contribution, eot, total_score, grade, identifier, descriptor, teacher_init, teacher_id,
                         ai_values[0], ai_values[1], ai_values[2], ai_values[3], ai_values[4], ai_values[5],
                         ai_average, ai_contribution, eot, total_score, grade, identifier, descriptor, teacher_init))
            count += 1
    
    mysql.connection.commit()
    cur.close()
    return count

def get_predefined_comments(comment_type):
    """Get predefined comments for dropdown - safe version"""
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT id, comment_text FROM predefined_comments WHERE comment_type=%s AND is_active=1 ORDER BY id", (comment_type,))
    comments = cur.fetchall()
    cur.close()
    return comments

def calculate_age(birth_date):
    """Calculate age from date of birth"""
    today = datetime.now().date()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

def extract_results_from_pdf(file_path):
    """Extract results from uploaded PDF (simplified - integrate with actual OCR/parser)"""
    # This is a placeholder. In production, integrate with:
    # - PyPDF2 for text extraction
    # - OCR engines like Tesseract
    # - Or specific result parsing logic
    
    # For demo, return sample data
    return {
        'english': 75,
        'math': 68,
        'science': 82,
        'social_studies': 70,
        'average': 73.75,
        'qualifies': True
    }

def determine_admission_worth(results):
    """Determine if student qualifies based on results"""
    # Define qualification criteria (customize as needed)
    min_average = 60
    min_english = 50
    min_math = 50
    
    qualifies = (
        results.get('average', 0) >= min_average and
        results.get('english', 0) >= min_english and
        results.get('math', 0) >= min_math
    )
    
    return {
        'qualifies': qualifies,
        'average': results.get('average', 0),
        'message': 'Congratulations! You qualify for admission.' if qualifies else 'Sorry, you do not meet the minimum requirements.'
    }

def process_mobile_money_payment(phone_number, amount, student_id):
    """Process mobile money payment (placeholder - integrate with actual API)"""
    # In production, integrate with:
    # - MTN MoMo API
    # - Airtel Money API
    # - Or other payment gateway
    
    # Generate unique transaction ID
    transaction_id = f"PAY-{student_id}-{int(datetime.now().timestamp())}"
    
    # For demo, simulate successful payment
    # In production, make actual API call
    success = True
    
    return {
        'success': success,
        'transaction_id': transaction_id,
        'message': 'Payment successful' if success else 'Payment failed'
    }

def generate_admission_letter(student):
    """Generate admission letter HTML content"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Admission Letter - {student['full_name']}</title></head>
    <body style="font-family: Arial, sans-serif; padding: 40px;">
        <div style="max-width: 800px; margin: 0 auto; border: 1px solid #ddd; padding: 30px;">
            <div style="text-align: center;">
                <h2>YOUR SCHOOL NAME</h2>
                <p>P.O. Box 123, Kampala, Uganda | Tel: +256 712 345678</p>
                <hr>
                <h3>ADMISSION LETTER</h3>
            </div>
            <p><strong>Date:</strong> {datetime.now().strftime('%d/%m/%Y')}</p>
            <p><strong>Student Name:</strong> {student['full_name']}</p>
            <p><strong>Student ID:</strong> {student['student_id']}</p>
            <p><strong>Class:</strong> {student['class']}</p>
            <p><strong>LIN:</strong> {student['lin']}</p>
            <p><strong>Preferred House:</strong> {student['preferred_house']}</p>
            <p>Dear {student['full_name']},</p>
            <p>We are pleased to inform you that your application for admission has been approved. You are hereby admitted to {student['class']} at our esteemed institution.</p>
            <p>Please report to the school on the specified reporting date with this letter and other required documents.</p>
            <br>
            <p>Yours sincerely,</p>
            <p><strong>Admissions Office</strong></p>
            <div style="margin-top: 20px; text-align: center; font-size: 12px; color: #666;">
                <p>This is a system-generated letter. No signature is required.</p>
            </div>
        </div>
    </body>
    </html>
    """

def send_email(recipient, subject, html_content):
    """Send email (placeholder - integrate with actual email service)"""
    # In production, integrate with:
    # - SMTP (Gmail, Outlook)
    # - SendGrid
    # - Mailgun
    
    print(f"[EMAIL] To: {recipient} | Subject: {subject}")
    print(f"[EMAIL] Content: {html_content[:200]}...")
    return True

@app.route('/admissions', methods=['GET', 'POST'])
def admissions_portal():
    """Student self-service admission portal"""
    if request.method == 'POST':
        # Step 1: Submit application
        full_name = request.form['full_name']
        date_of_birth = request.form['date_of_birth']
        sex = request.form['sex']
        preferred_house = request.form['preferred_house']
        disability = request.form.get('disability', '')
        sports_activities = request.form.getlist('sports_activities')
        lin = request.form['lin']
        phone = request.form['phone']
        email = request.form['email']
        
        # Calculate age
        birth_date = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
        age = calculate_age(birth_date)
        
        # Handle photo upload
        photo = request.files.get('photo')
        photo_filename = None
        if photo and photo.filename:
            ext = photo.filename.rsplit('.', 1)[1].lower()
            student_id_temp = f"TEMP-{int(datetime.now().timestamp())}"
            photo_filename = f"{student_id_temp}.{ext}"
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], photo_filename))
        
        # Handle results PDF upload
        results_file = request.files.get('results_pdf')
        results_data = None
        if results_file and results_file.filename:
            filename = secure_filename(f"results_{int(datetime.now().timestamp())}_{results_file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            results_file.save(filepath)
            
            # Extract results from PDF
            results_data = extract_results_from_pdf(filepath)
        
        # Determine admission worth
        qualification = determine_admission_worth(results_data) if results_data else {'qualifies': False, 'message': 'Results not uploaded'}
        
        # Store in session for next steps
        session['admission_data'] = {
            'full_name': full_name,
            'date_of_birth': date_of_birth,
            'age': age,
            'sex': sex,
            'preferred_house': preferred_house,
            'disability': disability,
            'sports_activities': ','.join(sports_activities),
            'lin': lin,
            'phone': phone,
            'email': email,
            'photo_filename': photo_filename,
            'qualification': qualification,
            'results_data': results_data
        }
        
        if qualification['qualifies']:
            return redirect(url_for('admission_payment'))
        else:
            flash(qualification['message'], 'danger')
            return redirect(url_for('admissions_portal'))
    
    # GET request - show admission form
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT name FROM houses ORDER BY name")
    houses = cur.fetchall()
    cur.execute("SELECT name FROM sports_activities ORDER BY name")
    sports = cur.fetchall()
    cur.close()
    
    return render_template('admissions/apply.html', houses=houses, sports=sports)

@app.route('/admissions/payment', methods=['GET', 'POST'])
def admission_payment():
    """Payment page for admission fees"""
    admission_data = session.get('admission_data')
    if not admission_data:
        flash('Please complete the application form first.', 'warning')
        return redirect(url_for('admissions_portal'))
    
    if request.method == 'POST':
        phone_number = request.form['phone_number']
        amount = 50000  # Admission fee amount
        
        # Process mobile money payment
        payment_result = process_mobile_money_payment(phone_number, amount, 'ADMISSION')
        
        if payment_result['success']:
            session['admission_data']['payment_completed'] = True
            session['admission_data']['transaction_id'] = payment_result['transaction_id']
            flash('Payment successful! Your application has been submitted.', 'success')
            return redirect(url_for('admission_submitted'))
        else:
            flash('Payment failed. Please try again.', 'danger')
            return redirect(url_for('admission_payment'))
    
    return render_template('admissions/payment.html', 
                          amount=50000, 
                          student_name=admission_data['full_name'])

@app.route('/admissions/submitted')
def admission_submitted():
    """Application submitted confirmation page"""
    admission_data = session.get('admission_data')
    if not admission_data:
        return redirect(url_for('admissions_portal'))
    
    return render_template('admissions/submitted.html', data=admission_data)

# ==================== AUTHENTICATION ====================
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, username, role, status, phone, must_change_password FROM users WHERE username=%s AND password=%s", (username, password))
        user = cur.fetchone()
        cur.close()
        if user and user[3] == 1:
            session['user_id'], session['username'], session['role'], session['phone'] = user[0], user[1], user[2], user[4]
            if user[5] == 1:
                flash('Please change your password.', 'warning')
                return redirect(url_for('change_password'))
            flash(f'Welcome {username}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials or inactive account.', 'danger')
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
        cur = mysql.connection.cursor()
        cur.execute("UPDATE users SET password=%s, must_change_password=0 WHERE id=%s", (new_pass, session['user_id']))
        mysql.connection.commit()
        cur.close()
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
        cur = mysql.connection.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s AND phone=%s", (username, phone))
        user = cur.fetchone()
        if user:
            cur.execute("UPDATE users SET password=%s, must_change_password=0 WHERE id=%s", (new_pass, user[0]))
            mysql.connection.commit()
            flash('Password reset successfully.', 'success')
        else:
            flash('Username and phone number do not match.', 'danger')
        cur.close()
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'info')
    return redirect(url_for('login'))

@app.context_processor
def inject_now():
    return {'datetime': datetime}

# ==================== DASHBOARD ====================
@app.route('/dashboard')
@login_required
def dashboard():
    role = session.get('role')
    
    # Get notifications for applicable roles
    notification_count = 0
    notifications = []
    if role in ['headteacher', 'bursar', 'management', 'admin']:
        notification_count = get_notification_count(role)
        notifications = get_notifications(role, limit=5)
    
    if role == 'admin':
        search = request.args.get('search', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = 10
        cur = mysql.connection.cursor()
        if search:
            cur.execute("SELECT COUNT(*) FROM users WHERE username LIKE %s", (f'%{search}%',))
        else:
            cur.execute("SELECT COUNT(*) FROM users")
        total = cur.fetchone()[0]
        total_pages = (total + per_page - 1) // per_page
        offset = (page - 1) * per_page
        if search:
            cur.execute("SELECT id, username, role, phone, status, profile_pic FROM users WHERE username LIKE %s ORDER BY id LIMIT %s OFFSET %s", (f'%{search}%', per_page, offset))
        else:
            cur.execute("SELECT id, username, role, phone, status, profile_pic FROM users ORDER BY id LIMIT %s OFFSET %s", (per_page, offset))
        users = cur.fetchall()
        cur.close()
        return render_template('dashboard.html', 
                              role=role, 
                              data={'users': users, 'total_pages': total_pages, 'current_page': page}, 
                              search=search,
                              notification_count=notification_count,
                              notifications=notifications)
    elif role == 'bursar':
        return redirect(url_for('bursar_dashboard'))
    elif role == 'headteacher':
        return render_template('dashboard.html', 
                              role=role,
                              notification_count=notification_count,
                              notifications=notifications)
    elif role == 'management':
        return render_template('dashboard.html', 
                              role=role,
                              notification_count=notification_count,
                              notifications=notifications)
    else:
        return render_template('dashboard.html', 
                              role=role,
                              notification_count=notification_count,
                              notifications=notifications)

@app.route('/notifications')
@login_required
def view_all_notifications():
    role = session.get('role')
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("""
        SELECT * FROM notifications 
        WHERE user_role = %s 
        ORDER BY created_at DESC
    """, (role,))
    notifications = cur.fetchall()
    cur.close()
    return render_template('notifications.html', notifications=notifications)


# ==================== ADMIN MODULE ====================
@app.route('/admin/add_user', methods=['POST'])
@admin_required
def add_user():
    username = request.form['username'].strip()
    password = request.form['password'].strip()
    role = request.form['role'].strip()
    phone_raw = request.form.get('phone', '').strip()
    phone = validate_and_format_phone(phone_raw) if phone_raw else None
    if phone_raw and not phone:
        flash('Invalid phone number format.', 'danger')
        return redirect(url_for('dashboard'))
    child_id = request.form.get('child_id', '').strip() or None
    
    if not username or not password or not role:
        flash('Username, password and role are required.', 'danger')
        return redirect(url_for('dashboard'))
    
    cur = mysql.connection.cursor()
    try:
        # REMOVED assigned_class from the INSERT statement
        cur.execute("""
            INSERT INTO users (username, password, role, phone, status, child_id, profile_pic, must_change_password) 
            VALUES (%s, %s, %s, %s, 1, %s, 'default_avatar.png', 1)
        """, (username, password, role, phone, child_id))
        mysql.connection.commit()
        flash(f'User {username} added. Password: {password} – inform the user.', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error: {str(e)}', 'danger')
    finally:
        cur.close()
    return redirect(url_for('dashboard'))

@app.route('/admin/edit_user/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        username = request.form['username'].strip()
        role = request.form['role'].strip()
        phone = request.form.get('phone', '').strip()
        child_id = request.form.get('child_id', '').strip() or None
        file = request.files.get('profile_pic')
        profile_pic = None
        if file and file.filename:
            if allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
                filename = secure_filename(f"user_{user_id}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                profile_pic = filename
            else:
                flash('Invalid image format.', 'danger')
                return redirect(url_for('edit_user', user_id=user_id))
        try:
            if profile_pic:
                cur.execute("UPDATE users SET username=%s, role=%s, phone=%s, child_id=%s, profile_pic=%s WHERE id=%s", 
                           (username, role, phone, child_id, profile_pic, user_id))
            else:
                cur.execute("UPDATE users SET username=%s, role=%s, phone=%s, child_id=%s WHERE id=%s", 
                           (username, role, phone, child_id, user_id))
            mysql.connection.commit()
            flash('User updated.', 'success')
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Error: {str(e)}', 'danger')
        finally:
            cur.close()
        return redirect(url_for('dashboard'))
    
    cur.execute("SELECT id, username, role, phone, child_id, profile_pic FROM users WHERE id=%s", (user_id,))
    user = cur.fetchone()
    cur.close()
    return render_template('edit_user.html', user=user)

@app.route('/admin/toggle_user/<int:user_id>')
@admin_required
def toggle_user(user_id):
    if user_id == session.get('user_id'):
        flash('Cannot toggle your own account.', 'warning')
        return redirect(url_for('dashboard'))
    cur = mysql.connection.cursor()
    cur.execute("UPDATE users SET status = 1 - status WHERE id=%s", (user_id,))
    mysql.connection.commit()
    cur.close()
    flash('Status toggled.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/admin/delete_user/<int:user_id>')
@admin_required
def delete_user(user_id):
    if user_id == session.get('user_id'):
        flash('Cannot delete your own account.', 'warning')
        return redirect(url_for('dashboard'))
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
    mysql.connection.commit()
    cur.close()
    flash('User deleted.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/admin/teacher_assignments')
@admin_required
def admin_teacher_assignments():
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT u.id, u.username, u.role, GROUP_CONCAT(tca.class_name) as assigned_classes FROM users u LEFT JOIN teacher_class_assignments tca ON u.id = tca.user_id WHERE u.role IN ('classteacher', 'subject_teacher') GROUP BY u.id ORDER BY u.username")
    teachers = cur.fetchall()
    cur.execute("SELECT DISTINCT class FROM students WHERE class IS NOT NULL ORDER BY class")
    all_classes = [row['class'] for row in cur.fetchall()]
    cur.close()
    return render_template('admin/teacher_assignments.html', teachers=teachers, all_classes=all_classes)

@app.route('/admin/assign_class', methods=['POST'])
@admin_required
def admin_assign_class():
    assign_user_to_class(request.form['teacher_id'], request.form['class_name'], request.form.get('subject'), 'subject_teacher')
    flash('Teacher assigned to class', 'success')
    return redirect(url_for('admin_teacher_assignments'))

@app.route('/admin/school_settings', methods=['GET', 'POST'])
def school_settings():
    if not check_permission(['admin', 'headteacher']):
        abort(403)
    
    cur = mysql.connection.cursor()
    
    if request.method == 'POST':
        begins = request.form['next_term_begins']
        ends = request.form['next_term_ends']
        
        # Handle stamp upload
        stamp_file = request.files.get('stamp')
        stamp_filename = None
        if stamp_file and stamp_file.filename:
            if allowed_file(stamp_file.filename, ALLOWED_IMAGE_EXTENSIONS):
                stamp_filename = f"stamp_{int(datetime.now().timestamp())}.{stamp_file.filename.rsplit('.', 1)[1].lower()}"
                stamp_file.save(os.path.join(app.config['UPLOAD_FOLDER'], stamp_filename))
            else:
                flash('Invalid stamp image format.', 'danger')
                return redirect(url_for('school_settings'))
        
        # School information
        school_name = request.form.get('school_name', 'YOUR SCHOOL NAME')
        school_address = request.form.get('school_address', 'P.O. Box 123, Kampala, Uganda')
        school_phone = request.form.get('school_phone', 'Tel: +256 712 345678')
        school_email = request.form.get('school_email', 'Email: info@school.com')
        
        # Logo upload
        logo_file = request.files.get('logo')
        logo_filename = None
        if logo_file and logo_file.filename:
            if allowed_file(logo_file.filename, ALLOWED_IMAGE_EXTENSIONS):
                logo_filename = f"logo_{int(datetime.now().timestamp())}.{logo_file.filename.rsplit('.', 1)[1].lower()}"
                logo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], logo_filename))
            else:
                flash('Invalid logo image format.', 'danger')
                return redirect(url_for('school_settings'))
        
        # NSSF and PAYE rates
        nssf_employee_rate = float(request.form.get('nssf_employee_rate', 5.0))
        paye_rate = float(request.form.get('paye_rate', 10.0))
        paye_threshold = float(request.form.get('paye_threshold', 235000))
        
        # Build update query dynamically
        update_fields = []
        params = []
        
        update_fields.append("next_term_begins = %s")
        params.append(begins)
        
        update_fields.append("next_term_ends = %s")
        params.append(ends)
        
        update_fields.append("school_name = %s")
        params.append(school_name)
        
        update_fields.append("school_address = %s")
        params.append(school_address)
        
        update_fields.append("school_phone = %s")
        params.append(school_phone)
        
        update_fields.append("school_email = %s")
        params.append(school_email)
        
        update_fields.append("nssf_employee_rate = %s")
        params.append(nssf_employee_rate)
        
        update_fields.append("paye_rate = %s")
        params.append(paye_rate)
        
        update_fields.append("paye_threshold = %s")
        params.append(paye_threshold)
        
        if stamp_filename:
            update_fields.append("headteacher_stamp = %s")
            params.append(stamp_filename)
        
        if logo_filename:
            update_fields.append("logo_url = %s")
            params.append(logo_filename)
        
        params.append(1)  # WHERE id=1
        
        query = f"UPDATE school_settings SET {', '.join(update_fields)} WHERE id = %s"
        cur.execute(query, params)
        mysql.connection.commit()
        
        flash('School settings updated successfully.', 'success')
    
    # Get all settings
    cur.execute("""
        SELECT next_term_begins, next_term_ends, headteacher_stamp, 
               school_name, school_address, school_phone, school_email, logo_url,
               nssf_employee_rate, paye_rate, paye_threshold
        FROM school_settings WHERE id=1
    """)
    settings = cur.fetchone()
    cur.close()
    
    # Extract values with defaults
    nssf_rate = settings[8] if settings and len(settings) > 8 else 5.0
    paye_rate = settings[9] if settings and len(settings) > 9 else 10.0
    paye_threshold = settings[10] if settings and len(settings) > 10 else 235000
    
    return render_template('admin/school_settings.html', 
                          settings=settings,
                          nssf_rate=nssf_rate,
                          paye_rate=paye_rate,
                          paye_threshold=paye_threshold)

# ==================== PREDEFINED COMMENTS MANAGEMENT ====================

@app.route('/admin/predefined_comments')
@admin_required
def admin_predefined_comments():
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT * FROM predefined_comments ORDER BY comment_type, id")
    comments = cur.fetchall()
    cur.close()
    return render_template('admin/predefined_comments.html', comments=comments)

@app.route('/admin/predefined_comments/add', methods=['POST'])
@admin_required
def admin_predefined_comments_add():
    comment_type = request.form['comment_type']
    comment_text = request.form['comment_text'].strip()
    
    if not comment_text:
        flash('Comment text is required.', 'danger')
        return redirect(url_for('admin_predefined_comments'))
    
    cur = mysql.connection.cursor()
    cur.execute("INSERT INTO predefined_comments (comment_type, comment_text, is_active) VALUES (%s, %s, 1)", 
                (comment_type, comment_text))
    mysql.connection.commit()
    cur.close()
    
    flash('Comment added successfully.', 'success')
    return redirect(url_for('admin_predefined_comments'))

@app.route('/admin/predefined_comments/delete/<int:comment_id>')
@admin_required
def admin_predefined_comments_delete(comment_id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM predefined_comments WHERE id=%s", (comment_id,))
    mysql.connection.commit()
    cur.close()
    
    flash('Comment deleted successfully.', 'success')
    return redirect(url_for('admin_predefined_comments'))

# ==================== DOS MODULE ====================
SCHOOL_ABBR = "SMS"

def generate_student_id():
    return generate_unique_number(SCHOOL_ABBR, 'students', 'student_id', year_format=True)

@app.route('/dos/admit_student', methods=['GET', 'POST'])
def dos_admit():
    if not check_permission(['dos']):
        abort(403)
    
    # Get houses and sports for dropdowns
    cur = mysql.connection.cursor(DictCursor)
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
        
        # Calculate age
        age = None
        if date_of_birth:
            birth_date = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
            age = calculate_age(birth_date)
        
        student_id = generate_student_id()
        photo_filename = "default_avatar.png"
        if photo and photo.filename:
            if allowed_file(photo.filename, ALLOWED_IMAGE_EXTENSIONS):
                ext = photo.filename.rsplit('.', 1)[1].lower()
                photo_filename = f"{student_id}.{ext}"
                photo.save(os.path.join(app.config['UPLOAD_FOLDER'], photo_filename))
        
        cur = mysql.connection.cursor()
        try:
            cur.execute("""
                INSERT INTO students (
                    student_id, full_name, class, photo_path, fees_paid, fees_balance, 
                    admission_date, parent_phone, date_of_birth, age, sex, 
                    preferred_house, disability, sports_activities, lin, 
                    admission_source, admission_status
                ) VALUES (%s, %s, %s, %s, 0, 0, CURDATE(), %s, %s, %s, %s, %s, %s, %s, %s, 'local', 'approved')
            """, (student_id, full_name, class_name, photo_filename, parent_phone, 
                  date_of_birth, age, sex, preferred_house, disability, 
                  ','.join(sports_activities) if sports_activities else None, lin))
            mysql.connection.commit()
            flash(f'Student {full_name} admitted with ID {student_id}.', 'success')
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Error: {str(e)}', 'danger')
        finally:
            cur.close()
        return redirect(url_for('dos_admit'))
    
    return render_template('dos/admit_student.html', houses=houses, sports=sports)

@app.route('/dos/class_lists')
def dos_class_lists():
    if not check_permission(['dos']):
        abort(403)
    class_filter = request.args.get('class', '') or ''
    search = request.args.get('search', '') or ''
    term = request.args.get('term', 'Term 1')
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != '' ORDER BY class")
    classes = [row['class'] for row in cur.fetchall()]
    
    query = "SELECT student_id, full_name, class, photo_path, parent_phone, sex, age, preferred_house, lin, admission_source FROM students WHERE 1=1"
    params = []
    if class_filter:
        query += " AND class = %s"
        params.append(class_filter)
    if search:
        query += " AND (student_id LIKE %s OR full_name LIKE %s)"
        pattern = f"%{search}%"
        params.append(pattern)
        params.append(pattern)
    query += " ORDER BY full_name"
    cur.execute(query, params)
    students = cur.fetchall()
    
    for s in students:
        photo_path = s.get('photo_path')
        if photo_path and photo_path != 'default_avatar.png':
            s['photo_url'] = url_for('static', filename='uploads/' + photo_path)
        else:
            s['photo_url'] = url_for('static', filename='uploads/default_avatar.png')
    
    cur.close()
    return render_template('dos/class_lists.html', 
        classes=classes, 
        students=students, 
        selected_class=class_filter, 
        search=search,
        term=term)

@app.route('/dos/remove_student/<student_id>', methods=['POST'])
def dos_remove_student(student_id):
    if not check_permission(['dos']):
        abort(403)
    cur = mysql.connection.cursor()
    cur.execute("SELECT photo_path FROM students WHERE student_id=%s", (student_id,))
    row = cur.fetchone()
    if row and row[0] != 'default_avatar.png':
        path = os.path.join(app.config['UPLOAD_FOLDER'], row[0])
        if os.path.exists(path):
            os.remove(path)
    cur.execute("DELETE FROM students WHERE student_id=%s", (student_id,))
    mysql.connection.commit()
    cur.close()
    flash(f'Student {student_id} removed.', 'success')
    return redirect(url_for('dos_class_lists'))

@app.route('/dos/promote', methods=['GET', 'POST'])
def dos_promote():
    if not check_permission(['dos']):
        abort(403)
    cur = mysql.connection.cursor()
    cur.execute("SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != '' ORDER BY class")
    classes = [row[0] for row in cur.fetchall()]
    if request.method == 'POST':
        from_class = request.form['from_class']
        match = re.search(r'(\d+)', from_class)
        if match:
            to_class = from_class.replace(str(match.group(1)), str(int(match.group(1)) + 1))
        else:
            to_class = from_class + " (Promoted)"
        cur.execute("UPDATE students SET class=%s WHERE class=%s", (to_class, from_class))
        mysql.connection.commit()
        flash(f'{cur.rowcount} students promoted from {from_class} to {to_class}.', 'success')
    cur.close()
    return render_template('dos/promote.html', classes=classes)

@app.route('/dos/attendance')
def dos_attendance():
    if not check_permission(['dos']):
        abort(403)
    # Reuses the same unified attendance template
    cur = mysql.connection.cursor()
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
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO schedules (type, term_scope, content, updated_at) VALUES (%s, %s, %s, NOW()) ON DUPLICATE KEY UPDATE content=%s, updated_at=NOW()", (schedule_type, term_scope, final_content, final_content))
        mysql.connection.commit()
        cur.close()
        flash(f'{schedule_type.capitalize()} saved.', 'success')
        return redirect(url_for('dos_schedules'))
    cur = mysql.connection.cursor()
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
            df = pd.read_excel(file)
            df.columns = [str(col).strip().lower() for col in df.columns]
            required = ['min_score', 'max_score', 'grade', 'descriptor']
            if not all(c in df.columns for c in required):
                flash('Missing required columns', 'danger')
                return redirect(url_for('dos_olevel_grading'))
            cur = mysql.connection.cursor()
            cur.execute("TRUNCATE TABLE grading_system")
            count = 0
            for _, row in df.iterrows():
                cur.execute("INSERT INTO grading_system (min_score, max_score, grade, descriptor) VALUES (%s, %s, %s, %s)", 
                           (float(row['min_score']), float(row['max_score']), str(row['grade']).strip(), str(row['descriptor']).strip()))
                count += 1
            mysql.connection.commit()
            cur.close()
            flash(f'{count} O-Level grading rules uploaded.', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dos_olevel_grading'))
    cur = mysql.connection.cursor()
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
            df = pd.read_excel(file)
            df.columns = [str(col).strip().lower() for col in df.columns]
            required = ['min_score', 'max_score', 'grade', 'points']
            if not all(c in df.columns for c in required):
                flash('Missing required columns', 'danger')
                return redirect(url_for('dos_alevel_grading'))
            cur = mysql.connection.cursor()
            cur.execute("DELETE FROM alevel_grading WHERE is_subsidiary=0")
            count = 0
            for _, row in df.iterrows():
                cur.execute("INSERT INTO alevel_grading (min_score, max_score, grade, points, is_subsidiary) VALUES (%s, %s, %s, %s, 0)", 
                           (float(row['min_score']), float(row['max_score']), str(row['grade']).strip(), int(row['points'])))
                count += 1
            mysql.connection.commit()
            cur.close()
            flash(f'{count} A-Level grading rules uploaded.', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dos_alevel_grading'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT min_score, max_score, grade, points FROM alevel_grading WHERE is_subsidiary=0 ORDER BY min_score DESC")
    rules = cur.fetchall()
    cur.close()
    return render_template('dos/alevel_grading.html', rules=rules)

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
            df = pd.read_excel(file)
            df.columns = [str(col).strip().lower() for col in df.columns]
            required = ['min_value', 'max_value', 'descriptor']
            if not all(c in df.columns for c in required):
                flash('Missing required columns', 'danger')
                return redirect(url_for('dos_identifier_grading'))
            cur = mysql.connection.cursor()
            cur.execute("TRUNCATE TABLE identifier_grading")
            count = 0
            for _, row in df.iterrows():
                cur.execute("INSERT INTO identifier_grading (min_value, max_value, descriptor) VALUES (%s, %s, %s)", 
                           (float(row['min_value']), float(row['max_value']), str(row['descriptor']).strip()))
                count += 1
            mysql.connection.commit()
            cur.close()
            flash(f'{count} Identifier grading rules uploaded.', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dos_identifier_grading'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT min_value, max_value, descriptor FROM identifier_grading ORDER BY min_value DESC")
    rules = cur.fetchall()
    cur.close()
    return render_template('dos/identifier_grading.html', rules=rules)

@app.route('/dos/teacher_assignments')
def dos_teacher_assignments():
    if not check_permission(['dos']):
        abort(403)
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT u.username, u.role, tca.class_name, tca.subject, tca.assignment_type, tca.assigned_by, tca.assigned_at FROM teacher_class_assignments tca JOIN users u ON tca.user_id = u.id ORDER BY tca.class_name, tca.assignment_type, u.username")
    assignments = cur.fetchall()
    cur.close()
    return render_template('dos/teacher_assignments.html', assignments=assignments)

@app.route('/dos/upload_subject_teachers', methods=['GET', 'POST'])
def dos_upload_subject_teachers():
    if not check_permission(['dos']):
        abort(403)
    if request.method == 'POST':
        file = request.files.get('excel_file')
        if not file or not file.filename:
            flash('Please upload an Excel file.', 'danger')
            return redirect(url_for('dos_upload_subject_teachers'))
        try:
            df = pd.read_excel(file)
            df.columns = [str(col).strip().lower() for col in df.columns]
            required = ['username', 'class_name', 'subject']
            if not all(c in df.columns for c in required):
                flash('Missing required columns', 'danger')
                return redirect(url_for('dos_upload_subject_teachers'))
            cur = mysql.connection.cursor(DictCursor)
            success = 0
            for _, row in df.iterrows():
                cur.execute("SELECT id FROM users WHERE username=%s", (str(row['username']).strip(),))
                user = cur.fetchone()
                if user:
                    assign_user_to_class(user['id'], str(row['class_name']).strip(), str(row['subject']).strip(), 'subject_teacher')
                    success += 1
            cur.close()
            flash(f'{success} subject teacher assignments uploaded.', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dos_teacher_assignments'))
    return render_template('dos/upload_subject_teachers.html')

@app.route('/dos/report_card/<student_id>')
def dos_report_card(student_id):
    if not check_permission(['dos']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    
    # Get student details
    cur.execute("SELECT full_name, class, photo_path FROM students WHERE student_id=%s", (student_id,))
    student = cur.fetchone()
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('dos_class_lists'))
    
    full_name = student['full_name']
    class_name = student['class']
    photo_path = student['photo_path']
    
    # Handle photo URL safely
    if photo_path and photo_path != 'default_avatar.png':
        photo_url = url_for('static', filename='uploads/' + photo_path)
    else:
        photo_url = url_for('static', filename='uploads/default_avatar.png')
    
    term = request.args.get('term', 'Term 1')
    year = request.args.get('year', datetime.now().year)
    
    # School info
    cur.execute("SELECT school_name, school_address, school_phone, school_email, logo_url FROM school_settings WHERE id=1")
    school = cur.fetchone()
    school_name = school['school_name'] if school else 'YOUR SCHOOL NAME'
    school_address = school['school_address'] if school else 'P.O. Box 123, Kampala, Uganda'
    school_phone = school['school_phone'] if school else 'Tel: +256 712 345678'
    school_email = school['school_email'] if school else 'Email: info@school.com'
    school_logo_url = school['logo_url'] if school else url_for('static', filename='images/logo.png')
    
    # School settings
    cur.execute("SELECT next_term_begins, next_term_ends, headteacher_stamp FROM school_settings WHERE id=1")
    settings = cur.fetchone()
    next_term_begins = settings['next_term_begins'] if settings else None
    next_term_ends = settings['next_term_ends'] if settings else None
    stamp_url = url_for('static', filename='uploads/' + settings['headteacher_stamp']) if settings and settings['headteacher_stamp'] else None
    
    # Get comments - INCLUDING LOCKED COLUMNS with safe handling
    cur.execute("""
        SELECT comment, headteacher_comment, class_teacher_comment_locked, headteacher_comment_locked 
        FROM teacher_comments 
        WHERE student_id=%s AND term=%s AND year=%s
    """, (student_id, term, year))
    comments = cur.fetchone()
    
    # Safe extraction with defaults - FIXED KeyError issue
    if comments:
        teacher_comment = comments.get('comment') if comments.get('comment') else ''
        headteacher_comment = comments.get('headteacher_comment') if comments.get('headteacher_comment') else ''
        teacher_comment_locked = comments.get('class_teacher_comment_locked') if comments.get('class_teacher_comment_locked') is not None else 0
        headteacher_comment_locked = comments.get('headteacher_comment_locked') if comments.get('headteacher_comment_locked') is not None else 0
    else:
        teacher_comment = ''
        headteacher_comment = ''
        teacher_comment_locked = 0
        headteacher_comment_locked = 0
    
    # Detect level
    class_upper = class_name.upper()
    is_alevel = class_upper in ['S5', 'S6', 'A-LEVEL', 'A LEVEL'] or (class_upper.startswith('S') and len(class_upper) >= 2 and class_upper[1] in ['5', '6'])
    
    if is_alevel:
        cur.execute("SELECT subject, paper1, paper2, total_score, grade, points, teacher_initials FROM marks WHERE student_id=%s AND term=%s AND year=%s ORDER BY subject", (student_id, term, year))
        marks = cur.fetchall()
        total_points = sum(m['points'] for m in marks if m['points'] is not None) if marks else 0
        cur.close()
        return render_template('teacher/report_card_alevel.html',
            student_id=student_id, full_name=full_name, class_name=class_name, photo_url=photo_url,
            term=term, year=year, marks=marks, total_points=total_points,
            teacher_comment=teacher_comment, headteacher_comment=headteacher_comment,
            teacher_comment_locked=teacher_comment_locked,
            headteacher_comment_locked=headteacher_comment_locked,
            predefined_class_comments=get_predefined_comments('class_teacher'),
            predefined_head_comments=get_predefined_comments('headteacher'),
            next_term_begins=next_term_begins, next_term_ends=next_term_ends, stamp_url=stamp_url,
            school_name=school_name, school_address=school_address, school_phone=school_phone,
            school_email=school_email, school_logo_url=school_logo_url, can_edit_comments=False)
    else:
        cur.execute("""
            SELECT subject, ai1, ai2, ai3, ai4, ai5, ai6, ai_average, ai_contribution, eot_score, total_score, grade, identifier, descriptor, teacher_initials
            FROM marks WHERE student_id=%s AND term=%s AND year=%s ORDER BY subject
        """, (student_id, term, year))
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
            school_name=school_name, school_address=school_address, school_phone=school_phone,
            school_email=school_email, school_logo_url=school_logo_url, can_edit_comments=False)
    
@app.route('/dos/admissions/pending')
def dos_pending_admissions():
    if not check_permission(['dos']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("""
        SELECT * FROM students 
        WHERE admission_source = 'online' AND admission_status = 'pending'
        ORDER BY application_date DESC
    """)
    pending = cur.fetchall()
    cur.close()
    
    return render_template('dos/pending_admissions.html', pending=pending)

@app.route('/dos/admissions/approve/<student_id>')
def dos_approve_admission(student_id):
    if not check_permission(['dos']):
        abort(403)
    
    # Generate student ID
    new_student_id = generate_student_id()
    
    cur = mysql.connection.cursor(DictCursor)
    
    # Get pending admission data
    cur.execute("""
        SELECT * FROM students 
        WHERE student_id=%s AND admission_source='online' AND admission_status='pending'
    """, (student_id,))
    student = cur.fetchone()
    
    if not student:
        flash('Admission not found or already processed.', 'danger')
        return redirect(url_for('dos_pending_admissions'))
    
    # Update student record with new ID and approved status
    cur.execute("""
        UPDATE students SET 
            student_id = %s,
            admission_status = 'approved',
            admission_fee_paid = 1
        WHERE student_id = %s
    """, (new_student_id, student_id))
    
    # Generate and send admission letter
    letter_content = generate_admission_letter({
        'full_name': student['full_name'],
        'student_id': new_student_id,
        'class': student['class'],
        'lin': student['lin'],
        'preferred_house': student['preferred_house']
    })
    
    send_email(student['email'], 'Admission Letter - Approved', letter_content)
    
    mysql.connection.commit()
    cur.close()
    
    flash(f'Admission approved for {student["full_name"]}. Student ID: {new_student_id}', 'success')
    return redirect(url_for('dos_pending_admissions'))

@app.route('/dos/admissions/reject/<student_id>')
def dos_reject_admission(student_id):
    if not check_permission(['dos']):
        abort(403)
    
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE students SET 
            admission_status = 'rejected'
        WHERE student_id=%s AND admission_source='online' AND admission_status='pending'
    """, (student_id,))
    mysql.connection.commit()
    cur.close()
    
    flash('Admission rejected.', 'warning')
    return redirect(url_for('dos_pending_admissions'))

# ==================== UNIFIED TEACHER MODULE (Class Teacher + Subject Teacher) ====================
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
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT student_id, full_name, photo_path, parent_phone FROM students WHERE class=%s ORDER BY full_name", (selected_class,))
    students = cur.fetchall()
    for s in students:
        photo_path = s.get('photo_path')
        if photo_path and photo_path != 'default_avatar.png':
            s['photo_url'] = url_for('static', filename='uploads/' + photo_path)
        else:
            s['photo_url'] = url_for('static', filename='uploads/default_avatar.png')
    cur.close()
    
    is_classteacher = any(a['assignment_type'] == 'classteacher' and a['class_name'] == selected_class for a in assignments)
    
    return render_template('teacher/students.html', 
        students=students, 
        selected_class=selected_class,
        available_classes=available_classes,
        is_classteacher=is_classteacher,
        term=term)

@app.route('/teacher/attendance', methods=['GET', 'POST'])
def teacher_attendance():
    if not check_permission(['classteacher']):
        abort(403)
    selected_class = session.get('selected_class')
    if not selected_class:
        flash('No class selected', 'danger')
        return redirect(url_for('teacher_students'))
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        selected_date = request.form['date']
        for key, value in request.form.items():
            if key.startswith('status_'):
                student_id = key.split('_')[1]
                cur.execute("INSERT INTO attendance (student_id, date, status) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE status=%s", (student_id, selected_date, value, value))
        mysql.connection.commit()
        flash('Attendance saved.', 'success')
    cur.execute("SELECT s.student_id, s.full_name, a.status FROM students s LEFT JOIN attendance a ON s.student_id = a.student_id AND a.date = %s WHERE s.class = %s ORDER BY s.full_name", (selected_date, selected_class))
    rows = cur.fetchall()
    cols = [desc[0] for desc in cur.description]
    records = [dict(zip(cols, row)) for row in rows]
    cur.close()
    return render_template('teacher/attendance.html', records=records, selected_date=selected_date, assigned_class=selected_class)

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
    level = 'alevel' if class_upper in ['S5', 'S6', 'A-LEVEL', 'A LEVEL'] or (class_upper.startswith('S') and len(class_upper) >= 2 and class_upper[1] in ['5', '6']) else 'olevel'
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
    return render_template(f'teacher/upload_marks_{level}.html', assigned_class=selected_class, current_year=current_year, teacher_classes=[{'class_name': c} for c in available_classes], selected_class=selected_class)

@app.route('/teacher/report_card/<student_id>')
def teacher_report_card(student_id):
    if not check_permission(['classteacher', 'subject_teacher', 'parent', 'dos', 'headteacher']):
        abort(403)
    
    role = session.get('role')
    cur = mysql.connection.cursor(DictCursor)
    
    # ==================== AUTHORIZATION CHECKS ====================
    if role in ['classteacher', 'subject_teacher']:
        selected_class = session.get('selected_class')
        if not selected_class:
            flash('No class selected', 'danger')
            return redirect(url_for('teacher_students'))
        cur.execute("SELECT class FROM students WHERE student_id=%s", (student_id,))
        res = cur.fetchone()
        if not res or res['class'] != selected_class:
            flash('Student not in your class.', 'danger')
            return redirect(url_for('teacher_students'))
    elif role == 'parent':
        parent_phone = session.get('phone')
        if not parent_phone:
            flash('No phone linked.', 'danger')
            return redirect(url_for('dashboard'))
        cur.execute("SELECT parent_phone FROM students WHERE student_id=%s", (student_id,))
        res = cur.fetchone()
        if not res or res['parent_phone'] != parent_phone:
            flash('Not authorized.', 'danger')
            return redirect(url_for('dashboard'))
    elif role == 'dos':
        cur.execute("SELECT class FROM students WHERE student_id=%s", (student_id,))
        if not cur.fetchone():
            flash('Student not found.', 'danger')
            return redirect(url_for('dos_class_lists'))
    elif role == 'headteacher':
        # Headteacher can view any student
        cur.execute("SELECT class FROM students WHERE student_id=%s", (student_id,))
        if not cur.fetchone():
            flash('Student not found.', 'danger')
            return redirect(url_for('dashboard'))
    
    # ==================== GET STUDENT INFO ====================
    cur.execute("SELECT full_name, class, photo_path FROM students WHERE student_id=%s", (student_id,))
    student = cur.fetchone()
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('dashboard'))
    
    full_name = student['full_name']
    class_name = student['class']
    photo_path = student['photo_path']
    photo_url = url_for('static', filename='uploads/' + photo_path) if photo_path and photo_path != 'default_avatar.png' else url_for('static', filename='uploads/default_avatar.png')
    
    term = request.args.get('term', 'Term 1')
    year = request.args.get('year', datetime.now().year)
    
    # ==================== GET COMMENTS (SAFE - NO HARDCODING) ====================
    # First, check what columns exist in teacher_comments table
    cur.execute("SHOW COLUMNS FROM teacher_comments")
    existing_columns = [row['Field'] for row in cur.fetchall()]
    
    # Build dynamic query based on existing columns
    select_fields = []
    if 'comment' in existing_columns:
        select_fields.append('comment')
    if 'headteacher_comment' in existing_columns:
        select_fields.append('headteacher_comment')
    if 'class_teacher_comment_locked' in existing_columns:
        select_fields.append('class_teacher_comment_locked')
    if 'headteacher_comment_locked' in existing_columns:
        select_fields.append('headteacher_comment_locked')
    
    # Default values
    teacher_comment = ''
    headteacher_comment = ''
    teacher_comment_locked = 0
    headteacher_comment_locked = 0
    
    if select_fields:
        query = f"SELECT {', '.join(select_fields)} FROM teacher_comments WHERE student_id=%s AND term=%s AND year=%s"
        cur.execute(query, (student_id, term, year))
        comments = cur.fetchone()
        
        if comments:
            teacher_comment = comments.get('comment') if comments.get('comment') else ''
            headteacher_comment = comments.get('headteacher_comment') if comments.get('headteacher_comment') else ''
            teacher_comment_locked = comments.get('class_teacher_comment_locked') if comments.get('class_teacher_comment_locked') else 0
            headteacher_comment_locked = comments.get('headteacher_comment_locked') if comments.get('headteacher_comment_locked') else 0
    
    # ==================== SCHOOL INFO ====================
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
    
    # ==================== PERMISSION FLAGS ====================
    can_edit_class_comment = (role == 'classteacher' and not teacher_comment_locked)
    can_edit_head_comment = (role == 'headteacher' and not headteacher_comment_locked)
    can_view_only = role in ['subject_teacher', 'parent', 'dos']
    
    # ==================== GET PREDEFINED COMMENTS ====================
    predefined_class_comments = get_predefined_comments('class_teacher')
    predefined_head_comments = get_predefined_comments('headteacher')
    
    # ==================== DETECT LEVEL (O-LEVEL vs A-LEVEL) ====================
    class_upper = class_name.upper()
    is_alevel = class_upper in ['S5', 'S6', 'A-LEVEL', 'A LEVEL'] or (class_upper.startswith('S') and len(class_upper) >= 2 and class_upper[1] in ['5', '6'])
    
    # ==================== GET MARKS ====================
    if is_alevel:
        cur.execute("""
            SELECT subject, paper1, paper2, total_score, grade, points, teacher_initials
            FROM marks 
            WHERE student_id=%s AND term=%s AND year=%s
            ORDER BY subject
        """, (student_id, term, year))
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
        cur.execute("""
            SELECT subject, ai1, ai2, ai3, ai4, ai5, ai6, ai_average, ai_contribution, eot_score, total_score, grade, identifier, descriptor, teacher_initials
            FROM marks 
            WHERE student_id=%s AND term=%s AND year=%s
            ORDER BY subject
        """, (student_id, term, year))
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
    
    # Use custom comment if provided, otherwise use selected predefined comment
    final_comment = custom_comment if custom_comment else comment
    
    cur = mysql.connection.cursor()
    # Check if comment already exists and is locked
    cur.execute("SELECT class_teacher_comment_locked FROM teacher_comments WHERE student_id=%s AND term=%s AND year=%s", (student_id, term, year))
    existing = cur.fetchone()
    
    if existing and existing[0] == 1:
        flash('Comment cannot be edited as it has been locked.', 'danger')
        return redirect(url_for('teacher_report_card', student_id=student_id, term=term, year=year))
    
    cur.execute("""
        INSERT INTO teacher_comments (student_id, term, year, comment, class_teacher_comment_locked) 
        VALUES (%s, %s, %s, %s, 1) 
        ON DUPLICATE KEY UPDATE comment=%s, class_teacher_comment_locked=1
    """, (student_id, term, year, final_comment, final_comment))
    mysql.connection.commit()
    cur.close()
    flash('Comment saved and locked.', 'success')
    return redirect(url_for('teacher_report_card', student_id=student_id, term=term, year=year))

@app.route('/teacher/edit_student/<student_id>', methods=['GET', 'POST'])
def teacher_edit_student(student_id):
    if not check_permission(['classteacher', 'dos']):
        abort(403)
    cur = mysql.connection.cursor(DictCursor)
    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        class_name = request.form['class'].strip()
        parent_phone = validate_and_format_phone(request.form.get('parent_phone', ''))
        cur.execute("UPDATE students SET full_name=%s, class=%s, parent_phone=%s WHERE student_id=%s", (full_name, class_name, parent_phone, student_id))
        mysql.connection.commit()
        flash('Student updated.', 'success')
        cur.close()
        return redirect(url_for('teacher_students'))
    cur.execute("SELECT student_id, full_name, class, parent_phone FROM students WHERE student_id=%s", (student_id,))
    student = cur.fetchone()
    cur.close()
    return render_template('teacher/edit_student.html', student=student)

@app.route('/teacher/remove_student/<student_id>', methods=['POST'])
def teacher_remove_student(student_id):
    if not check_permission(['classteacher', 'dos']):
        abort(403)
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM students WHERE student_id=%s", (student_id,))
    mysql.connection.commit()
    cur.close()
    flash('Student removed.', 'success')
    return redirect(url_for('teacher_students'))

@app.route('/teacher/print_all_report_cards')
def teacher_print_all_report_cards():
    if not check_permission(['classteacher']):
        abort(403)
    
    # Get selected class from session
    selected_class = session.get('selected_class')
    if not selected_class:
        selected_class = session.get('assigned_class')
    
    if not selected_class:
        flash('No class assigned to you.', 'danger')
        return redirect(url_for('teacher_students'))
    
    term = request.args.get('term', 'Term 1')
    year = request.args.get('year', datetime.now().year)
    
    cur = mysql.connection.cursor(DictCursor)
    
    # Get all students in the class - FIXED: separate execute and fetchall
    cur.execute("SELECT student_id, full_name, photo_path FROM students WHERE class=%s ORDER BY full_name", (selected_class,))
    students_data = cur.fetchall()
    
    # Check if class has no students
    if not students_data:
        flash(f'No students found in class {selected_class}.', 'warning')
        return redirect(url_for('teacher_students'))
    
    # Get school info
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
    
    # Get school settings (term dates, stamp)
    cur.execute("SELECT next_term_begins, next_term_ends, headteacher_stamp FROM school_settings WHERE id=1")
    settings = cur.fetchone()
    
    next_term_begins = settings['next_term_begins'] if settings else None
    next_term_ends = settings['next_term_ends'] if settings else None
    stamp_url = url_for('static', filename='uploads/' + settings['headteacher_stamp']) if settings and settings['headteacher_stamp'] else None
    
    # Detect level for the class
    class_upper = selected_class.upper()
    is_alevel = class_upper in ['S5', 'S6', 'A-LEVEL', 'A LEVEL'] or (class_upper.startswith('S') and len(class_upper) >= 2 and class_upper[1] in ['5', '6'])
    
    # Get comments for each student
    all_reports = []
    
    for student in students_data:
        student_id = student['student_id']
        full_name = student['full_name']
        photo_path = student['photo_path']
        
        photo_url = url_for('static', filename='uploads/' + photo_path) if photo_path and photo_path != 'default_avatar.png' else url_for('static', filename='uploads/default_avatar.png')
        
        # Get comments
        cur.execute("SELECT comment, headteacher_comment FROM teacher_comments WHERE student_id=%s AND term=%s AND year=%s", (student_id, term, year))
        comments_row = cur.fetchone()
        teacher_comment = comments_row['comment'] if comments_row else ''
        headteacher_comment = comments_row['headteacher_comment'] if comments_row else ''
        
        if is_alevel:
            # A-Level marks
            cur.execute("""
                SELECT subject, paper1, paper2, total_score, grade, points, teacher_initials
                FROM marks 
                WHERE student_id=%s AND term=%s AND year=%s
                ORDER BY subject
            """, (student_id, term, year))
            marks = cur.fetchall()
            total_points = sum(m['points'] for m in marks if m['points'] is not None) if marks else 0
            
            all_reports.append({
                'student_id': student_id,
                'full_name': full_name,
                'photo_url': photo_url,
                'marks': marks,
                'total_points': total_points,
                'teacher_comment': teacher_comment,
                'headteacher_comment': headteacher_comment,
                'is_alevel': True
            })
        else:
            # O-Level marks
            cur.execute("""
                SELECT subject, ai1, ai2, ai3, ai4, ai5, ai6, ai_average, ai_contribution, eot_score, total_score, grade, identifier, descriptor, teacher_initials
                FROM marks 
                WHERE student_id=%s AND term=%s AND year=%s
                ORDER BY subject
            """, (student_id, term, year))
            marks = cur.fetchall()
            
            # Compute general average and grade
            total_final = sum(m['total_score'] for m in marks) if marks else 0
            count = len(marks)
            avg_percent = total_final / count if count > 0 else 0
            avg_out_of_3 = round((avg_percent / 100) * 3, 2)
            general_grade, general_descriptor = get_grade_and_descriptor(avg_percent)
            
            all_reports.append({
                'student_id': student_id,
                'full_name': full_name,
                'photo_url': photo_url,
                'marks': marks,
                'avg_out_of_3': avg_out_of_3,
                'general_grade': general_grade,
                'general_descriptor': general_descriptor,
                'teacher_comment': teacher_comment,
                'headteacher_comment': headteacher_comment,
                'is_alevel': False
            })
    
    cur.close()
    
    # Choose template based on level
    template = 'teacher/print_all_report_cards_alevel.html' if is_alevel else 'teacher/print_all_report_cards.html'
    
    return render_template(template,
        reports=all_reports,
        class_name=selected_class,
        term=term,
        year=year,
        next_term_begins=next_term_begins,
        next_term_ends=next_term_ends,
        stamp_url=stamp_url,
        school_name=school_name,
        school_address=school_address,
        school_phone=school_phone,
        school_email=school_email,
        school_logo_url=school_logo_url
    )

# ==================== BURSAR MODULE ====================
def calculate_nssf_and_paye(gross_salary):
    """Calculate NSSF employee contribution and PAYE tax"""
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
    rates = cur.fetchone()
    cur.close()
    
    nssf_employee_rate = rates['nssf_employee_rate'] if rates else 5.0
    paye_rate = rates['paye_rate'] if rates else 10.0
    paye_threshold = rates['paye_threshold'] if rates else 235000
    
    # Calculate NSSF (based on gross salary)
    nssf_employee = (gross_salary * nssf_employee_rate) / 100
    
    # Calculate PAYE (only on amount above threshold)
    taxable_amount = max(0, gross_salary - paye_threshold)
    paye_tax = (taxable_amount * paye_rate) / 100
    
    return {
        'nssf_employee': round(nssf_employee, 2),
        'paye_tax': round(paye_tax, 2)
    }

def generate_receipt_number():
    return generate_unique_number('RCP', 'payments', 'receipt_no', year_format=True)

def send_fee_sms(phone_number, student_name, amount, balance):
    if not phone_number:
        return False
    message = f"Payment of UGX {amount:,.2f} received for {student_name}. Balance: UGX {balance:,.2f}. Thank you."
    return send_sms(phone_number, message)

@app.route('/bursar/dashboard')
def bursar_dashboard():
    if not check_permission(['bursar']):
        abort(403)
    notification_count = get_notification_count('bursar')
    notifications = get_notifications('bursar')
       
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT SUM(fees_total) as total_fees, SUM(fees_paid) as total_paid, SUM(fees_balance) as total_balance FROM students")
    totals = cur.fetchone()
    cur.execute("SELECT COUNT(*) as defaulter_count FROM students WHERE fees_balance > 0")
    defaulter_count = cur.fetchone()
    cur.execute("SELECT COUNT(*) as total_students FROM students")
    total_students = cur.fetchone()
    cur.execute("SELECT p.*, s.full_name, s.class FROM payments p JOIN students s ON p.student_id = s.student_id ORDER BY p.payment_date DESC LIMIT 10")
    recent_payments = cur.fetchall()
    cur.close()
    return render_template('bursar/dashboard.html', totals=totals, notification_count=notification_count,
        notifications=notifications, defaulter_count=defaulter_count['defaulter_count'] if defaulter_count else 0, total_students=total_students['total_students'] if total_students else 0, recent_payments=recent_payments)

@app.route('/bursar/students')
def bursar_students():
    if not check_permission(['bursar']):
        abort(403)
    search = request.args.get('search', '').strip()
    class_filter = request.args.get('class', '').strip()
    cur = mysql.connection.cursor(DictCursor)
    query = "SELECT student_id, full_name, class, parent_phone, fees_total, fees_paid, fees_balance FROM students WHERE 1=1"
    params = []
    if search:
        query += " AND (student_id LIKE %s OR full_name LIKE %s)"
        pattern = f"%{search}%"
        params.extend([pattern, pattern])
    if class_filter:
        query += " AND class = %s"
        params.append(class_filter)
    query += " ORDER BY full_name"
    cur.execute(query, params)
    students = cur.fetchall()
    cur.execute("SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != '' ORDER BY class")
    classes = [row['class'] for row in cur.fetchall()]
    cur.close()
    return render_template('bursar/students.html', students=students, classes=classes, search=search, class_filter=class_filter)

@app.route('/bursar/student/<student_id>')
def bursar_student_detail(student_id):
    if not check_permission(['bursar']):
        abort(403)
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT student_id, full_name, class, parent_phone, fees_total, fees_paid, fees_balance FROM students WHERE student_id=%s", (student_id,))
    student = cur.fetchone()
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('bursar_students'))
    cur.execute("SELECT * FROM payments WHERE student_id=%s ORDER BY payment_date DESC", (student_id,))
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
    cur = mysql.connection.cursor(DictCursor)
    try:
        cur.execute("SELECT full_name, parent_phone, fees_paid, fees_balance FROM students WHERE student_id=%s", (student_id,))
        student = cur.fetchone()
        if not student:
            flash('Student not found.', 'danger')
            return redirect(url_for('bursar_students'))
        cur.execute("INSERT INTO payments (student_id, amount, payment_date, receipt_no, payment_method, notes, recorded_by) VALUES (%s, %s, CURDATE(), %s, %s, %s, %s)", (student_id, amount, receipt_no, payment_method, notes, session.get('username')))
        new_paid = student['fees_paid'] + amount
        new_balance = student['fees_balance'] - amount
        cur.execute("UPDATE students SET fees_paid=%s, fees_balance=%s WHERE student_id=%s", (new_paid, new_balance, student_id))
        mysql.connection.commit()
        if student['parent_phone']:
            send_fee_sms(student['parent_phone'], student['full_name'], amount, new_balance)
        flash(f'Payment recorded. Receipt: {receipt_no}', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error: {str(e)}', 'danger')
    finally:
        cur.close()
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
            cur = mysql.connection.cursor(DictCursor)
            placeholders = ','.join(['%s'] * len(ids))
            cur.execute(f"SELECT p.*, s.full_name, s.class FROM payments p JOIN students s ON p.student_id = s.student_id WHERE p.id IN ({placeholders}) ORDER BY p.payment_date DESC", ids)
            receipts = cur.fetchall()
            cur.close()
    return render_template('bursar/print_receipts.html', receipts=receipts)

@app.route('/bursar/send_reminder/<student_id>')
def bursar_send_reminder(student_id):
    if not check_permission(['bursar']):
        abort(403)
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT full_name, parent_phone, fees_balance FROM students WHERE student_id=%s", (student_id,))
    student = cur.fetchone()
    if student and student['parent_phone']:
        send_sms(student['parent_phone'], f"Fees reminder: UGX {student['fees_balance']:,.2f} outstanding for {student['full_name']}.")
        flash('Reminder sent.', 'success')
    else:
        flash('No parent phone.', 'warning')
    cur.close()
    return redirect(url_for('bursar_student_detail', student_id=student_id))

@app.route('/bursar/bulk_reminder', methods=['POST'])
def bursar_bulk_reminder():
    if not check_permission(['bursar']):
        abort(403)
    class_filter = request.form.get('class', '')
    cur = mysql.connection.cursor(DictCursor)
    query = "SELECT full_name, parent_phone, fees_balance FROM students WHERE fees_balance > 0"
    if class_filter:
        query += f" AND class = %s"
        cur.execute(query, (class_filter,))
    else:
        cur.execute(query)
    students = cur.fetchall()
    sent = 0
    for s in students:
        if s['parent_phone']:
            send_sms(s['parent_phone'], f"Fees reminder: UGX {s['fees_balance']:,.2f} outstanding for {s['full_name']}.")
            sent += 1
    cur.close()
    flash(f'{sent} reminders sent.', 'success')
    return redirect(url_for('bursar_students'))

@app.route('/bursar/webhook/process')
def bursar_process_webhooks():
    if not check_permission(['bursar']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT * FROM payment_webhooks WHERE processed=0")
    webhooks = cur.fetchall()
    processed = 0
    
    for w in webhooks:
        if w.get('student_id'):
            # Auto-record payment for the student
            cur.execute("SELECT full_name, parent_phone, fees_paid, fees_balance FROM students WHERE student_id=%s", (w['student_id'],))
            student = cur.fetchone()
            if student:
                receipt_no = generate_receipt_number()
                cur.execute("""
                    INSERT INTO payments (student_id, amount, payment_date, receipt_no, payment_method, notes, recorded_by)
                    VALUES (%s, %s, CURDATE(), %s, %s, %s, %s)
                """, (w['student_id'], w['amount'], receipt_no, w.get('payment_method', 'Mobile Money'), 
                      f"Auto from webhook: {w.get('transaction_id', '')}", 'System'))
                
                # Update student fees
                new_paid = student['fees_paid'] + w['amount']
                new_balance = student['fees_balance'] - w['amount']
                cur.execute("UPDATE students SET fees_paid=%s, fees_balance=%s WHERE student_id=%s", (new_paid, new_balance, w['student_id']))
                mysql.connection.commit()
                
                # Send SMS confirmation
                if student.get('parent_phone'):
                    send_fee_sms(student['parent_phone'], student['full_name'], w['amount'], new_balance)
        
        # Mark webhook as processed
        cur.execute("UPDATE payment_webhooks SET processed=1 WHERE id=%s", (w['id'],))
        processed += 1
    
    mysql.connection.commit()
    cur.close()
    
    flash(f'Processed {processed} pending webhooks.', 'success')
    return redirect(url_for('bursar_dashboard'))

@app.route('/bursar/webhook/payment', methods=['POST'])
def bursar_payment_webhook():
    """Endpoint for payment gateway to send payment notifications"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid data'}), 400
    
    # Store raw webhook data
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("""
        INSERT INTO payment_webhooks (transaction_id, amount, phone_number, student_id, reference, payment_method, raw_data, status, processed)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
    """, (data.get('transaction_id'), data.get('amount'), data.get('phone_number'), data.get('student_id'), 
          data.get('reference'), data.get('payment_method'), json.dumps(data), 'received'))
    mysql.connection.commit()
    cur.close()
    
    return jsonify({'status': 'received'}), 200

@app.route('/bursar/bulk_clearance')
def bursar_bulk_clearance():
    if not check_permission(['bursar']):
        abort(403)
    
    class_filter = request.args.get('class', '')
    cur = mysql.connection.cursor(DictCursor)
    
    query = "SELECT student_id, full_name, class, parent_phone, fees_balance, photo_path FROM students WHERE fees_balance <= 0"
    if class_filter:
        query += " AND class = %s"
        cur.execute(query, (class_filter,))
    else:
        cur.execute(query)
    
    students = cur.fetchall()
    
    # Add photo URLs
    for s in students:
        photo_path = s.get('photo_path')
        if photo_path and photo_path != 'default_avatar.png':
            s['photo_url'] = url_for('static', filename='uploads/' + photo_path)
        else:
            s['photo_url'] = url_for('static', filename='uploads/default_avatar.png')
    
    cur.close()
    
    return render_template('bursar/bulk_clearance.html', students=students)

@app.route('/bursar/clearance/<student_id>')
def bursar_clearance(student_id):
    if not check_permission(['bursar']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT student_id, full_name, class, parent_phone, fees_balance, photo_path FROM students WHERE student_id=%s", (student_id,))
    student = cur.fetchone()
    
    if not student:
        flash('Student not found', 'danger')
        return redirect(url_for('bursar_students'))
    
    # Get photo URL
    photo_path = student.get('photo_path')
    if photo_path and photo_path != 'default_avatar.png':
        student['photo_url'] = url_for('static', filename='uploads/' + photo_path)
    else:
        student['photo_url'] = url_for('static', filename='uploads/default_avatar.png')
    
    cur.close()
    return render_template('bursar/clearance.html', student=student)

# ==================== STAFF PAYROLL ====================
def generate_staff_no():
    return generate_unique_number('STF', 'staff', 'staff_no', year_format=True)

def generate_payroll_no():
    """Generate unique payroll number: PR-202401-0001 format"""
    year_month = datetime.now().strftime("%Y%m")
    cur = mysql.connection.cursor()
    cur.execute("SELECT payroll_no FROM payroll WHERE payroll_no LIKE %s ORDER BY payroll_no DESC LIMIT 1", (f'PR-{year_month}-%',))
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
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT * FROM staff ORDER BY full_name")
    staff = cur.fetchall()
    
    # Get NSSF and PAYE rates
    cur.execute("SELECT nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
    rates = cur.fetchone()
    
    nssf_rate = rates['nssf_employee_rate'] if rates else 5.0
    paye_rate = rates['paye_rate'] if rates else 10.0
    paye_threshold = rates['paye_threshold'] if rates else 235000
    
    # Calculate totals and add NSSF/PAYE to each staff
    total_basic = 0
    total_allowances = 0
    total_gross = 0
    total_nssf = 0
    total_paye = 0
    total_deductions = 0
    total_net = 0
    
    for s in staff:
        gross = s['salary_basic'] + (s['salary_allowances'] or 0)
        nssf = (gross * nssf_rate) / 100
        taxable = max(0, gross - paye_threshold)
        paye = (taxable * paye_rate) / 100
        net = gross - nssf - paye - (s['salary_deductions'] or 0)
        
        s['gross'] = gross
        s['nssf'] = round(nssf, 2)
        s['paye'] = round(paye, 2)
        s['net'] = net
        
        total_basic += s['salary_basic']
        total_allowances += (s['salary_allowances'] or 0)
        total_gross += gross
        total_nssf += nssf
        total_paye += paye
        total_deductions += (s['salary_deductions'] or 0)
        total_net += net
    
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
        
        cur = mysql.connection.cursor()
        try:
            cur.execute("""
                INSERT INTO staff (staff_no, full_name, position, department, phone, email, 
                                   nssf_number, tin_number, bank_account, bank_name, 
                                   salary_basic, salary_allowances, salary_deductions) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (staff_no, full_name, position, department, phone, email, nssf_number, tin_number,
                  bank_account, bank_name, salary_basic, salary_allowances, salary_deductions))
            mysql.connection.commit()
            flash(f'Staff {full_name} added. Staff No: {staff_no}', 'success')
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Error: {str(e)}', 'danger')
        finally:
            cur.close()
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
        
        cur = mysql.connection.cursor(DictCursor)
        
        # Get NSSF and PAYE rates
        cur.execute("SELECT nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
        rates = cur.fetchone()
        
        nssf_rate = rates['nssf_employee_rate'] if rates else 5.0
        paye_rate = rates['paye_rate'] if rates else 10.0
        paye_threshold = rates['paye_threshold'] if rates else 235000
        
        # FIXED: Create proper placeholders for IN clause
        placeholders = ','.join(['%s'] * len(selected_staff))
        query = f"SELECT * FROM staff WHERE id IN ({placeholders})"
        cur.execute(query, selected_staff)  # Pass the list directly
        staff_list = cur.fetchall()
        
        total_amount = 0
        for staff in staff_list:
            gross = staff['salary_basic'] + (staff['salary_allowances'] or 0)
            nssf = (gross * nssf_rate) / 100
            taxable = max(0, gross - paye_threshold)
            paye = (taxable * paye_rate) / 100
            net = gross - nssf - paye - (staff['salary_deductions'] or 0)
            total_amount += net
        
        payroll_no = generate_payroll_no()
        approval_code = generate_approval_code()
        token, expires_at = generate_secure_token(2)
        
        cur.execute("""
            INSERT INTO payroll (payroll_no, month_year, total_amount, approval_code, headteacher_access_token, token_expires_at, recorded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (payroll_no, month_year, total_amount, approval_code, token, expires_at, session.get('username')))
        payroll_id = cur.lastrowid
        
        # Create individual salary payment records
        for staff in staff_list:
            gross = staff['salary_basic'] + (staff['salary_allowances'] or 0)
            nssf = (gross * nssf_rate) / 100
            taxable = max(0, gross - paye_threshold)
            paye = (taxable * paye_rate) / 100
            net_salary = gross - nssf - paye - (staff['salary_deductions'] or 0)
            
            cur.execute("""
                INSERT INTO salary_payments 
                (staff_id, payroll_id, month_year, basic, allowances, deductions, 
                 gross_salary, nssf_employee, paye_tax, net_salary, approval_code, recorded_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (staff['id'], payroll_id, month_year, staff['salary_basic'], staff['salary_allowances'] or 0, 
                  staff['salary_deductions'] or 0, gross, nssf, paye, net_salary, approval_code, session.get('username')))
        
        mysql.connection.commit()
        
        # Send approval link to headteacher
        approval_link = url_for('headteacher_approval_access', token=token, _external=True)
        cur.execute("SELECT phone FROM users WHERE role='headteacher' AND status=1 LIMIT 1")
        headteacher = cur.fetchone()
        
        if headteacher and headteacher.get('phone'):
            send_sms(headteacher['phone'], 
                f"PAYROLL APPROVAL NEEDED: {payroll_no} - UGX {total_amount:,.2f}. Approval code: {approval_code}. Link: {approval_link}")
        
        add_notification('headteacher', 
            f"Payroll {payroll_no} needs approval. Code: {approval_code}", 
            f"/headteacher/approval/{token}")
        
        cur.close()
        flash(f'Payroll {payroll_no} created. Approval link sent to Headteacher.', 'success')
        return redirect(url_for('bursar_payroll_list'))
    
    # GET request - show staff selection form
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT * FROM staff WHERE status='active' ORDER BY full_name")
    staff_list = cur.fetchall()
    cur.close()
    return render_template('bursar/generate_payroll.html', staff_list=staff_list)

@app.route('/bursar/payroll/list')
def bursar_payroll_list():
    if not check_permission(['bursar']):
        abort(403)
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT p.*, COUNT(sp.id) as staff_count FROM payroll p LEFT JOIN salary_payments sp ON p.id = sp.payroll_id GROUP BY p.id ORDER BY p.created_at DESC")
    payrolls = cur.fetchall()
    cur.close()
    return render_template('bursar/payroll_list.html', payrolls=payrolls)

# ==================== BURSAR PRINT FUNCTIONS ====================

@app.route('/bursar/print_payroll')
def bursar_print_payroll():
    if not check_permission(['bursar']):
        abort(403)
    
    staff_ids = request.args.get('staff_ids', '')
    
    cur = mysql.connection.cursor(DictCursor)
    
    if staff_ids:
        ids = [int(x) for x in staff_ids.split(',') if x.isdigit()]
        if ids:
            placeholders = ','.join(['%s'] * len(ids))
            cur.execute(f"""
                SELECT staff_no, full_name, position, salary_basic, salary_allowances, salary_deductions, salary_net
                FROM staff 
                WHERE id IN ({placeholders})
                ORDER BY full_name
            """, ids)
        else:
            staff_list = []
    else:
        cur.execute("""
            SELECT staff_no, full_name, position, salary_basic, salary_allowances, salary_deductions, salary_net
            FROM staff 
            ORDER BY full_name
        """)
    
    staff_list = cur.fetchall()
    
    # Get NSSF and PAYE rates
    cur.execute("SELECT nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
    rates = cur.fetchone()
    cur.close()
    
    # Calculate NSSF and PAYE for each staff
    total_basic = 0
    total_allowances = 0
    total_gross = 0
    total_nssf = 0
    total_paye = 0
    total_deductions = 0
    total_net = 0
    
    for s in staff_list:
        gross = s['salary_basic'] + s['salary_allowances']
        nssf = (gross * (rates['nssf_employee_rate'] if rates else 5)) / 100
        taxable = max(0, gross - (rates['paye_threshold'] if rates else 235000))
        paye = (taxable * (rates['paye_rate'] if rates else 10)) / 100
        net = gross - nssf - paye - s['salary_deductions']
        
        s['gross'] = gross
        s['nssf_employee'] = round(nssf, 2)
        s['paye_tax'] = round(paye, 2)
        s['net'] = net
        
        total_basic += s['salary_basic']
        total_allowances += s['salary_allowances']
        total_gross += gross
        total_nssf += nssf
        total_paye += paye
        total_deductions += s['salary_deductions']
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
                          nssf_rate=rates['nssf_employee_rate'] if rates else 5,
                          paye_rate=rates['paye_rate'] if rates else 10,
                          paye_threshold=rates['paye_threshold'] if rates else 235000)

@app.route('/admin/nssf_paye_settings', methods=['GET', 'POST'])
def nssf_paye_settings():
    if not check_permission(['admin', 'bursar']):
        abort(403)
    
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        nssf_employee = float(request.form['nssf_employee_rate'])
        paye_rate = float(request.form['paye_rate'])
        paye_threshold = float(request.form['paye_threshold'])
        
        cur.execute("""
            UPDATE school_settings SET 
                nssf_employee_rate = %s, 
                paye_rate = %s, 
                paye_threshold = %s 
            WHERE id = 1
        """, (nssf_employee, paye_rate, paye_threshold))
        mysql.connection.commit()
        flash('NSSF and PAYE settings updated successfully.', 'success')
    
    cur.execute("SELECT nssf_employee_rate, paye_rate, paye_threshold FROM school_settings WHERE id=1")
    settings = cur.fetchone()
    cur.close()
    
    return render_template('admin/nssf_paye_settings.html', settings=settings)


@app.route('/bursar/print_fees_list')
def bursar_print_fees_list():
    if not check_permission(['bursar']):
        abort(403)
    
    class_filter = request.args.get('class', '')
    status_filter = request.args.get('status', '')  # 'all' or 'defaulters'
    
    cur = mysql.connection.cursor(DictCursor)
    
    if status_filter == 'defaulters':
        query = """
            SELECT student_id, full_name, class, fees_paid, fees_balance
            FROM students 
            WHERE fees_balance > 0
        """
        params = []
        if class_filter:
            query += " AND class = %s"
            params.append(class_filter)
        query += " ORDER BY class, full_name"
        cur.execute(query, params)
    else:
        query = """
            SELECT student_id, full_name, class, fees_paid, fees_balance
            FROM students 
            WHERE 1=1
        """
        params = []
        if class_filter:
            query += " AND class = %s"
            params.append(class_filter)
        query += " ORDER BY class, full_name"
        cur.execute(query, params)
    
    students = cur.fetchall()
    cur.close()
    
    # Calculate totals
    total_paid = sum(s['fees_paid'] for s in students) if students else 0
    total_balance = sum(s['fees_balance'] for s in students) if students else 0
    
    return render_template('bursar/print_fees_list.html', 
                          students=students,
                          class_filter=class_filter,
                          status_filter=status_filter,
                          total_paid=total_paid,
                          total_balance=total_balance)

@app.route('/bursar/delete_payroll/<int:payroll_id>')
def bursar_delete_payroll(payroll_id):
    if not check_permission(['bursar']):
        abort(403)
    
    cur = mysql.connection.cursor()
    
    # Check if payroll exists and is pending
    cur.execute("SELECT approval_status FROM payroll WHERE id=%s", (payroll_id,))
    payroll = cur.fetchone()
    
    if not payroll:
        flash('Payroll not found.', 'danger')
        return redirect(url_for('bursar_payroll_list'))
    
    if payroll[0] != 'pending':
        flash('Only pending payrolls can be deleted.', 'warning')
        return redirect(url_for('bursar_payroll_list'))
    
    try:
        # Delete salary payments first (foreign key constraint)
        cur.execute("DELETE FROM salary_payments WHERE payroll_id=%s", (payroll_id,))
        cur.execute("DELETE FROM payroll WHERE id=%s", (payroll_id,))
        mysql.connection.commit()
        flash('Payroll deleted successfully.', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error deleting payroll: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('bursar_payroll_list'))


#@app.route('/bursar/payroll/process/<int:payroll_id>')
#def bursar_process_payroll(payroll_id):
    if not check_permission(['bursar']):
        abort(403)
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT * FROM payroll WHERE id=%s AND approval_status='approved'", (payroll_id,))
    payroll = cur.fetchone()
    if not payroll:
        flash('Payroll not approved.', 'warning')
        return redirect(url_for('bursar_payroll_list'))
    cur.execute("UPDATE salary_payments SET approval_status='paid', payment_date=CURDATE() WHERE payroll_id=%s", (payroll_id,))
    cur.execute("UPDATE payroll SET approval_status='paid' WHERE id=%s", (payroll_id,))
    mysql.connection.commit()
    cur.close()
    flash('Payroll processed.', 'success')
    return redirect(url_for('bursar_payroll_list'))

@app.route('/bursar/view_payroll/<int:payroll_id>')
def bursar_view_payroll(payroll_id):
    if not check_permission(['bursar']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT * FROM payroll WHERE id=%s", (payroll_id,))
    payroll = cur.fetchone()
    
    if not payroll:
        flash('Payroll not found.', 'danger')
        return redirect(url_for('bursar_payroll_list'))
    
    cur.execute("""
        SELECT sp.*, s.full_name, s.position, s.bank_account, s.bank_name, s.phone, s.staff_no
        FROM salary_payments sp
        JOIN staff s ON sp.staff_id = s.id
        WHERE sp.payroll_id = %s
    """, (payroll_id,))
    staff_list = cur.fetchall()
    
    # Calculate totals
    total_basic = sum(s['basic'] for s in staff_list) if staff_list else 0
    total_allowances = sum(s['allowances'] for s in staff_list) if staff_list else 0
    total_deductions = sum(s['deductions'] for s in staff_list) if staff_list else 0
    
    cur.close()
    
    return render_template('bursar/view_payroll.html', 
                          payroll=payroll, 
                          staff_list=staff_list,
                          total_basic=total_basic,
                          total_allowances=total_allowances,
                          total_deductions=total_deductions)



@app.route('/bursar/budget')
def bursar_budget():
    if not check_permission(['bursar']):
        abort(403)
    year = request.args.get('year', datetime.now().year)
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT * FROM budget_categories WHERE year=%s ORDER BY code", (year,))
    categories = cur.fetchall()
    cur.execute("SELECT c.code, c.name, c.allocated_amount, SUM(e.amount) as spent FROM budget_categories c LEFT JOIN expenditures e ON c.id = e.category_id AND e.status='paid' WHERE c.year=%s GROUP BY c.id", (year,))
    summary = cur.fetchall()
    cur.close()
    return render_template('bursar/budget.html', categories=categories, summary=summary, year=year)

@app.route('/bursar/budget/add', methods=['POST'])
def bursar_budget_add():
    if not check_permission(['bursar']):
        abort(403)
    cur = mysql.connection.cursor()
    cur.execute("INSERT INTO budget_categories (code, name, description, allocated_amount, year) VALUES (%s, %s, %s, %s, %s)", (request.form['code'], request.form['name'], request.form.get('description', ''), float(request.form['allocated_amount']), request.form['year']))
    mysql.connection.commit()
    cur.close()
    flash('Budget category added.', 'success')
    return redirect(url_for('bursar_budget', year=request.form['year']))

@app.route('/bursar/expenditure')
def bursar_expenditure():
    if not check_permission(['bursar']):
        abort(403)
    cur = mysql.connection.cursor(DictCursor)
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
    cur = mysql.connection.cursor()
    cur.execute("INSERT INTO expenditures (voucher_no, category_id, description, amount, expenditure_date, payment_method, payee_name, payee_phone, status, recorded_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (voucher_no, request.form['category_id'], request.form['description'], float(request.form['amount']), request.form['expenditure_date'], request.form.get('payment_method', 'Cash'), request.form.get('payee_name', ''), validate_and_format_phone(request.form.get('payee_phone', '')), request.form.get('status', 'paid'), session.get('username')))
    mysql.connection.commit()
    cur.close()
    flash(f'Expenditure recorded. Voucher: {voucher_no}', 'success')
    return redirect(url_for('bursar_expenditure'))

@app.route('/bursar/income_report')
def bursar_income_report():
    if not check_permission(['bursar']):
        abort(403)
    start = request.args.get('start_date', datetime.now().replace(day=1).strftime('%Y-%m-%d'))
    end = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT DATE(payment_date) as date, SUM(amount) as total FROM payments WHERE payment_date BETWEEN %s AND %s GROUP BY DATE(payment_date) ORDER BY date DESC", (start, end))
    daily = cur.fetchall()
    cur.execute("SELECT payment_method, SUM(amount) as total FROM payments WHERE payment_date BETWEEN %s AND %s GROUP BY payment_method", (start, end))
    by_method = cur.fetchall()
    cur.execute("SELECT SUM(amount) as total_income FROM payments WHERE payment_date BETWEEN %s AND %s", (start, end))
    total = cur.fetchone()
    cur.close()
    return render_template('bursar/income_report.html', daily=daily, by_method=by_method, total=total, start_date=start, end_date=end)

@app.route('/bursar/expenditure_report')
def bursar_expenditure_report():
    if not check_permission(['bursar']):
        abort(403)
    start = request.args.get('start_date', datetime.now().replace(day=1).strftime('%Y-%m-%d'))
    end = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT c.code, c.name, SUM(e.amount) as total_spent FROM expenditures e JOIN budget_categories c ON e.category_id = c.id WHERE e.expenditure_date BETWEEN %s AND %s AND e.status='paid' GROUP BY c.id ORDER BY total_spent DESC", (start, end))
    by_category = cur.fetchall()
    cur.execute("SELECT SUM(amount) as total_expenditure FROM expenditures WHERE expenditure_date BETWEEN %s AND %s AND status='paid'", (start, end))
    total = cur.fetchone()
    cur.close()
    return render_template('bursar/expenditure_report.html', by_category=by_category, total=total, start_date=start, end_date=end)

@app.route('/bursar/school_pay/config', methods=['GET', 'POST'])
def bursar_school_pay_config():
    if not check_permission(['bursar']):
        abort(403)
    cur = mysql.connection.cursor(DictCursor)
    if request.method == 'POST':
        cur.execute("UPDATE payment_gateway_config SET api_key=%s, api_secret=%s, webhook_secret=%s, callback_url=%s, status=%s WHERE id=1", (request.form['api_key'], request.form['api_secret'], request.form['webhook_secret'], request.form['callback_url'], request.form.get('status', 'inactive')))
        mysql.connection.commit()
        flash('Configuration saved.', 'success')
    cur.execute("SELECT * FROM payment_gateway_config WHERE id=1")
    config = cur.fetchone()
    cur.close()
    return render_template('bursar/school_pay_config.html', config=config)


# ==================== HEADTEACHER & MANAGEMENT APPROVAL ====================
@app.route('/headteacher/approvals')
def headteacher_approvals():
    if not check_permission(['headteacher']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("""
        SELECT p.*, COUNT(sp.id) as staff_count
        FROM payroll p
        LEFT JOIN salary_payments sp ON p.id = sp.payroll_id
        WHERE p.approval_status = 'pending'
        GROUP BY p.id
        ORDER BY p.created_at DESC
    """)
    pending = cur.fetchall()
    cur.close()
    
    return render_template('headteacher/approvals.html', pending=pending)
@app.route('/headteacher/approval/<token>', methods=['GET', 'POST'])
def headteacher_approval_access(token):
    if not check_permission(['headteacher']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    
    # Get payroll by token
    cur.execute("SELECT * FROM payroll WHERE headteacher_access_token = %s", (token,))
    payroll = cur.fetchone()
    
    if not payroll:
        flash('Invalid approval link.', 'danger')
        return redirect(url_for('headteacher_approvals'))
    
    # Check if already approved/rejected
    if payroll['approval_status'] != 'pending':
        flash(f'This payroll has already been {payroll["approval_status"]}.', 'warning')
        return redirect(url_for('headteacher_approvals'))
    
    # Check expiration
    if payroll.get('token_expires_at') and payroll['token_expires_at'] <= datetime.now():
        flash('This approval link has expired. Please request a new link.', 'danger')
        return redirect(url_for('headteacher_approvals'))
    
    if request.method == 'POST':
        approval_code = request.form.get('approval_code')
        action = request.form.get('action')
        
        # Verify approval code
        if payroll['approval_code'] != approval_code:
            flash('Invalid approval code.', 'danger')
            return redirect(url_for('headteacher_approval_access', token=token))
        
        if action == 'approve':
            # Generate management approval code and token
            mgmt_code = generate_approval_code()
            mgmt_token, mgmt_expires = generate_secure_token(2)
            
            # Update payroll
            cur.execute("""
                UPDATE payroll SET 
                    approval_status = 'approved', 
                    approved_by = %s, 
                    approved_at = NOW(),
                    management_approval_code = %s,
                    management_access_token = %s,
                    management_token_expires_at = %s,
                    management_approval_status = 'pending'
                WHERE id = %s
            """, ('Headteacher', mgmt_code, mgmt_token, mgmt_expires, payroll['id']))
            
            # Update salary payments
            cur.execute("UPDATE salary_payments SET approval_status = 'approved' WHERE payroll_id = %s", (payroll['id'],))
            mysql.connection.commit()
            
            # Send SMS to management
            management_link = url_for('management_authorization_access', token=mgmt_token, _external=True)
            expires_str = mgmt_expires.strftime('%Y-%m-%d %H:%M:%S')
            
            cur.execute("SELECT phone FROM users WHERE role='management' AND status=1")
            management_users = cur.fetchall()
            
            for mgmt in management_users:
                if mgmt.get('phone'):
                    send_sms(mgmt['phone'], 
                        f"BANK AUTHORIZATION NEEDED: Payroll {payroll['payroll_no']} - UGX {payroll['total_amount']:,.2f}. "
                        f"Code: {mgmt_code}. Expires: {expires_str}. Link: {management_link}")
            
            # Add notification
            add_notification('management', 
                f"Payroll {payroll['payroll_no']} needs bank authorization. Code: {mgmt_code}", 
                f"/management/authorization/{mgmt_token}")
            
            flash('Payroll approved. Management notified for bank authorization.', 'success')
            
        elif action == 'reject':
            # Reject payroll
            cur.execute("UPDATE payroll SET approval_status='rejected', approved_by=%s, approved_at=NOW() WHERE id=%s", ('Headteacher', payroll['id']))
            cur.execute("UPDATE salary_payments SET approval_status='rejected' WHERE payroll_id=%s", (payroll['id'],))
            mysql.connection.commit()
            
            # Notify bursar
            add_notification('bursar', f"Payroll {payroll['payroll_no']} was REJECTED by Headteacher.", '/bursar/payroll/list')
            
            flash('Payroll rejected.', 'warning')
        
        cur.close()
        return redirect(url_for('headteacher_approvals'))
    
    # Calculate remaining time
    remaining_minutes = None
    if payroll.get('token_expires_at'):
        remaining = payroll['token_expires_at'] - datetime.now()
        remaining_minutes = int(remaining.total_seconds() / 60)
    
    cur.close()
    
    return render_template('headteacher/approve_payroll_secure.html', 
                          payroll=payroll, 
                          remaining_minutes=remaining_minutes)
    
@app.route('/headteacher/reject_payroll/<int:payroll_id>')
def headteacher_reject_payroll(payroll_id):
    if not check_permission(['headteacher']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    
    # Check if payroll exists and is pending
    cur.execute("SELECT * FROM payroll WHERE id=%s AND approval_status='pending'", (payroll_id,))
    payroll = cur.fetchone()
    
    if not payroll:
        flash('Payroll not found or already processed.', 'danger')
        return redirect(url_for('headteacher_approvals'))
    
    try:
        # Update payroll status to rejected
        cur.execute("UPDATE payroll SET approval_status='rejected', approved_by=%s, approved_at=NOW() WHERE id=%s", ('Headteacher', payroll_id))
        cur.execute("UPDATE salary_payments SET approval_status='rejected' WHERE payroll_id=%s", (payroll_id,))
        mysql.connection.commit()
        
        # Notify bursar
        add_notification('bursar', f"Payroll {payroll['payroll_no']} has been REJECTED by Headteacher.", '/bursar/payroll/list')
        
        flash(f'Payroll {payroll["payroll_no"]} has been rejected.', 'warning')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error rejecting payroll: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('headteacher_approvals'))

@app.route('/headteacher/resend_token/<int:payroll_id>')
def headteacher_resend_token(payroll_id):
    if not check_permission(['headteacher']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT * FROM payroll WHERE id=%s AND approval_status='pending'", (payroll_id,))
    payroll = cur.fetchone()
    
    if not payroll:
        flash('Payroll not found or already processed.', 'danger')
        return redirect(url_for('headteacher_approvals'))
    
    # Check resend limit (max 3 resends)
    if payroll.get('token_resend_count', 0) >= 3:
        flash('Maximum token resend limit reached (3). Please create a new payroll.', 'danger')
        return redirect(url_for('headteacher_approvals'))
    
    # Generate new token
    new_token, new_expires = generate_secure_token(2)
    
    # Update payroll with new token
    cur.execute("""
        UPDATE payroll SET 
            headteacher_access_token = %s,
            token_expires_at = %s,
            token_resend_count = token_resend_count + 1,
            last_resend_at = NOW()
        WHERE id = %s
    """, (new_token, new_expires, payroll_id))
    mysql.connection.commit()
    
    # Send new SMS
    approval_link = url_for('headteacher_approval_access', token=new_token, _external=True)
    expires_str = new_expires.strftime('%Y-%m-%d %H:%M:%S')
    
    # Get headteacher phone
    cur.execute("SELECT phone FROM users WHERE role='headteacher' AND status=1 LIMIT 1")
    headteacher = cur.fetchone()
    
    if headteacher and headteacher.get('phone'):
        send_sms(headteacher['phone'], 
            f"NEW LINK: Payroll {payroll['payroll_no']} - UGX {payroll['total_amount']:,.2f}. Code: {payroll['approval_code']}. Expires: {expires_str}. Link: {approval_link}")
    
    cur.close()
    
    flash(f'New approval link sent! Expires at {expires_str}.', 'success')
    return redirect(url_for('headteacher_approvals'))

@app.route('/management/authorization/<token>', methods=['GET', 'POST'])
def management_authorization_access(token):
    if not check_permission(['management']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    
    # Get payroll by management token
    cur.execute("SELECT * FROM payroll WHERE management_access_token = %s", (token,))
    payroll = cur.fetchone()
    
    if not payroll:
        flash('Invalid authorization link.', 'danger')
        return redirect(url_for('management_pending_authorizations'))
    
    # Check status
    if payroll['management_approval_status'] != 'pending':
        flash(f'This authorization has already been {payroll["management_approval_status"]}.', 'warning')
        return redirect(url_for('management_pending_authorizations'))
    
    if payroll['approval_status'] != 'approved':
        flash('Payroll has not been approved by Headteacher yet.', 'warning')
        return redirect(url_for('management_pending_authorizations'))
    
    # Check expiration
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
            # Process bank payment
            result = process_bank_payment(payroll)
            
            if result['success']:
                cur.execute("""
                    UPDATE payroll SET 
                        management_approval_status = 'approved',
                        management_approved_by = 'Management',
                        management_approved_at = NOW(),
                        bank_authorization_token = %s,
                        bank_transaction_ref = %s,
                        bank_payment_status = 'completed'
                    WHERE id = %s
                """, (result['token'], result['reference'], payroll['id']))
                
                cur.execute("""
                    UPDATE salary_payments SET 
                        approval_status = 'paid', 
                        payment_date = CURDATE(), 
                        transaction_ref = %s 
                    WHERE payroll_id = %s
                """, (result['reference'], payroll['id']))
                
                mysql.connection.commit()
                
                # Notify bursar
                add_notification('bursar', f"Payroll {payroll['payroll_no']} has been paid. Reference: {result['reference']}", '/bursar/payroll/list')
                
                flash(f'Payment authorized and processed! Reference: {result["reference"]}', 'success')
            else:
                cur.execute("UPDATE payroll SET bank_payment_status='failed', bank_payment_response=%s WHERE id=%s", (result['error'], payroll['id']))
                mysql.connection.commit()
                flash(f'Payment failed: {result["error"]}', 'danger')
        
        elif action == 'reject':
            cur.execute("UPDATE payroll SET management_approval_status='rejected', management_approved_by=%s, management_approved_at=NOW() WHERE id=%s", ('Management', payroll['id']))
            cur.execute("UPDATE salary_payments SET approval_status='rejected' WHERE payroll_id=%s", (payroll['id'],))
            mysql.connection.commit()
            
            add_notification('headteacher', f"Payroll {payroll['payroll_no']} authorization was REJECTED by Management.", '/headteacher/approvals')
            add_notification('bursar', f"Payroll {payroll['payroll_no']} was REJECTED by Management.", '/bursar/payroll/list')
            
            flash('Payment authorization rejected.', 'warning')
        
        cur.close()
        return redirect(url_for('management_pending_authorizations'))
    
    # Calculate remaining time
    remaining_minutes = None
    if payroll.get('management_token_expires_at'):
        remaining = payroll['management_token_expires_at'] - datetime.now()
        remaining_minutes = int(remaining.total_seconds() / 60)
    
    cur.close()
    
    return render_template('management/authorize_payment_secure.html', 
                          payroll=payroll, 
                          remaining_minutes=remaining_minutes)

@app.route('/headteacher/view_payroll/<int:payroll_id>')
def headteacher_view_payroll(payroll_id):
    if not check_permission(['headteacher']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT * FROM payroll WHERE id=%s", (payroll_id,))
    payroll = cur.fetchone()
    
    if not payroll:
        flash('Payroll not found.', 'danger')
        return redirect(url_for('headteacher_approvals'))
    
    cur.execute("""
        SELECT sp.*, s.full_name, s.position
        FROM salary_payments sp
        JOIN staff s ON sp.staff_id = s.id
        WHERE sp.payroll_id = %s
    """, (payroll_id,))
    staff_list = cur.fetchall()
    cur.close()
    
    return render_template('headteacher/view_payroll.html', payroll=payroll, staff_list=staff_list)

@app.route('/management/pending')
def management_pending_authorizations():
    if not check_permission(['management']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("""
        SELECT p.*, COUNT(sp.id) as staff_count
        FROM payroll p
        LEFT JOIN salary_payments sp ON p.id = sp.payroll_id
        WHERE p.management_approval_status = 'pending' AND p.approval_status = 'approved'
        GROUP BY p.id
        ORDER BY p.created_at DESC
    """)
    pending = cur.fetchall()
    cur.close()
    
    return render_template('management/pending.html', pending=pending)

@app.route('/headteacher/update_comment', methods=['POST'])
def headteacher_update_comment():
    if not check_permission(['headteacher']):
        abort(403)
    
    student_id = request.form['student_id']
    term = request.form['term']
    year = request.form['year']
    comment = request.form.get('comment', '').strip()
    custom_comment = request.form.get('custom_comment', '').strip()
    
    # Use custom comment if provided, otherwise use selected predefined comment
    final_comment = custom_comment if custom_comment else comment
    
    cur = mysql.connection.cursor()
    
    # Check if comment already exists and is locked
    cur.execute("SELECT headteacher_comment_locked FROM teacher_comments WHERE student_id=%s AND term=%s AND year=%s", (student_id, term, year))
    existing = cur.fetchone()
    
    if existing and existing[0] == 1:
        flash('Comment cannot be edited as it has been locked.', 'danger')
        return redirect(url_for('teacher_report_card', student_id=student_id, term=term, year=year))
    
    # Insert or update comment with lock
    cur.execute("""
        INSERT INTO teacher_comments (student_id, term, year, headteacher_comment, headteacher_comment_locked) 
        VALUES (%s, %s, %s, %s, 1) 
        ON DUPLICATE KEY UPDATE headteacher_comment=%s, headteacher_comment_locked=1
    """, (student_id, term, year, final_comment, final_comment))
    mysql.connection.commit()
    cur.close()
    
    flash('Headteacher comment saved and locked.', 'success')
    return redirect(url_for('teacher_report_card', student_id=student_id, term=term, year=year))

@app.route('/management/resend_token/<int:payroll_id>')
def management_resend_token(payroll_id):
    if not check_permission(['management']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("""
        SELECT * FROM payroll 
        WHERE id=%s AND management_approval_status='pending' AND approval_status='approved'
    """, (payroll_id,))
    payroll = cur.fetchone()
    
    if not payroll:
        flash('Payroll not found or already authorized.', 'danger')
        return redirect(url_for('management_pending_authorizations'))
    
    # Check resend limit (max 3 resends)
    if payroll.get('token_resend_count', 0) >= 3:
        flash('Maximum token resend limit reached (3). Please contact headteacher.', 'danger')
        return redirect(url_for('management_pending_authorizations'))
    
    # Generate new token
    new_token, new_expires = generate_secure_token(2)
    
    # Update payroll with new token
    cur.execute("""
        UPDATE payroll SET 
            management_access_token = %s,
            management_token_expires_at = %s,
            token_resend_count = token_resend_count + 1,
            last_resend_at = NOW()
        WHERE id = %s
    """, (new_token, new_expires, payroll_id))
    mysql.connection.commit()
    
    # Send new SMS
    auth_link = url_for('management_authorization_access', token=new_token, _external=True)
    expires_str = new_expires.strftime('%Y-%m-%d %H:%M:%S')
    
    # Get management phone
    cur.execute("SELECT phone FROM users WHERE role='management' AND status=1 LIMIT 1")
    management_user = cur.fetchone()
    
    if management_user and management_user.get('phone'):
        send_sms(management_user['phone'], 
            f"NEW LINK: Authorize Payroll {payroll['payroll_no']} - UGX {payroll['total_amount']:,.2f}. Code: {payroll['management_approval_code']}. Expires: {expires_str}. Link: {auth_link}")
    
    cur.close()
    
    flash(f'New authorization link sent! Expires at {expires_str}.', 'success')
    return redirect(url_for('management_pending_authorizations'))

@app.route('/headteacher/students')
def headteacher_students():
    if not check_permission(['headteacher']):
        abort(403)
    
    search = request.args.get('search', '')
    class_filter = request.args.get('class', '')
    
    cur = mysql.connection.cursor(DictCursor)
    query = "SELECT student_id, full_name, class, photo_path FROM students WHERE 1=1"
    params = []
    
    if search:
        query += " AND (student_id LIKE %s OR full_name LIKE %s)"
        pattern = f"%{search}%"
        params.extend([pattern, pattern])
    if class_filter:
        query += " AND class = %s"
        params.append(class_filter)
    query += " ORDER BY class, full_name"
    
    cur.execute(query, params)
    students = cur.fetchall()
    
    for s in students:
        if s['photo_path'] and s['photo_path'] != 'default_avatar.png':
            s['photo_url'] = url_for('static', filename='uploads/' + s['photo_path'])
        else:
            s['photo_url'] = url_for('static', filename='uploads/default_avatar.png')
    
    cur.execute("SELECT DISTINCT class FROM students WHERE class IS NOT NULL ORDER BY class")
    classes = [row['class'] for row in cur.fetchall()]
    cur.close()
    
    return render_template('headteacher/students.html', students=students, classes=classes, search=search, class_filter=class_filter)

@app.route('/management/reject_authorization/<int:payroll_id>')
def management_reject_authorization(payroll_id):
    if not check_permission(['management']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    
    # Check if payroll exists and is pending authorization
    cur.execute("SELECT * FROM payroll WHERE id=%s AND management_approval_status='pending' AND approval_status='approved'", (payroll_id,))
    payroll = cur.fetchone()
    
    if not payroll:
        flash('Payroll not found or already processed.', 'danger')
        return redirect(url_for('management_pending_authorizations'))
    
    try:
        # Update payroll status to rejected
        cur.execute("UPDATE payroll SET management_approval_status='rejected', management_approved_by=%s, management_approved_at=NOW() WHERE id=%s", ('Management', payroll_id))
        cur.execute("UPDATE salary_payments SET approval_status='rejected' WHERE payroll_id=%s", (payroll_id,))
        mysql.connection.commit()
        
        # Notify headteacher and bursar
        add_notification('headteacher', f"Payroll {payroll['payroll_no']} authorization has been REJECTED by Management.", '/headteacher/approvals')
        add_notification('bursar', f"Payroll {payroll['payroll_no']} authorization has been REJECTED by Management.", '/bursar/payroll/list')
        
        flash(f'Payroll {payroll["payroll_no"]} authorization has been rejected.', 'warning')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error rejecting authorization: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('management_pending_authorizations'))

def process_bank_payment(payroll):
    """Demo payment processor - replace with real API"""
    import random
    results = {'success': False, 'token': None, 'reference': None, 'error': None}
    if random.random() > 0.1:
        results['success'] = True
        results['token'] = f"TOKEN-{payroll['payroll_no']}"
        results['reference'] = f"REF-{payroll['payroll_no']}-{int(time.time())}"
    else:
        results['error'] = "Bank API temporarily unavailable"
    return results


@app.route('/management/view_payroll/<int:payroll_id>')
def management_view_payroll(payroll_id):
    if not check_permission(['management']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    
    # Get payroll details
    cur.execute("SELECT * FROM payroll WHERE id=%s", (payroll_id,))
    payroll = cur.fetchone()
    
    if not payroll:
        flash('Payroll not found.', 'danger')
        return redirect(url_for('management_pending_authorizations'))
    
    # Get staff list for this payroll
    cur.execute("""
        SELECT sp.*, s.full_name, s.position, s.bank_account, s.bank_name, s.phone, 
               s.nssf_number, s.tin_number
        FROM salary_payments sp
        JOIN staff s ON sp.staff_id = s.id
        WHERE sp.payroll_id = %s
    """, (payroll_id,))
    staff_list = cur.fetchall()
    cur.close()
    
    return render_template('management/view_payroll.html', 
                          payroll=payroll, 
                          staff_list=staff_list)

# ==================== UPLOADS & MISC ====================
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.template_filter('currency')
def currency_filter(value):
    return "{:,.2f}".format(float(value)) if value else '0.00'

@app.template_filter('word_format')
def word_format(value):
    words = {1: 'One', 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight', 9: 'Nine', 10: 'Ten'}
    return words.get(int(value), str(value)) if value else 'Zero'

# ==================== INVENTORY MODULE ====================

# Generate unique item code
def generate_item_code(category_name):
    prefix = category_name[:3].upper()
    year = datetime.now().strftime("%Y")
    cur = mysql.connection.cursor()
    cur.execute("SELECT item_code FROM inventory_items WHERE item_code LIKE %s ORDER BY item_code DESC LIMIT 1", (f'{prefix}-{year}-%',))
    last = cur.fetchone()
    cur.close()
    if last:
        last_num = int(last[0].split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1
    return f"{prefix}-{year}-{new_num:04d}"

def check_low_stock_alerts():
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("""
        SELECT i.*, c.name as category_name, c.warning_level
        FROM inventory_items i
        JOIN inventory_categories c ON i.category_id = c.id
        WHERE i.quantity <= i.reorder_level AND i.status = 'working'
    """)
    low_stock_items = cur.fetchall()
    
    for item in low_stock_items:
        cur.execute("SELECT id FROM inventory_alerts WHERE item_id=%s AND alert_type='low_stock' AND is_read=0", (item['id'],))
        existing = cur.fetchone()
        if not existing:
            cur.execute("""
                INSERT INTO inventory_alerts (item_id, alert_type, message)
                VALUES (%s, 'low_stock', %s)
            """, (item['id'], f"Stock for {item['name']} is low! Current: {item['quantity']}, Reorder level: {item['reorder_level']}"))
            mysql.connection.commit()
            
            # Notify stores keeper, admin, and bursar
            add_notification('stores_keeper', f"LOW STOCK ALERT: {item['name']} has only {item['quantity']} {item['unit']} left!", '/inventory/items')
            add_notification('admin', f"LOW STOCK ALERT: {item['name']} needs reordering!", '/inventory/items')
            add_notification('bursar', f"LOW STOCK ALERT: {item['name']} needs reordering!", '/inventory/items')
    cur.close()

# Inventory Dashboard
@app.route('/inventory/dashboard')
def inventory_dashboard():
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    
    # Summary statistics
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
    
    # Recent transactions
    cur.execute("""
        SELECT t.*, i.name as item_name, i.item_code
        FROM inventory_transactions t
        JOIN inventory_items i ON t.item_id = i.id
        ORDER BY t.created_at DESC LIMIT 10
    """)
    recent_transactions = cur.fetchall()
    
    # Low stock alerts
    cur.execute("""
        SELECT a.*, i.name as item_name, i.quantity, i.reorder_level
        FROM inventory_alerts a
        JOIN inventory_items i ON a.item_id = i.id
        WHERE a.is_read = 0
        ORDER BY a.created_at DESC
    """)
    alerts = cur.fetchall()
    
    cur.close()
    return render_template('inventory/dashboard.html', 
                          total_items=total_items,
                          low_stock=low_stock,
                          spoilt=spoilt,
                          under_repair=under_repair,
                          total_quantity=total_quantity,
                          total_value=total_value,
                          recent_transactions=recent_transactions,
                          alerts=alerts)

# View all inventory items
@app.route('/inventory/items')
def inventory_items():
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    
    category = request.args.get('category', '')
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    
    cur = mysql.connection.cursor(DictCursor)
    query = """
        SELECT i.*, c.name as category_name 
        FROM inventory_items i
        JOIN inventory_categories c ON i.category_id = c.id
        WHERE 1=1
    """
    params = []
    
    if category:
        query += " AND c.name = %s"
        params.append(category)
    if status:
        query += " AND i.status = %s"
        params.append(status)
    if search:
        query += " AND (i.name LIKE %s OR i.item_code LIKE %s)"
        pattern = f"%{search}%"
        params.extend([pattern, pattern])
    
    query += " ORDER BY i.category_id, i.name"
    cur.execute(query, params)
    items = cur.fetchall()
    
    cur.execute("SELECT * FROM inventory_categories ORDER BY name")
    categories = cur.fetchall()
    cur.close()
    
    return render_template('inventory/items.html', items=items, categories=categories, category=category, status=status, search=search)

# Add new inventory item
@app.route('/inventory/item/add', methods=['GET', 'POST'])
def inventory_item_add():
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    
    if request.method == 'POST':
        category_id = request.form['category_id']
        name = request.form['name']
        unit = request.form['unit']
        quantity = int(request.form['quantity'])
        minimum_quantity = int(request.form.get('minimum_quantity', 0))
        reorder_level = int(request.form.get('reorder_level', 5))
        location = request.form.get('location', '')
        supplier = request.form.get('supplier', '')
        purchase_price = float(request.form.get('purchase_price', 0))
        current_value = quantity * purchase_price
        status = request.form.get('status', 'working')
        responsible_person = request.form.get('responsible_person', '')
        responsible_role = request.form.get('responsible_role', '')
        
        # Get category name for item code
        cur.execute("SELECT name FROM inventory_categories WHERE id=%s", (category_id,))
        category = cur.fetchone()
        item_code = generate_item_code(category['name'])
        
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
             responsible_role, image_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (item_code, name, category_id, unit, quantity, minimum_quantity, reorder_level,
              location, supplier, purchase_price, current_value, status, responsible_person,
              responsible_role, image_path))
        mysql.connection.commit()
        
        # Record initial stock transaction
        transaction_id = cur.lastrowid
        cur.execute("""
            INSERT INTO inventory_transactions 
            (item_id, transaction_type, quantity, unit_price, total_amount, transaction_date, recorded_by, notes)
            VALUES (%s, 'purchase', %s, %s, %s, CURDATE(), %s, 'Initial stock')
        """, (transaction_id, quantity, purchase_price, current_value, session.get('username')))
        mysql.connection.commit()
        
        flash(f'Item {name} added successfully. Code: {item_code}', 'success')
        return redirect(url_for('inventory_items'))
    
    cur.execute("SELECT * FROM inventory_categories ORDER BY name")
    categories = cur.fetchall()
    cur.close()
    return render_template('inventory/item_add.html', categories=categories)

# Edit inventory item
@app.route('/inventory/item/edit/<int:item_id>', methods=['GET', 'POST'])
def inventory_item_edit(item_id):
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    
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
        
        cur.execute("""
            UPDATE inventory_items SET 
                name=%s, unit=%s, minimum_quantity=%s, reorder_level=%s,
                location=%s, supplier=%s, status=%s, responsible_person=%s, responsible_role=%s,
                updated_at=NOW()
            WHERE id=%s
        """, (name, unit, minimum_quantity, reorder_level, location, supplier, status,
              responsible_person, responsible_role, item_id))
        mysql.connection.commit()
        flash('Item updated successfully.', 'success')
        return redirect(url_for('inventory_items'))
    
    cur.execute("SELECT i.*, c.name as category_name FROM inventory_items i JOIN inventory_categories c ON i.category_id = c.id WHERE i.id=%s", (item_id,))
    item = cur.fetchone()
    cur.execute("SELECT * FROM inventory_categories ORDER BY name")
    categories = cur.fetchall()
    cur.close()
    return render_template('inventory/item_edit.html', item=item, categories=categories)

# Issue item (outgoing)
@app.route('/inventory/issue/<int:item_id>', methods=['POST'])
def inventory_issue_item(item_id):
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    
    quantity = int(request.form['quantity'])
    issued_to = request.form['issued_to']
    issued_to_role = request.form['issued_to_role']
    purpose = request.form['purpose']
    notes = request.form.get('notes', '')
    
    cur = mysql.connection.cursor(DictCursor)
    
    # Check if enough quantity available
    cur.execute("SELECT name, quantity, current_value, unit FROM inventory_items WHERE id=%s", (item_id,))
    item = cur.fetchone()
    
    if not item:
        flash('Item not found.', 'danger')
        return redirect(url_for('inventory_items'))
    
    if item['quantity'] < quantity:
        flash(f'Insufficient stock! Available: {item["quantity"]} {item["unit"]}', 'danger')
        return redirect(url_for('inventory_items'))
    
    # Update quantity
    new_quantity = item['quantity'] - quantity
    cur.execute("UPDATE inventory_items SET quantity=%s, updated_at=NOW() WHERE id=%s", (new_quantity, item_id))
    
    # Record transaction
    cur.execute("""
        INSERT INTO inventory_transactions 
        (item_id, transaction_type, quantity, transaction_date, issued_to, issued_to_role, purpose, notes, recorded_by)
        VALUES (%s, 'issued', %s, CURDATE(), %s, %s, %s, %s, %s)
    """, (item_id, quantity, issued_to, issued_to_role, purpose, notes, session.get('username')))
    
    mysql.connection.commit()
    
    # Check low stock after issue
    check_low_stock_alerts()
    
    flash(f'{quantity} {item["unit"]} of {item["name"]} issued to {issued_to}.', 'success')
    return redirect(url_for('inventory_items'))

# Receive/restock item (incoming)
@app.route('/inventory/receive/<int:item_id>', methods=['POST'])
def inventory_receive_item(item_id):
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    
    quantity = int(request.form['quantity'])
    unit_price = float(request.form.get('unit_price', 0))
    supplier = request.form.get('supplier', '')
    notes = request.form.get('notes', '')
    
    cur = mysql.connection.cursor(DictCursor)
    
    cur.execute("SELECT name, quantity, current_value, unit FROM inventory_items WHERE id=%s", (item_id,))
    item = cur.fetchone()
    
    if not item:
        flash('Item not found.', 'danger')
        return redirect(url_for('inventory_items'))
    
    # Update quantity and value
    new_quantity = item['quantity'] + quantity
    total_amount = quantity * unit_price
    new_value = item['current_value'] + total_amount
    
    cur.execute("UPDATE inventory_items SET quantity=%s, current_value=%s, updated_at=NOW() WHERE id=%s", 
                (new_quantity, new_value, item_id))
    
    # Record transaction
    cur.execute("""
        INSERT INTO inventory_transactions 
        (item_id, transaction_type, quantity, unit_price, total_amount, transaction_date, supplier, notes, recorded_by)
        VALUES (%s, 'received', %s, %s, %s, CURDATE(), %s, %s, %s)
    """, (item_id, quantity, unit_price, total_amount, supplier, notes, session.get('username')))
    
    mysql.connection.commit()
    
    # Clear low stock alert if any
    cur.execute("UPDATE inventory_alerts SET is_read=1 WHERE item_id=%s AND alert_type='low_stock'", (item_id,))
    mysql.connection.commit()
    
    flash(f'{quantity} {item["unit"]} of {item["name"]} received.', 'success')
    return redirect(url_for('inventory_items'))

# Update item status (working, spoilt, used_up, under_repair)
@app.route('/inventory/update_status/<int:item_id>', methods=['POST'])
def inventory_update_status(item_id):
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    
    status = request.form['status']
    condition_notes = request.form.get('condition_notes', '')
    quantity_affected = int(request.form.get('quantity_affected', 0))
    
    cur = mysql.connection.cursor(DictCursor)
    
    cur.execute("SELECT name, quantity FROM inventory_items WHERE id=%s", (item_id,))
    item = cur.fetchone()
    
    if not item:
        flash('Item not found.', 'danger')
        return redirect(url_for('inventory_items'))
    
    if status in ['spoilt', 'used_up'] and quantity_affected > 0:
        # Reduce quantity
        new_quantity = item['quantity'] - quantity_affected
        cur.execute("UPDATE inventory_items SET quantity=%s, status=%s, condition_notes=%s, updated_at=NOW() WHERE id=%s", 
                    (new_quantity, status, condition_notes, item_id))
        
        # Record transaction
        cur.execute("""
            INSERT INTO inventory_transactions 
            (item_id, transaction_type, quantity, notes, recorded_by)
            VALUES (%s, %s, %s, %s, %s)
        """, (item_id, status, quantity_affected, condition_notes, session.get('username')))
    else:
        cur.execute("UPDATE inventory_items SET status=%s, condition_notes=%s, updated_at=NOW() WHERE id=%s", 
                    (status, condition_notes, item_id))
    
    mysql.connection.commit()
    flash(f'Item status updated to {status}.', 'success')
    return redirect(url_for('inventory_items'))

# View inventory transactions
@app.route('/inventory/transactions')
def inventory_transactions():
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    
    item_id = request.args.get('item_id', '')
    
    cur = mysql.connection.cursor(DictCursor)
    if item_id:
        cur.execute("""
            SELECT t.*, i.name as item_name, i.item_code
            FROM inventory_transactions t
            JOIN inventory_items i ON t.item_id = i.id
            WHERE t.item_id = %s
            ORDER BY t.created_at DESC
        """, (item_id,))
    else:
        cur.execute("""
            SELECT t.*, i.name as item_name, i.item_code
            FROM inventory_transactions t
            JOIN inventory_items i ON t.item_id = i.id
            ORDER BY t.created_at DESC LIMIT 100
        """)
    transactions = cur.fetchall()
    
    cur.execute("SELECT id, name FROM inventory_items ORDER BY name")
    items = cur.fetchall()
    cur.close()
    
    return render_template('inventory/transactions.html', transactions=transactions, items=items, selected_item=item_id)

# View and acknowledge alerts
@app.route('/inventory/alerts')
def inventory_alerts():
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("""
        SELECT a.*, i.name as item_name, i.quantity, i.reorder_level, i.unit
        FROM inventory_alerts a
        JOIN inventory_items i ON a.item_id = i.id
        WHERE a.is_read = 0
        ORDER BY a.created_at DESC
    """)
    alerts = cur.fetchall()
    cur.close()
    
    return render_template('inventory/alerts.html', alerts=alerts)

# Acknowledge/read alert
@app.route('/inventory/alert/read/<int:alert_id>')
def inventory_alert_read(alert_id):
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        abort(403)
    
    cur = mysql.connection.cursor()
    cur.execute("UPDATE inventory_alerts SET is_read=1 WHERE id=%s", (alert_id,))
    mysql.connection.commit()
    cur.close()
    
    flash('Alert acknowledged.', 'success')
    return redirect(url_for('inventory_alerts'))

# Inventory Reports
@app.route('/inventory/reports')
def inventory_reports():
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    
    cur = mysql.connection.cursor(DictCursor)
    
    # Stock by category
    cur.execute("""
        SELECT c.name as category, COUNT(i.id) as item_count, SUM(i.quantity) as total_quantity, SUM(i.current_value) as total_value
        FROM inventory_categories c
        LEFT JOIN inventory_items i ON c.id = i.category_id
        GROUP BY c.id
        ORDER BY total_value DESC
    """)
    by_category = cur.fetchall()
    
    # Stock by status
    cur.execute("""
        SELECT status, COUNT(*) as count, SUM(quantity) as quantity
        FROM inventory_items
        GROUP BY status
    """)
    by_status = cur.fetchall()
    
    # Low stock items
    cur.execute("""
        SELECT i.*, c.name as category_name
        FROM inventory_items i
        JOIN inventory_categories c ON i.category_id = c.id
        WHERE i.quantity <= i.reorder_level AND i.status = 'working'
        ORDER BY i.quantity ASC
    """)
    low_stock_items = cur.fetchall()
    
    # Recent issues
    cur.execute("""
        SELECT t.*, i.name as item_name
        FROM inventory_transactions t
        JOIN inventory_items i ON t.item_id = i.id
        WHERE t.transaction_type = 'issued'
        ORDER BY t.created_at DESC LIMIT 20
    """)
    recent_issues = cur.fetchall()
    
    cur.close()
    return render_template('inventory/reports.html', 
                          by_category=by_category, 
                          by_status=by_status,
                          low_stock_items=low_stock_items,
                          recent_issues=recent_issues)

# Print inventory report
@app.route('/inventory/print_report')
def inventory_print_report():
    if not check_permission(['admin', 'bursar', 'stores_keeper']):
        abort(403)
    
    category = request.args.get('category', '')
    
    cur = mysql.connection.cursor(DictCursor)
    if category:
        cur.execute("""
            SELECT i.*, c.name as category_name
            FROM inventory_items i
            JOIN inventory_categories c ON i.category_id = c.id
            WHERE c.name = %s
            ORDER BY i.name
        """, (category,))
    else:
        cur.execute("""
            SELECT i.*, c.name as category_name
            FROM inventory_items i
            JOIN inventory_categories c ON i.category_id = c.id
            ORDER BY c.name, i.name
        """)
    items = cur.fetchall()
    cur.close()
    
    return render_template('inventory/print_report.html', items=items, category=category)

@app.route('/inventory/alert/count')
def inventory_alert_count():
    if not check_permission(['admin', 'bursar', 'dos', 'stores_keeper']):
        return jsonify({'count': 0})
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) FROM inventory_alerts WHERE is_read = 0")
    count = cur.fetchone()[0]
    cur.close()
    
    return jsonify({'count': count})

if __name__ == '__main__':
    app.run(debug=True)

# Mobile API endpoints
@app.route('/mobile/login', methods=['POST'])
def mobile_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    cur = mysql.connection.cursor(DictCursor)
    cur.execute("SELECT id, username, role, status FROM users WHERE username=%s AND password=%s", (username, password))
    user = cur.fetchone()
    cur.close()
    
    if user and user['status'] == 1:
        token = generate_secure_token()
        return jsonify({
            'success': True,
            'token': token,
            'role': user['role'],
            'username': user['username']
        })
    return jsonify({'success': False, 'message': 'Invalid credentials'})

@app.route('/mobile/dashboard', methods=['GET'])
def mobile_dashboard():
    # Get token from header
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    # Validate token (implement token validation)
    
    role = session.get('role')
    if role == 'admin':
        cur = mysql.connection.cursor(DictCursor)
        cur.execute("SELECT COUNT(*) as total_users FROM users")
        users = cur.fetchone()
        cur.execute("SELECT COUNT(*) as total_students FROM students")
        students = cur.fetchone()
        cur.close()
        return jsonify({
            'total_users': users['total_users'],
            'total_students': students['total_students']
        })
    # Add other roles...
    return jsonify({})