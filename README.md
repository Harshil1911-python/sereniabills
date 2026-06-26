# SereniaBills 🧾

**Professional POS & Inventory Management System**

A complete, production-ready billing and inventory management software for retail stores, supermarkets, electronics shops, pharmacies, hardware stores, restaurants, and general businesses.

---

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the application
python app.py

# 3. Open browser
http://localhost:5000
```

**Default Login:**
- Username: `admin`
- Password: `admin123`

---

## 📋 Features

### 🏪 Dual POS Panels
- **Text POS** — Fast keyboard billing with barcode scanning, hold/resume bills, keyboard shortcuts (F2, F4, F6, F8)
- **Photo POS** — Touch-friendly product grid with category filters and mobile-responsive layout

### 📺 Customer Display Screen
- Open `/display/{cashier_id}` on a second monitor or TV
- Live real-time synchronization with POS screen
- Fullscreen mode, clock, product images, totals

### 📦 Modules
- **Dashboard** — Sales analytics, low stock alerts, recent bills, top products
- **Products** — Add/edit/delete, barcode, QR code, CSV import/export, expiry tracking
- **Inventory** — Stock in/out/adjustment, history, low stock alerts
- **Customers** — Full CRM with purchase history and outstanding balance
- **Suppliers** — Supplier management with purchase order history
- **Purchases** — Purchase order management with stock auto-update
- **Invoices** — Complete invoice management with PDF, print, hold, return/refund
- **Reports** — Sales, products, customers, inventory, profit, tax reports
- **Admin** — Role-based access, user management, activity logs
- **Settings** — Company info, logo, GST, invoice prefix, themes, backup/restore

### 🔐 Security
- Password hashing (Werkzeug)
- Session management (Flask-Login)
- Role-based access control (Super Admin / Staff)
- SQL injection protection (SQLAlchemy ORM)
- Input validation

### 🎨 UI
- Light and Dark mode
- Responsive Bootstrap 5 layout
- Professional sidebar navigation
- Mobile-friendly POS

---

## 📁 Project Structure

```
SereniaBills/
├── app.py                  # Main Flask application + all routes
├── requirements.txt        # Python dependencies
├── Procfile               # For Heroku/Render
├── render.yaml            # Render.com config
├── .gitignore
├── README.md
├── instance/
│   └── serenia.db         # SQLite database (auto-created)
├── static/
│   ├── css/
│   │   └── main.css       # Full custom CSS with themes
│   └── uploads/           # Product images & logos
└── templates/
    ├── base.html           # Base layout with sidebar
    ├── login.html
    ├── dashboard.html
    ├── pos_text.html       # Text POS
    ├── pos_photo.html      # Photo POS
    ├── customer_display.html
    ├── products.html
    ├── product_form.html
    ├── inventory.html
    ├── customers.html
    ├── customer_form.html
    ├── customer_history.html
    ├── suppliers.html
    ├── supplier_form.html
    ├── supplier_history.html
    ├── purchases.html
    ├── purchase_form.html
    ├── purchase_view.html
    ├── invoices.html
    ├── invoice_view.html
    ├── return_form.html
    ├── categories.html
    ├── brands.html
    ├── reports.html
    ├── report_sales.html
    ├── report_products.html
    ├── report_customers.html
    ├── report_inventory.html
    ├── report_profit.html
    ├── report_tax.html
    ├── settings.html
    ├── admin_users.html
    └── activity_logs.html
```

---

## 🌐 Deploy to Render.com

1. Push code to GitHub
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your GitHub repo
4. Render auto-detects `render.yaml` settings
5. Deploy!

---

## ⌨️ POS Keyboard Shortcuts

| Key | Action |
|-----|--------|
| F2  | Focus search bar |
| F4  | Checkout / Complete sale |
| F6  | Hold current bill |
| F8  | Clear cart |
| Esc | Close search dropdown |

---

## 🖥️ Customer Display

Open the customer display on a second screen:

```
http://your-server/display/{cashier_user_id}
```

Example: `http://localhost:5000/display/1`

The display auto-refreshes every 1.5 seconds showing:
- Live cart items with images
- Subtotal, tax, discount, grand total
- Real-time clock and date
- Fullscreen mode support

---

## 📊 Database Tables

| Table | Purpose |
|-------|---------|
| users | Staff accounts |
| roles | super_admin, staff |
| products | Product catalog |
| categories | Product categories |
| brands | Product brands |
| customers | Customer CRM |
| suppliers | Supplier directory |
| inventory | Current stock levels |
| inventory_history | All stock movements |
| sales | Invoice headers |
| sale_items | Invoice line items |
| purchases | Purchase orders |
| purchase_items | PO line items |
| settings | App configuration |
| activity_logs | Audit trail |
| returns | Return records |
| refunds | Refund records |

---

## 🏪 Supported Business Types

- Retail stores & supermarkets
- Electronics shops
- Pharmacies (with expiry date tracking)
- Hardware stores
- Restaurants (dine-in, takeaway, table numbers, kitchen notes)
- General businesses

---

## 📄 License

MIT License — Free to use and modify for commercial projects.

---

**Built with ❤️ — SereniaBills v1.0.0**
