import os
from datetime import datetime, date, timedelta
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import func, extract
import io
import csv
import json
import secrets

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'serenia-bills-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', f"sqlite:///{os.path.join(basedir, 'instance', 'serenia.db')}"
).replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ----------------------- MODELS -----------------------

class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # super_admin, staff
    description = db.Column(db.String(255))
    users = db.relationship('User', backref='role', lazy=True)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120))
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_super_admin(self):
        return self.role and self.role.name == 'super_admin'


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255))
    products = db.relationship('Product', backref='category', lazy=True)


class Brand(db.Model):
    __tablename__ = 'brands'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    products = db.relationship('Product', backref='brand', lazy=True)


class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    sku = db.Column(db.String(50), unique=True)
    barcode = db.Column(db.String(50), unique=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'))
    cost_price = db.Column(db.Float, default=0)
    selling_price = db.Column(db.Float, default=0)
    tax_percent = db.Column(db.Float, default=0)
    stock_quantity = db.Column(db.Integer, default=0)
    low_stock_threshold = db.Column(db.Integer, default=5)
    description = db.Column(db.Text)
    image = db.Column(db.String(255))
    expiry_date = db.Column(db.Date, nullable=True)
    variant_name = db.Column(db.String(100), nullable=True)  # e.g. "Size: L, Color: Red"
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_low_stock(self):
        return self.stock_quantity <= self.low_stock_threshold

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'sku': self.sku,
            'barcode': self.barcode,
            'selling_price': self.selling_price,
            'tax_percent': self.tax_percent,
            'stock_quantity': self.stock_quantity,
            'image': self.image or '',
            'category': self.category.name if self.category else '',
        }


class Customer(db.Model):
    __tablename__ = 'customers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    outstanding_balance = db.Column(db.Float, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sales = db.relationship('Sale', backref='customer', lazy=True)


class Supplier(db.Model):
    __tablename__ = 'suppliers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    purchases = db.relationship('Purchase', backref='supplier', lazy=True)


class Inventory(db.Model):
    __tablename__ = 'inventory'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    product = db.relationship('Product', backref='inventory_record', uselist=False)


class InventoryHistory(db.Model):
    __tablename__ = 'inventory_history'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    change_type = db.Column(db.String(20))  # stock_in, stock_out, adjustment, sale, return
    quantity = db.Column(db.Integer)
    reason = db.Column(db.String(255))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship('Product')
    user = db.relationship('User')


class Sale(db.Model):
    __tablename__ = 'sales'
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    subtotal = db.Column(db.Float, default=0)
    discount_amount = db.Column(db.Float, default=0)
    tax_amount = db.Column(db.Float, default=0)
    grand_total = db.Column(db.Float, default=0)
    paid_amount = db.Column(db.Float, default=0)
    payment_method = db.Column(db.String(30), default='Cash')
    status = db.Column(db.String(20), default='completed')  # completed, draft, held, returned, refunded
    notes = db.Column(db.Text)
    table_number = db.Column(db.String(20), nullable=True)
    order_type = db.Column(db.String(20), default='retail')  # retail, dine_in, takeaway
    kitchen_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')
    items = db.relationship('SaleItem', backref='sale', lazy=True, cascade='all, delete-orphan')


class SaleItem(db.Model):
    __tablename__ = 'sale_items'
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product_name = db.Column(db.String(150))
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Float, default=0)
    discount = db.Column(db.Float, default=0)
    tax_percent = db.Column(db.Float, default=0)
    line_total = db.Column(db.Float, default=0)
    product = db.relationship('Product')


class Purchase(db.Model):
    __tablename__ = 'purchases'
    id = db.Column(db.Integer, primary_key=True)
    reference_no = db.Column(db.String(50), unique=True, nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    total_amount = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='received')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('PurchaseItem', backref='purchase', lazy=True, cascade='all, delete-orphan')


class PurchaseItem(db.Model):
    __tablename__ = 'purchase_items'
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    unit_cost = db.Column(db.Float, default=0)
    line_total = db.Column(db.Float, default=0)
    product = db.relationship('Product')


class Settings(db.Model):
    __tablename__ = 'settings'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), default='SereniaBills')
    logo = db.Column(db.String(255))
    gst_number = db.Column(db.String(50))
    address = db.Column(db.String(255))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    currency_symbol = db.Column(db.String(10), default='₹')
    invoice_prefix = db.Column(db.String(10), default='INV-')
    default_tax_rate = db.Column(db.Float, default=0)
    theme = db.Column(db.String(20), default='light')
    next_invoice_number = db.Column(db.Integer, default=1)


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(255))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')


class Return(db.Model):
    __tablename__ = 'returns'
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    reason = db.Column(db.String(255))
    amount = db.Column(db.Float, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sale = db.relationship('Sale')
    product = db.relationship('Product')


class Refund(db.Model):
    __tablename__ = 'refunds'
    id = db.Column(db.Integer, primary_key=True)
    return_id = db.Column(db.Integer, db.ForeignKey('returns.id'), nullable=False)
    amount = db.Column(db.Float, default=0)
    method = db.Column(db.String(30), default='Cash')
    status = db.Column(db.String(20), default='processed')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    return_record = db.relationship('Return')


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ----------------------- HELPERS -----------------------

def log_activity(action, details=''):
    try:
        log = ActivityLog(user_id=current_user.id if current_user.is_authenticated else None,
                           action=action, details=details)
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()


def get_settings():
    settings = Settings.query.first()
    if not settings:
        settings = Settings()
        db.session.add(settings)
        db.session.commit()
    return settings


def generate_invoice_number():
    settings = get_settings()
    number = settings.next_invoice_number
    settings.next_invoice_number += 1
    db.session.commit()
    return f"{settings.invoice_prefix}{number:06d}"


def super_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_super_admin():
            flash('Access denied. Super Admin privileges required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def inject_globals():
    return dict(settings=get_settings(), now=datetime.utcnow())


# ----------------------- AUTH ROUTES -----------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.active:
            login_user(user)
            log_activity('Login', f'User {user.username} logged in')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    log_activity('Logout', f'User {current_user.username} logged out')
    logout_user()
    return redirect(url_for('login'))


# ----------------------- DASHBOARD -----------------------

@app.route('/')
@login_required
def dashboard():
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    sales_today = db.session.query(func.coalesce(func.sum(Sale.grand_total), 0)).filter(
        func.date(Sale.created_at) == today, Sale.status == 'completed').scalar()
    sales_week = db.session.query(func.coalesce(func.sum(Sale.grand_total), 0)).filter(
        func.date(Sale.created_at) >= week_start, Sale.status == 'completed').scalar()
    sales_month = db.session.query(func.coalesce(func.sum(Sale.grand_total), 0)).filter(
        func.date(Sale.created_at) >= month_start, Sale.status == 'completed').scalar()

    total_products = Product.query.filter_by(active=True).count()
    total_customers = Customer.query.count()
    total_suppliers = Supplier.query.count()
    low_stock_products = Product.query.filter(Product.stock_quantity <= Product.low_stock_threshold,
                                                Product.active == True).all()

    recent_bills = Sale.query.order_by(Sale.created_at.desc()).limit(8).all()

    top_products = db.session.query(
        SaleItem.product_name, func.sum(SaleItem.quantity).label('total_qty')
    ).group_by(SaleItem.product_name).order_by(func.sum(SaleItem.quantity).desc()).limit(5).all()

    # sales analytics - last 7 days
    chart_labels = []
    chart_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        total = db.session.query(func.coalesce(func.sum(Sale.grand_total), 0)).filter(
            func.date(Sale.created_at) == d, Sale.status == 'completed').scalar()
        chart_labels.append(d.strftime('%a'))
        chart_data.append(round(total, 2))

    inventory_value = db.session.query(
        func.coalesce(func.sum(Product.stock_quantity * Product.cost_price), 0)).scalar()

    return render_template('dashboard.html',
                            sales_today=sales_today, sales_week=sales_week, sales_month=sales_month,
                            total_products=total_products, total_customers=total_customers,
                            total_suppliers=total_suppliers, low_stock_products=low_stock_products,
                            recent_bills=recent_bills, top_products=top_products,
                            chart_labels=chart_labels, chart_data=chart_data,
                            inventory_value=inventory_value)


# ----------------------- PRODUCT MANAGEMENT -----------------------

@app.route('/products')
@login_required
def products():
    search = request.args.get('search', '')
    category_id = request.args.get('category', '')
    query = Product.query
    if search:
        query = query.filter(db.or_(Product.name.ilike(f'%{search}%'),
                                     Product.sku.ilike(f'%{search}%'),
                                     Product.barcode.ilike(f'%{search}%')))
    if category_id:
        query = query.filter_by(category_id=category_id)
    products_list = query.order_by(Product.name).all()
    categories = Category.query.all()
    return render_template('products.html', products=products_list, categories=categories,
                            search=search, category_id=category_id)


@app.route('/products/add', methods=['GET', 'POST'])
@login_required
def add_product():
    categories = Category.query.all()
    brands = Brand.query.all()
    if request.method == 'POST':
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                image_filename = secure_filename(f"{secrets.token_hex(8)}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))

        expiry = request.form.get('expiry_date')
        expiry_date = datetime.strptime(expiry, '%Y-%m-%d').date() if expiry else None

        product = Product(
            name=request.form['name'],
            sku=request.form.get('sku') or None,
            barcode=request.form.get('barcode') or None,
            category_id=request.form.get('category_id') or None,
            brand_id=request.form.get('brand_id') or None,
            cost_price=float(request.form.get('cost_price') or 0),
            selling_price=float(request.form.get('selling_price') or 0),
            tax_percent=float(request.form.get('tax_percent') or 0),
            stock_quantity=int(request.form.get('stock_quantity') or 0),
            low_stock_threshold=int(request.form.get('low_stock_threshold') or 5),
            description=request.form.get('description'),
            image=image_filename,
            expiry_date=expiry_date,
            variant_name=request.form.get('variant_name') or None,
        )
        db.session.add(product)
        db.session.commit()

        inv = Inventory(product_id=product.id, quantity=product.stock_quantity)
        db.session.add(inv)
        history = InventoryHistory(product_id=product.id, change_type='stock_in',
                                    quantity=product.stock_quantity, reason='Initial stock',
                                    user_id=current_user.id)
        db.session.add(history)
        db.session.commit()
        log_activity('Add Product', f'Added product {product.name}')
        flash('Product added successfully.', 'success')
        return redirect(url_for('products'))
    return render_template('product_form.html', categories=categories, brands=brands, product=None)


@app.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    categories = Category.query.all()
    brands = Brand.query.all()
    if request.method == 'POST':
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                image_filename = secure_filename(f"{secrets.token_hex(8)}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
                product.image = image_filename

        expiry = request.form.get('expiry_date')
        product.expiry_date = datetime.strptime(expiry, '%Y-%m-%d').date() if expiry else None

        product.name = request.form['name']
        product.sku = request.form.get('sku') or None
        product.barcode = request.form.get('barcode') or None
        product.category_id = request.form.get('category_id') or None
        product.brand_id = request.form.get('brand_id') or None
        product.cost_price = float(request.form.get('cost_price') or 0)
        product.selling_price = float(request.form.get('selling_price') or 0)
        product.tax_percent = float(request.form.get('tax_percent') or 0)
        product.low_stock_threshold = int(request.form.get('low_stock_threshold') or 5)
        product.description = request.form.get('description')
        product.variant_name = request.form.get('variant_name') or None
        db.session.commit()
        log_activity('Edit Product', f'Edited product {product.name}')
        flash('Product updated successfully.', 'success')
        return redirect(url_for('products'))
    return render_template('product_form.html', categories=categories, brands=brands, product=product)


@app.route('/products/delete/<int:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    product.active = False
    db.session.commit()
    log_activity('Delete Product', f'Deactivated product {product.name}')
    flash('Product deleted (deactivated) successfully.', 'success')
    return redirect(url_for('products'))


@app.route('/products/export-csv')
@login_required
def export_products_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['name', 'sku', 'barcode', 'category', 'brand', 'cost_price', 'selling_price',
                      'tax_percent', 'stock_quantity', 'low_stock_threshold', 'description'])
    for p in Product.query.all():
        writer.writerow([p.name, p.sku, p.barcode, p.category.name if p.category else '',
                          p.brand.name if p.brand else '', p.cost_price, p.selling_price,
                          p.tax_percent, p.stock_quantity, p.low_stock_threshold, p.description])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv',
                      as_attachment=True, download_name='products_export.csv')


@app.route('/products/import-csv', methods=['POST'])
@login_required
def import_products_csv():
    file = request.files.get('csv_file')
    if not file:
        flash('No file selected.', 'danger')
        return redirect(url_for('products'))
    stream = io.StringIO(file.stream.read().decode('utf-8'))
    reader = csv.DictReader(stream)
    count = 0
    for row in reader:
        category = None
        if row.get('category'):
            category = Category.query.filter_by(name=row['category']).first()
            if not category:
                category = Category(name=row['category'])
                db.session.add(category)
                db.session.flush()
        brand = None
        if row.get('brand'):
            brand = Brand.query.filter_by(name=row['brand']).first()
            if not brand:
                brand = Brand(name=row['brand'])
                db.session.add(brand)
                db.session.flush()
        product = Product(
            name=row.get('name', 'Unnamed'),
            sku=row.get('sku') or None,
            barcode=row.get('barcode') or None,
            category_id=category.id if category else None,
            brand_id=brand.id if brand else None,
            cost_price=float(row.get('cost_price') or 0),
            selling_price=float(row.get('selling_price') or 0),
            tax_percent=float(row.get('tax_percent') or 0),
            stock_quantity=int(row.get('stock_quantity') or 0),
            low_stock_threshold=int(row.get('low_stock_threshold') or 5),
            description=row.get('description'),
        )
        db.session.add(product)
        db.session.flush()
        db.session.add(Inventory(product_id=product.id, quantity=product.stock_quantity))
        count += 1
    db.session.commit()
    log_activity('Import Products CSV', f'Imported {count} products')
    flash(f'{count} products imported successfully.', 'success')
    return redirect(url_for('products'))


# ----------------------- CATEGORIES & BRANDS -----------------------

@app.route('/categories', methods=['GET', 'POST'])
@login_required
def categories():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name and not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name, description=request.form.get('description')))
            db.session.commit()
            flash('Category added.', 'success')
    cats = Category.query.all()
    return render_template('categories.html', categories=cats)


@app.route('/categories/delete/<int:cat_id>', methods=['POST'])
@login_required
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    db.session.delete(cat)
    db.session.commit()
    flash('Category deleted.', 'success')
    return redirect(url_for('categories'))


@app.route('/brands', methods=['GET', 'POST'])
@login_required
def brands():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name and not Brand.query.filter_by(name=name).first():
            db.session.add(Brand(name=name))
            db.session.commit()
            flash('Brand added.', 'success')
    brand_list = Brand.query.all()
    return render_template('brands.html', brands=brand_list)


@app.route('/brands/delete/<int:brand_id>', methods=['POST'])
@login_required
def delete_brand(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    db.session.delete(brand)
    db.session.commit()
    flash('Brand deleted.', 'success')
    return redirect(url_for('brands'))


# ----------------------- INVENTORY MANAGEMENT -----------------------

@app.route('/inventory')
@login_required
def inventory():
    products_list = Product.query.filter_by(active=True).order_by(Product.name).all()
    history = InventoryHistory.query.order_by(InventoryHistory.created_at.desc()).limit(50).all()
    return render_template('inventory.html', products=products_list, history=history)


@app.route('/inventory/adjust', methods=['POST'])
@login_required
def adjust_inventory():
    product_id = int(request.form['product_id'])
    change_type = request.form['change_type']  # stock_in, stock_out, adjustment
    quantity = int(request.form['quantity'])
    reason = request.form.get('reason', '')

    product = Product.query.get_or_404(product_id)
    if change_type == 'stock_in':
        product.stock_quantity += quantity
    elif change_type == 'stock_out':
        product.stock_quantity = max(0, product.stock_quantity - quantity)
    elif change_type == 'adjustment':
        product.stock_quantity = quantity

    inv = Inventory.query.filter_by(product_id=product_id).first()
    if inv:
        inv.quantity = product.stock_quantity
    else:
        db.session.add(Inventory(product_id=product_id, quantity=product.stock_quantity))

    db.session.add(InventoryHistory(product_id=product_id, change_type=change_type,
                                     quantity=quantity, reason=reason, user_id=current_user.id))
    db.session.commit()
    log_activity('Inventory Adjustment', f'{change_type} {quantity} for {product.name}')
    flash('Inventory updated successfully.', 'success')
    return redirect(url_for('inventory'))


# ----------------------- CUSTOMER MANAGEMENT -----------------------

@app.route('/customers')
@login_required
def customers():
    search = request.args.get('search', '')
    query = Customer.query
    if search:
        query = query.filter(db.or_(Customer.name.ilike(f'%{search}%'),
                                     Customer.phone.ilike(f'%{search}%')))
    customer_list = query.order_by(Customer.name).all()
    return render_template('customers.html', customers=customer_list, search=search)


@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'POST':
        customer = Customer(
            name=request.form['name'],
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            address=request.form.get('address'),
            outstanding_balance=float(request.form.get('outstanding_balance') or 0),
            notes=request.form.get('notes'),
        )
        db.session.add(customer)
        db.session.commit()
        log_activity('Add Customer', f'Added customer {customer.name}')
        flash('Customer added successfully.', 'success')
        return redirect(url_for('customers'))
    return render_template('customer_form.html', customer=None)


@app.route('/customers/edit/<int:customer_id>', methods=['GET', 'POST'])
@login_required
def edit_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    if request.method == 'POST':
        customer.name = request.form['name']
        customer.phone = request.form.get('phone')
        customer.email = request.form.get('email')
        customer.address = request.form.get('address')
        customer.outstanding_balance = float(request.form.get('outstanding_balance') or 0)
        customer.notes = request.form.get('notes')
        db.session.commit()
        flash('Customer updated successfully.', 'success')
        return redirect(url_for('customers'))
    return render_template('customer_form.html', customer=customer)


@app.route('/customers/delete/<int:customer_id>', methods=['POST'])
@login_required
def delete_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    db.session.delete(customer)
    db.session.commit()
    flash('Customer deleted successfully.', 'success')
    return redirect(url_for('customers'))


@app.route('/customers/<int:customer_id>/history')
@login_required
def customer_history(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    sales_list = Sale.query.filter_by(customer_id=customer_id).order_by(Sale.created_at.desc()).all()
    return render_template('customer_history.html', customer=customer, sales=sales_list)


# ----------------------- SUPPLIER MANAGEMENT -----------------------

@app.route('/suppliers')
@login_required
def suppliers():
    search = request.args.get('search', '')
    query = Supplier.query
    if search:
        query = query.filter(Supplier.name.ilike(f'%{search}%'))
    supplier_list = query.order_by(Supplier.name).all()
    return render_template('suppliers.html', suppliers=supplier_list, search=search)


@app.route('/suppliers/add', methods=['GET', 'POST'])
@login_required
def add_supplier():
    if request.method == 'POST':
        supplier = Supplier(
            name=request.form['name'],
            contact_person=request.form.get('contact_person'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            address=request.form.get('address'),
            notes=request.form.get('notes'),
        )
        db.session.add(supplier)
        db.session.commit()
        flash('Supplier added successfully.', 'success')
        return redirect(url_for('suppliers'))
    return render_template('supplier_form.html', supplier=None)


@app.route('/suppliers/edit/<int:supplier_id>', methods=['GET', 'POST'])
@login_required
def edit_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    if request.method == 'POST':
        supplier.name = request.form['name']
        supplier.contact_person = request.form.get('contact_person')
        supplier.phone = request.form.get('phone')
        supplier.email = request.form.get('email')
        supplier.address = request.form.get('address')
        supplier.notes = request.form.get('notes')
        db.session.commit()
        flash('Supplier updated successfully.', 'success')
        return redirect(url_for('suppliers'))
    return render_template('supplier_form.html', supplier=supplier)


@app.route('/suppliers/delete/<int:supplier_id>', methods=['POST'])
@login_required
def delete_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    db.session.delete(supplier)
    db.session.commit()
    flash('Supplier deleted successfully.', 'success')
    return redirect(url_for('suppliers'))


@app.route('/suppliers/<int:supplier_id>/history')
@login_required
def supplier_history(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    purchases_list = Purchase.query.filter_by(supplier_id=supplier_id).order_by(Purchase.created_at.desc()).all()
    return render_template('supplier_history.html', supplier=supplier, purchases=purchases_list)


# ----------------------- PURCHASE ORDERS -----------------------

@app.route('/purchases')
@login_required
def purchases():
    purchase_list = Purchase.query.order_by(Purchase.created_at.desc()).all()
    return render_template('purchases.html', purchases=purchase_list)


@app.route('/purchases/add', methods=['GET', 'POST'])
@login_required
def add_purchase():
    suppliers_list = Supplier.query.all()
    products_list = Product.query.filter_by(active=True).all()
    if request.method == 'POST':
        data = json.loads(request.form['items_json'])
        ref_no = f"PO-{secrets.token_hex(4).upper()}"
        purchase = Purchase(reference_no=ref_no, supplier_id=request.form.get('supplier_id') or None,
                             user_id=current_user.id, notes=request.form.get('notes'))
        total = 0
        for item in data:
            product = Product.query.get(int(item['product_id']))
            qty = int(item['quantity'])
            cost = float(item['unit_cost'])
            line_total = qty * cost
            total += line_total
            purchase.items.append(PurchaseItem(product_id=product.id, quantity=qty,
                                                 unit_cost=cost, line_total=line_total))
            product.stock_quantity += qty
            product.cost_price = cost
            inv = Inventory.query.filter_by(product_id=product.id).first()
            if inv:
                inv.quantity = product.stock_quantity
            db.session.add(InventoryHistory(product_id=product.id, change_type='stock_in',
                                             quantity=qty, reason=f'Purchase {ref_no}',
                                             user_id=current_user.id))
        purchase.total_amount = total
        db.session.add(purchase)
        db.session.commit()
        log_activity('Add Purchase', f'Purchase order {ref_no} created')
        flash('Purchase order recorded successfully.', 'success')
        return redirect(url_for('purchases'))
    return render_template('purchase_form.html', suppliers=suppliers_list, products=products_list)


@app.route('/purchases/<int:purchase_id>')
@login_required
def view_purchase(purchase_id):
    purchase = Purchase.query.get_or_404(purchase_id)
    return render_template('purchase_view.html', purchase=purchase)


# ----------------------- POS - TEXT SALES PANEL -----------------------

@app.route('/pos/text')
@login_required
def pos_text():
    products_list = Product.query.filter_by(active=True).order_by(Product.name).all()
    customers_list = Customer.query.order_by(Customer.name).all()
    held_bills = Sale.query.filter_by(status='held').all()
    settings = get_settings()
    return render_template('pos_text.html', products=products_list, customers=customers_list,
                            held_bills=held_bills, settings=settings)


# ----------------------- POS - PHOTO SALES PANEL -----------------------

@app.route('/pos/photo')
@login_required
def pos_photo():
    categories_list = Category.query.all()
    products_list = Product.query.filter_by(active=True).order_by(Product.name).all()
    customers_list = Customer.query.order_by(Customer.name).all()
    settings = get_settings()
    return render_template('pos_photo.html', categories=categories_list, products=products_list,
                            customers=customers_list, settings=settings)


# ----------------------- POS API -----------------------

@app.route('/api/products/search')
@login_required
def api_search_products():
    q = request.args.get('q', '')
    products_list = Product.query.filter(
        Product.active == True,
        db.or_(Product.name.ilike(f'%{q}%'), Product.barcode == q, Product.sku.ilike(f'%{q}%'))
    ).limit(20).all()
    return jsonify([p.to_dict() for p in products_list])


@app.route('/api/products/barcode/<barcode>')
@login_required
def api_product_by_barcode(barcode):
    product = Product.query.filter_by(barcode=barcode, active=True).first()
    if product:
        return jsonify(product.to_dict())
    return jsonify(None), 404


# Live cart state for customer display (in-memory, keyed by session/cashier)
LIVE_CART_STATE = {}


@app.route('/api/cart/update', methods=['POST'])
@login_required
def api_cart_update():
    data = request.get_json()
    cashier_id = str(current_user.id)
    LIVE_CART_STATE[cashier_id] = data
    return jsonify({'status': 'ok'})


@app.route('/api/cart/state/<cashier_id>')
def api_cart_state(cashier_id):
    return jsonify(LIVE_CART_STATE.get(cashier_id, {
        'items': [], 'subtotal': 0, 'tax': 0, 'discount': 0, 'total': 0
    }))


@app.route('/display/<cashier_id>')
def customer_display(cashier_id):
    settings = get_settings()
    return render_template('customer_display.html', cashier_id=cashier_id, settings=settings)


# ----------------------- SALES / CHECKOUT -----------------------

@app.route('/api/sales/checkout', methods=['POST'])
@login_required
def checkout():
    data = request.get_json()
    items = data.get('items', [])
    if not items:
        return jsonify({'error': 'Cart is empty'}), 400

    status = data.get('status', 'completed')  # completed, draft, held
    invoice_number = data.get('resume_invoice') or generate_invoice_number()

    existing = Sale.query.filter_by(invoice_number=invoice_number).first()
    if existing and existing.status == 'held':
        sale = existing
        sale.items = []
    else:
        sale = Sale(invoice_number=invoice_number)

    sale.customer_id = data.get('customer_id') or None
    sale.user_id = current_user.id
    sale.payment_method = data.get('payment_method', 'Cash')
    sale.notes = data.get('notes', '')
    sale.order_type = data.get('order_type', 'retail')
    sale.table_number = data.get('table_number')
    sale.kitchen_notes = data.get('kitchen_notes')
    sale.discount_amount = float(data.get('discount_amount', 0))
    sale.status = status

    subtotal = 0
    tax_total = 0
    for item in items:
        product = Product.query.get(int(item['product_id']))
        qty = int(item['quantity'])
        price = float(item['unit_price'])
        item_discount = float(item.get('discount', 0))
        line_subtotal = (price * qty) - item_discount
        tax_amt = line_subtotal * (product.tax_percent / 100) if product.tax_percent else 0
        line_total = line_subtotal + tax_amt
        subtotal += line_subtotal
        tax_total += tax_amt
        sale.items.append(SaleItem(product_id=product.id, product_name=product.name,
                                    quantity=qty, unit_price=price, discount=item_discount,
                                    tax_percent=product.tax_percent, line_total=line_total))
        if status == 'completed':
            product.stock_quantity = max(0, product.stock_quantity - qty)
            inv = Inventory.query.filter_by(product_id=product.id).first()
            if inv:
                inv.quantity = product.stock_quantity
            db.session.add(InventoryHistory(product_id=product.id, change_type='sale',
                                             quantity=qty, reason=f'Sale {invoice_number}',
                                             user_id=current_user.id))

    sale.subtotal = subtotal
    sale.tax_amount = tax_total
    sale.grand_total = subtotal + tax_total - sale.discount_amount
    sale.paid_amount = float(data.get('paid_amount', sale.grand_total))

    if sale.customer_id and sale.paid_amount < sale.grand_total:
        customer = Customer.query.get(sale.customer_id)
        customer.outstanding_balance += (sale.grand_total - sale.paid_amount)

    if not existing or existing.status != 'held':
        db.session.add(sale)
    db.session.commit()

    # clear cart from live display once finalized
    if status == 'completed':
        LIVE_CART_STATE[str(current_user.id)] = {'items': [], 'subtotal': 0, 'tax': 0, 'discount': 0, 'total': 0}

    log_activity('Sale', f'Invoice {sale.invoice_number} - {status} - Total: {sale.grand_total}')
    return jsonify({'status': 'ok', 'invoice_number': sale.invoice_number, 'sale_id': sale.id})


# ----------------------- INVOICES -----------------------

@app.route('/invoices')
@login_required
def invoices():
    status_filter = request.args.get('status', '')
    query = Sale.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    sales_list = query.order_by(Sale.created_at.desc()).limit(200).all()
    return render_template('invoices.html', sales=sales_list, status_filter=status_filter)


@app.route('/invoices/<int:sale_id>')
@login_required
def view_invoice(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    return render_template('invoice_view.html', sale=sale)


@app.route('/invoices/<int:sale_id>/pdf')
@login_required
def invoice_pdf(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    settings = get_settings()
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except ImportError:
        flash('PDF generation library not available.', 'danger')
        return redirect(url_for('view_invoice', sale_id=sale_id))

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 30 * mm

    c.setFont('Helvetica-Bold', 16)
    c.drawString(20 * mm, y, settings.company_name)
    y -= 6 * mm
    c.setFont('Helvetica', 9)
    if settings.address:
        c.drawString(20 * mm, y, settings.address)
        y -= 5 * mm
    if settings.gst_number:
        c.drawString(20 * mm, y, f"GST No: {settings.gst_number}")
        y -= 5 * mm

    y -= 5 * mm
    c.setFont('Helvetica-Bold', 12)
    c.drawString(20 * mm, y, f"Invoice: {sale.invoice_number}")
    c.drawString(120 * mm, y, f"Date: {sale.created_at.strftime('%Y-%m-%d %H:%M')}")
    y -= 6 * mm
    c.setFont('Helvetica', 10)
    if sale.customer:
        c.drawString(20 * mm, y, f"Customer: {sale.customer.name}")
        y -= 6 * mm

    y -= 4 * mm
    c.setFont('Helvetica-Bold', 9)
    c.drawString(20 * mm, y, "Item")
    c.drawString(90 * mm, y, "Qty")
    c.drawString(110 * mm, y, "Price")
    c.drawString(140 * mm, y, "Tax%")
    c.drawString(165 * mm, y, "Total")
    y -= 4 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 5 * mm

    c.setFont('Helvetica', 9)
    for item in sale.items:
        c.drawString(20 * mm, y, item.product_name[:35])
        c.drawString(90 * mm, y, str(item.quantity))
        c.drawString(110 * mm, y, f"{settings.currency_symbol}{item.unit_price:.2f}")
        c.drawString(140 * mm, y, f"{item.tax_percent:.1f}")
        c.drawString(165 * mm, y, f"{settings.currency_symbol}{item.line_total:.2f}")
        y -= 5 * mm
        if y < 30 * mm:
            c.showPage()
            y = height - 30 * mm

    y -= 5 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm
    c.setFont('Helvetica', 10)
    c.drawString(130 * mm, y, f"Subtotal: {settings.currency_symbol}{sale.subtotal:.2f}")
    y -= 5 * mm
    c.drawString(130 * mm, y, f"Discount: {settings.currency_symbol}{sale.discount_amount:.2f}")
    y -= 5 * mm
    c.drawString(130 * mm, y, f"Tax: {settings.currency_symbol}{sale.tax_amount:.2f}")
    y -= 5 * mm
    c.setFont('Helvetica-Bold', 11)
    c.drawString(130 * mm, y, f"Grand Total: {settings.currency_symbol}{sale.grand_total:.2f}")
    y -= 10 * mm
    c.setFont('Helvetica-Oblique', 9)
    c.drawString(20 * mm, y, "Thank you for your business!")

    c.save()
    buffer.seek(0)
    return send_file(buffer, mimetype='application/pdf', as_attachment=True,
                      download_name=f"{sale.invoice_number}.pdf")


@app.route('/invoices/<int:sale_id>/return', methods=['GET', 'POST'])
@login_required
def return_invoice(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    if request.method == 'POST':
        item_id = int(request.form['item_id'])
        qty = int(request.form['quantity'])
        reason = request.form.get('reason', '')
        item = SaleItem.query.get_or_404(item_id)
        amount = (item.line_total / item.quantity) * qty if item.quantity else 0

        ret = Return(sale_id=sale.id, product_id=item.product_id, quantity=qty,
                      reason=reason, amount=amount, user_id=current_user.id)
        db.session.add(ret)

        # restock
        product = Product.query.get(item.product_id)
        if product:
            product.stock_quantity += qty
            inv = Inventory.query.filter_by(product_id=product.id).first()
            if inv:
                inv.quantity = product.stock_quantity
            db.session.add(InventoryHistory(product_id=product.id, change_type='return',
                                             quantity=qty, reason=f'Return for {sale.invoice_number}',
                                             user_id=current_user.id))
        db.session.commit()

        if request.form.get('process_refund'):
            refund = Refund(return_id=ret.id, amount=amount,
                             method=request.form.get('refund_method', 'Cash'),
                             user_id=current_user.id)
            db.session.add(refund)
            sale.status = 'refunded'
            db.session.commit()
            flash('Return and refund processed successfully.', 'success')
        else:
            sale.status = 'returned'
            db.session.commit()
            flash('Return processed successfully.', 'success')

        log_activity('Return', f'Return processed for {sale.invoice_number}')
        return redirect(url_for('view_invoice', sale_id=sale.id))

    return render_template('return_form.html', sale=sale)


# ----------------------- HELD / DRAFT BILLS -----------------------

@app.route('/api/sales/held')
@login_required
def api_held_bills():
    held = Sale.query.filter_by(status='held').order_by(Sale.created_at.desc()).all()
    result = []
    for sale in held:
        result.append({
            'id': sale.id,
            'invoice_number': sale.invoice_number,
            'grand_total': sale.grand_total,
            'created_at': sale.created_at.strftime('%Y-%m-%d %H:%M'),
            'items': [{
                'product_id': i.product_id, 'product_name': i.product_name,
                'quantity': i.quantity, 'unit_price': i.unit_price,
                'discount': i.discount, 'tax_percent': i.tax_percent
            } for i in sale.items],
            'customer_id': sale.customer_id,
            'discount_amount': sale.discount_amount
        })
    return jsonify(result)


@app.route('/api/sales/held/<int:sale_id>/delete', methods=['POST'])
@login_required
def delete_held_bill(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    if sale.status == 'held':
        db.session.delete(sale)
        db.session.commit()
    return jsonify({'status': 'ok'})


# ----------------------- REPORTS -----------------------

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')


@app.route('/reports/sales')
@login_required
def report_sales():
    period = request.args.get('period', 'daily')
    today = date.today()

    if period == 'daily':
        start = today
    elif period == 'weekly':
        start = today - timedelta(days=today.weekday())
    elif period == 'monthly':
        start = today.replace(day=1)
    elif period == 'yearly':
        start = today.replace(month=1, day=1)
    else:
        start = today

    sales_list = Sale.query.filter(func.date(Sale.created_at) >= start,
                                    Sale.status == 'completed').order_by(Sale.created_at.desc()).all()
    total = sum(s.grand_total for s in sales_list)
    tax_total = sum(s.tax_amount for s in sales_list)
    return render_template('report_sales.html', sales=sales_list, total=total,
                            tax_total=tax_total, period=period, start=start)


@app.route('/reports/products')
@login_required
def report_products():
    results = db.session.query(
        SaleItem.product_name,
        func.sum(SaleItem.quantity).label('total_qty'),
        func.sum(SaleItem.line_total).label('total_revenue')
    ).join(Sale).filter(Sale.status == 'completed').group_by(SaleItem.product_name).order_by(
        func.sum(SaleItem.line_total).desc()).all()
    return render_template('report_products.html', results=results)


@app.route('/reports/customers')
@login_required
def report_customers():
    results = db.session.query(
        Customer.name, Customer.phone,
        func.count(Sale.id).label('total_orders'),
        func.sum(Sale.grand_total).label('total_spent'),
        Customer.outstanding_balance
    ).join(Sale).filter(Sale.status == 'completed').group_by(Customer.id).order_by(
        func.sum(Sale.grand_total).desc()).all()
    return render_template('report_customers.html', results=results)


@app.route('/reports/inventory')
@login_required
def report_inventory():
    products_list = Product.query.filter_by(active=True).all()
    total_value = sum(p.stock_quantity * p.cost_price for p in products_list)
    total_selling_value = sum(p.stock_quantity * p.selling_price for p in products_list)
    return render_template('report_inventory.html', products=products_list,
                            total_value=total_value, total_selling_value=total_selling_value)


@app.route('/reports/profit')
@login_required
def report_profit():
    period = request.args.get('period', 'monthly')
    today = date.today()
    if period == 'daily':
        start = today
    elif period == 'weekly':
        start = today - timedelta(days=today.weekday())
    elif period == 'yearly':
        start = today.replace(month=1, day=1)
    else:
        start = today.replace(day=1)

    items = db.session.query(SaleItem).join(Sale).filter(
        func.date(Sale.created_at) >= start, Sale.status == 'completed').all()

    total_revenue = 0
    total_cost = 0
    for item in items:
        total_revenue += item.line_total
        cost = (item.product.cost_price if item.product else 0) * item.quantity
        total_cost += cost
    total_profit = total_revenue - total_cost
    return render_template('report_profit.html', total_revenue=total_revenue,
                            total_cost=total_cost, total_profit=total_profit, period=period, start=start)


@app.route('/reports/tax')
@login_required
def report_tax():
    period = request.args.get('period', 'monthly')
    today = date.today()
    if period == 'daily':
        start = today
    elif period == 'weekly':
        start = today - timedelta(days=today.weekday())
    elif period == 'yearly':
        start = today.replace(month=1, day=1)
    else:
        start = today.replace(day=1)

    sales_list = Sale.query.filter(func.date(Sale.created_at) >= start,
                                    Sale.status == 'completed').all()
    total_tax = sum(s.tax_amount for s in sales_list)
    total_sales = sum(s.grand_total for s in sales_list)
    return render_template('report_tax.html', sales=sales_list, total_tax=total_tax,
                            total_sales=total_sales, period=period, start=start)


@app.route('/reports/export-csv/<report_type>')
@login_required
def export_report_csv(report_type):
    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == 'sales':
        writer.writerow(['Invoice', 'Date', 'Customer', 'Subtotal', 'Discount', 'Tax', 'Grand Total', 'Status'])
        for s in Sale.query.order_by(Sale.created_at.desc()).all():
            writer.writerow([s.invoice_number, s.created_at.strftime('%Y-%m-%d %H:%M'),
                              s.customer.name if s.customer else 'Walk-in', s.subtotal,
                              s.discount_amount, s.tax_amount, s.grand_total, s.status])
    elif report_type == 'inventory':
        writer.writerow(['Product', 'SKU', 'Stock', 'Cost Price', 'Selling Price', 'Stock Value'])
        for p in Product.query.filter_by(active=True).all():
            writer.writerow([p.name, p.sku, p.stock_quantity, p.cost_price, p.selling_price,
                              p.stock_quantity * p.cost_price])
    else:
        writer.writerow(['No data'])

    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv',
                      as_attachment=True, download_name=f'{report_type}_report.csv')


# ----------------------- ADMIN PANEL - USERS -----------------------

@app.route('/admin/users')
@login_required
@super_admin_required
def admin_users():
    users_list = User.query.all()
    roles_list = Role.query.all()
    return render_template('admin_users.html', users=users_list, roles=roles_list)


@app.route('/admin/users/add', methods=['POST'])
@login_required
@super_admin_required
def add_user():
    username = request.form['username'].strip()
    if User.query.filter_by(username=username).first():
        flash('Username already exists.', 'danger')
        return redirect(url_for('admin_users'))
    user = User(username=username, email=request.form.get('email'),
                 full_name=request.form.get('full_name'),
                 role_id=request.form['role_id'])
    user.set_password(request.form['password'])
    db.session.add(user)
    db.session.commit()
    log_activity('Add User', f'Added user {username}')
    flash('User added successfully.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@super_admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id != current_user.id:
        user.active = not user.active
        db.session.commit()
        flash('User status updated.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id != current_user.id:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully.', 'success')
    else:
        flash('You cannot delete your own account.', 'danger')
    return redirect(url_for('admin_users'))


# ----------------------- ACTIVITY LOGS -----------------------

@app.route('/admin/activity-logs')
@login_required
@super_admin_required
def activity_logs():
    logs = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(200).all()
    return render_template('activity_logs.html', logs=logs)


# ----------------------- SETTINGS -----------------------

@app.route('/settings', methods=['GET', 'POST'])
@login_required
@super_admin_required
def settings_page():
    settings = get_settings()
    if request.method == 'POST':
        settings.company_name = request.form.get('company_name')
        settings.gst_number = request.form.get('gst_number')
        settings.address = request.form.get('address')
        settings.phone = request.form.get('phone')
        settings.email = request.form.get('email')
        settings.currency_symbol = request.form.get('currency_symbol')
        settings.invoice_prefix = request.form.get('invoice_prefix')
        settings.default_tax_rate = float(request.form.get('default_tax_rate') or 0)
        settings.theme = request.form.get('theme', 'light')

        if 'logo' in request.files:
            file = request.files['logo']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"logo_{secrets.token_hex(4)}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                settings.logo = filename

        db.session.commit()
        flash('Settings updated successfully.', 'success')
        return redirect(url_for('settings_page'))
    return render_template('settings.html', settings=settings)


# ----------------------- BACKUP / RESTORE -----------------------

@app.route('/admin/backup')
@login_required
@super_admin_required
def backup_database():
    db_path = os.path.join(basedir, 'instance', 'serenia.db')
    if os.path.exists(db_path):
        log_activity('Backup', 'Database backup downloaded')
        return send_file(db_path, as_attachment=True,
                          download_name=f"serenia_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    flash('Database file not found.', 'danger')
    return redirect(url_for('settings_page'))


@app.route('/admin/restore', methods=['POST'])
@login_required
@super_admin_required
def restore_database():
    file = request.files.get('backup_file')
    if not file or not file.filename.endswith('.db'):
        flash('Please upload a valid .db backup file.', 'danger')
        return redirect(url_for('settings_page'))
    db_path = os.path.join(basedir, 'instance', 'serenia.db')
    db.session.close()
    file.save(db_path)
    log_activity('Restore', 'Database restored from backup')
    flash('Database restored successfully. Please restart the application.', 'success')
    return redirect(url_for('settings_page'))


# ----------------------- BARCODE / QR -----------------------

@app.route('/products/<int:product_id>/barcode')
@login_required
def product_barcode(product_id):
    product = Product.query.get_or_404(product_id)
    try:
        import barcode
        from barcode.writer import ImageWriter
    except ImportError:
        abort(404)

    code_value = product.barcode or str(product.id).zfill(12)
    buffer = io.BytesIO()
    try:
        code128 = barcode.get('code128', code_value, writer=ImageWriter())
        code128.write(buffer)
    except Exception:
        abort(404)
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png')


@app.route('/products/<int:product_id>/qrcode')
@login_required
def product_qrcode(product_id):
    product = Product.query.get_or_404(product_id)
    try:
        import qrcode
    except ImportError:
        abort(404)

    data = f"SKU:{product.sku}|Name:{product.name}|Price:{product.selling_price}"
    img = qrcode.make(data)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png')


# ----------------------- INITIALIZATION -----------------------

def init_db():
    db.create_all()

    if not Role.query.first():
        super_admin = Role(name='super_admin', description='Full system access')
        staff = Role(name='staff', description='Limited POS access')
        db.session.add_all([super_admin, staff])
        db.session.commit()

    if not User.query.filter_by(username='admin').first():
        super_admin_role = Role.query.filter_by(name='super_admin').first()
        admin = User(username='admin', email='admin@serenia.com', full_name='Administrator',
                     role_id=super_admin_role.id)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    if not Settings.query.first():
        db.session.add(Settings(company_name='SereniaBills', currency_symbol='₹',
                                 invoice_prefix='INV-', next_invoice_number=1))
        db.session.commit()

    # Demo data
    if not Category.query.first():
        cats = ['Groceries', 'Electronics', 'Pharmacy', 'Hardware', 'Beverages']
        for c in cats:
            db.session.add(Category(name=c))
        db.session.commit()

    if not Brand.query.first():
        for b in ['Generic', 'Samsung', 'Nestle', 'Bosch', 'Cipla']:
            db.session.add(Brand(name=b))
        db.session.commit()

    if not Product.query.first():
        groceries = Category.query.filter_by(name='Groceries').first()
        electronics = Category.query.filter_by(name='Electronics').first()
        pharmacy = Category.query.filter_by(name='Pharmacy').first()
        beverages = Category.query.filter_by(name='Beverages').first()
        generic = Brand.query.filter_by(name='Generic').first()
        samsung = Brand.query.filter_by(name='Samsung').first()
        nestle = Brand.query.filter_by(name='Nestle').first()
        cipla = Brand.query.filter_by(name='Cipla').first()

        demo_products = [
            Product(name='Basmati Rice 5kg', sku='GR001', barcode='8901001000011',
                    category_id=groceries.id, brand_id=generic.id, cost_price=400, selling_price=550,
                    tax_percent=5, stock_quantity=50, low_stock_threshold=10,
                    description='Premium basmati rice'),
            Product(name='Sunflower Oil 1L', sku='GR002', barcode='8901001000028',
                    category_id=groceries.id, brand_id=generic.id, cost_price=120, selling_price=160,
                    tax_percent=5, stock_quantity=40, low_stock_threshold=10,
                    description='Refined sunflower cooking oil'),
            Product(name='Maggi Noodles', sku='GR003', barcode='8901001000035',
                    category_id=groceries.id, brand_id=nestle.id, cost_price=10, selling_price=14,
                    tax_percent=12, stock_quantity=200, low_stock_threshold=30,
                    description='2-minute instant noodles'),
            Product(name='Samsung Earbuds', sku='EL001', barcode='8901001000042',
                    category_id=electronics.id, brand_id=samsung.id, cost_price=1500, selling_price=2499,
                    tax_percent=18, stock_quantity=15, low_stock_threshold=5,
                    description='Wireless bluetooth earbuds'),
            Product(name='Samsung Power Bank 10000mAh', sku='EL002', barcode='8901001000059',
                    category_id=electronics.id, brand_id=samsung.id, cost_price=900, selling_price=1299,
                    tax_percent=18, stock_quantity=20, low_stock_threshold=5,
                    description='Fast charging power bank'),
            Product(name='Paracetamol 500mg (10 Tabs)', sku='PH001', barcode='8901001000066',
                    category_id=pharmacy.id, brand_id=cipla.id, cost_price=8, selling_price=15,
                    tax_percent=12, stock_quantity=100, low_stock_threshold=20,
                    description='Pain relief tablets',
                    expiry_date=date.today() + timedelta(days=365)),
            Product(name='Cough Syrup 100ml', sku='PH002', barcode='8901001000073',
                    category_id=pharmacy.id, brand_id=cipla.id, cost_price=45, selling_price=75,
                    tax_percent=12, stock_quantity=30, low_stock_threshold=10,
                    description='Herbal cough syrup',
                    expiry_date=date.today() + timedelta(days=180)),
            Product(name='Mineral Water 1L', sku='BV001', barcode='8901001000080',
                    category_id=beverages.id, brand_id=generic.id, cost_price=10, selling_price=20,
                    tax_percent=12, stock_quantity=4, low_stock_threshold=10,
                    description='Packaged drinking water'),
            Product(name='Cold Drink 500ml', sku='BV002', barcode='8901001000097',
                    category_id=beverages.id, brand_id=generic.id, cost_price=18, selling_price=35,
                    tax_percent=28, stock_quantity=60, low_stock_threshold=15,
                    description='Carbonated soft drink'),
            Product(name='Tea Powder 250g', sku='GR004', barcode='8901001000103',
                    category_id=groceries.id, brand_id=generic.id, cost_price=60, selling_price=95,
                    tax_percent=5, stock_quantity=35, low_stock_threshold=10,
                    description='Premium CTC tea'),
        ]
        db.session.add_all(demo_products)
        db.session.commit()

        for p in demo_products:
            db.session.add(Inventory(product_id=p.id, quantity=p.stock_quantity))
        db.session.commit()

    if not Customer.query.first():
        demo_customers = [
            Customer(name='Walk-in Customer', phone='', email='', address='', outstanding_balance=0),
            Customer(name='Rajesh Sharma', phone='9876543210', email='rajesh@example.com',
                     address='123 MG Road, Surat', outstanding_balance=0),
            Customer(name='Priya Patel', phone='9123456780', email='priya@example.com',
                     address='45 Ring Road, Surat', outstanding_balance=250),
        ]
        db.session.add_all(demo_customers)
        db.session.commit()

    if not Supplier.query.first():
        demo_suppliers = [
            Supplier(name='Global Distributors', contact_person='Amit Shah', phone='9988776655',
                     email='amit@globaldist.com', address='Industrial Area, Surat'),
            Supplier(name='Tech Wholesale Hub', contact_person='Neha Joshi', phone='9090909090',
                     email='neha@techhub.com', address='Electronic City, Surat'),
        ]
        db.session.add_all(demo_suppliers)
        db.session.commit()


# ----------------------- QUICK CUSTOMER ADD (AJAX) -----------------------

@app.route('/api/customers/quick-add', methods=['POST'])
@login_required
def api_quick_add_customer():
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    customer = Customer(
        name=name,
        phone=request.form.get('phone', '').strip(),
        email=request.form.get('email', '').strip(),
        address=request.form.get('address', '').strip(),
        outstanding_balance=0
    )
    db.session.add(customer)
    db.session.commit()
    log_activity('Quick Add Customer', f'Added {customer.name} via POS')
    return jsonify({'id': customer.id, 'name': customer.name, 'phone': customer.phone})


# ----------------------- DAILY SALES CHART API -----------------------

@app.route('/api/dashboard/chart')
@login_required
def api_dashboard_chart():
    days = int(request.args.get('days', 7))
    today = date.today()
    labels, data_sales, data_orders = [], [], []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        total = db.session.query(func.coalesce(func.sum(Sale.grand_total), 0)).filter(
            func.date(Sale.created_at) == d, Sale.status == 'completed').scalar()
        count = Sale.query.filter(
            func.date(Sale.created_at) == d, Sale.status == 'completed').count()
        labels.append(d.strftime('%d %b'))
        data_sales.append(round(float(total), 2))
        data_orders.append(count)
    return jsonify({'labels': labels, 'sales': data_sales, 'orders': data_orders})


# ----------------------- PRODUCT STATS API -----------------------

@app.route('/api/products/<int:product_id>/stats')
@login_required
def api_product_stats(product_id):
    product = Product.query.get_or_404(product_id)
    total_sold = db.session.query(func.coalesce(func.sum(SaleItem.quantity), 0)).filter_by(
        product_id=product_id).scalar()
    total_revenue = db.session.query(func.coalesce(func.sum(SaleItem.line_total), 0)).filter_by(
        product_id=product_id).scalar()
    last_sale = SaleItem.query.filter_by(product_id=product_id).join(Sale).order_by(
        Sale.created_at.desc()).first()
    return jsonify({
        'total_sold': int(total_sold),
        'total_revenue': round(float(total_revenue), 2),
        'last_sale': last_sale.sale.created_at.strftime('%d %b %Y') if last_sale else None,
        'stock': product.stock_quantity,
        'name': product.name
    })


# ----------------------- EXPENSE TRACKER -----------------------

class Expense(db.Model):
    __tablename__ = 'expenses'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    amount = db.Column(db.Float, default=0)
    category = db.Column(db.String(80))
    payment_method = db.Column(db.String(30), default='Cash')
    notes = db.Column(db.Text)
    expense_date = db.Column(db.Date, default=date.today)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')


@app.route('/expenses')
@login_required
def expenses():
    month_start = date.today().replace(day=1)
    expense_list = Expense.query.order_by(Expense.expense_date.desc()).limit(200).all()
    total_month = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
        Expense.expense_date >= month_start).scalar()
    total_all = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).scalar()
    categories = db.session.query(Expense.category, func.sum(Expense.amount)).group_by(
        Expense.category).all()
    return render_template('expenses.html', expenses=expense_list,
                            total_month=total_month, total_all=total_all,
                            categories=categories)


@app.route('/expenses/add', methods=['POST'])
@login_required
def add_expense():
    exp_date_str = request.form.get('expense_date')
    exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date() if exp_date_str else date.today()
    expense = Expense(
        title=request.form['title'],
        amount=float(request.form.get('amount') or 0),
        category=request.form.get('category', 'General'),
        payment_method=request.form.get('payment_method', 'Cash'),
        notes=request.form.get('notes'),
        expense_date=exp_date,
        user_id=current_user.id
    )
    db.session.add(expense)
    db.session.commit()
    log_activity('Add Expense', f'{expense.title} — {expense.amount}')
    flash('Expense recorded successfully.', 'success')
    return redirect(url_for('expenses'))


@app.route('/expenses/<int:expense_id>/delete', methods=['POST'])
@login_required
def delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    db.session.delete(expense)
    db.session.commit()
    flash('Expense deleted.', 'success')
    return redirect(url_for('expenses'))


# ----------------------- DAILY SUMMARY / CASH REGISTER CLOSE -----------------------

@app.route('/reports/daily-summary')
@login_required
def daily_summary():
    report_date_str = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    try:
        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
    except ValueError:
        report_date = date.today()

    sales_qs = Sale.query.filter(
        func.date(Sale.created_at) == report_date,
        Sale.status == 'completed'
    ).all()

    total_sales = sum(s.grand_total for s in sales_qs)
    total_tax = sum(s.tax_amount for s in sales_qs)
    total_discount = sum(s.discount_amount for s in sales_qs)
    total_cash = sum(s.grand_total for s in sales_qs if s.payment_method == 'Cash')
    total_card = sum(s.grand_total for s in sales_qs if s.payment_method in ('Card', 'UPI'))
    total_credit = sum(s.grand_total for s in sales_qs if s.payment_method == 'Credit')
    num_bills = len(sales_qs)

    expenses_qs = Expense.query.filter(Expense.expense_date == report_date).all()
    total_expenses = sum(e.amount for e in expenses_qs)

    net_cash = total_cash - total_expenses

    # Payment method breakdown
    payment_breakdown = {}
    for s in sales_qs:
        payment_breakdown[s.payment_method] = payment_breakdown.get(s.payment_method, 0) + s.grand_total

    # Top items sold today
    top_items = db.session.query(
        SaleItem.product_name,
        func.sum(SaleItem.quantity).label('qty'),
        func.sum(SaleItem.line_total).label('rev')
    ).join(Sale).filter(
        func.date(Sale.created_at) == report_date,
        Sale.status == 'completed'
    ).group_by(SaleItem.product_name).order_by(func.sum(SaleItem.quantity).desc()).limit(10).all()

    return render_template('daily_summary.html',
                            report_date=report_date,
                            sales=sales_qs,
                            total_sales=total_sales,
                            total_tax=total_tax,
                            total_discount=total_discount,
                            total_cash=total_cash,
                            total_card=total_card,
                            total_credit=total_credit,
                            num_bills=num_bills,
                            expenses=expenses_qs,
                            total_expenses=total_expenses,
                            net_cash=net_cash,
                            payment_breakdown=payment_breakdown,
                            top_items=top_items)


# ----------------------- PRODUCT LABEL PRINTING -----------------------

@app.route('/products/labels')
@login_required
def product_labels():
    product_ids = request.args.getlist('ids')
    if product_ids:
        products_list = Product.query.filter(Product.id.in_(product_ids)).all()
    else:
        products_list = Product.query.filter_by(active=True).all()
    return render_template('product_labels.html', products=products_list)


# ----------------------- STOCK ALERTS API -----------------------

@app.route('/api/stock-alerts')
@login_required
def api_stock_alerts():
    low = Product.query.filter(
        Product.stock_quantity <= Product.low_stock_threshold,
        Product.active == True
    ).all()
    out = Product.query.filter(Product.stock_quantity <= 0, Product.active == True).all()
    expiring_soon = Product.query.filter(
        Product.expiry_date != None,
        Product.expiry_date <= date.today() + timedelta(days=30),
        Product.expiry_date >= date.today(),
        Product.active == True
    ).all()
    expired = Product.query.filter(
        Product.expiry_date != None,
        Product.expiry_date < date.today(),
        Product.active == True
    ).all()
    return jsonify({
        'low_stock': [{'id': p.id, 'name': p.name, 'stock': p.stock_quantity, 'threshold': p.low_stock_threshold} for p in low],
        'out_of_stock': [{'id': p.id, 'name': p.name} for p in out],
        'expiring_soon': [{'id': p.id, 'name': p.name, 'expiry': p.expiry_date.strftime('%d %b %Y')} for p in expiring_soon],
        'expired': [{'id': p.id, 'name': p.name, 'expiry': p.expiry_date.strftime('%d %b %Y')} for p in expired]
    })


# ----------------------- CHANGE PASSWORD -----------------------

@app.route('/profile/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form.get('current_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')
        if not current_user.check_password(current_pw):
            flash('Current password is incorrect.', 'danger')
        elif len(new_pw) < 6:
            flash('New password must be at least 6 characters.', 'danger')
        elif new_pw != confirm_pw:
            flash('Passwords do not match.', 'danger')
        else:
            current_user.set_password(new_pw)
            db.session.commit()
            log_activity('Change Password', f'{current_user.username} changed password')
            flash('Password changed successfully.', 'success')
            return redirect(url_for('dashboard'))
    return render_template('change_password.html')


# ----------------------- SHORTCUT: INVOICE REPRINT -----------------------

@app.route('/invoices/<int:sale_id>/reprint')
@login_required
def reprint_invoice(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    log_activity('Reprint Invoice', f'Reprinted {sale.invoice_number}')
    return render_template('invoice_view.html', sale=sale)


with app.app_context():
    init_db()
    # ensure new tables exist
    db.create_all()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False') == 'True')
