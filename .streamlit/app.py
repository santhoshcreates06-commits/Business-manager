import hashlib
import hmac
import io
import os
import secrets as _secrets
import time
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape

import extra_streamlit_components as stx
import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st
from psycopg2 import errors as pg_errors
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# ----------------------------------------------------------------------------
# PAGE CONFIG + RCB THEME
# ----------------------------------------------------------------------------
st.set_page_config(page_title="RCB Business Manager", page_icon="🏏", layout="wide")

RED = "#E4002B"
DARK_RED = "#8B0000"
BLACK = "#0D0D0D"
PANEL = "#1A1A1A"
GOLD = "#C8A24A"

st.markdown(
    f"""
    <style>
    .stApp {{ background: {BLACK}; color: #F5F5F5; }}
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {DARK_RED} 0%, {BLACK} 70%);
        border-right: 2px solid {GOLD};
    }}
    h1, h2, h3 {{ color: {RED}; letter-spacing: 0.5px; }}
    h1 {{ border-bottom: 3px solid {GOLD}; padding-bottom: 6px; }}
    div[data-testid="stMetric"] {{
        background: {PANEL};
        border-left: 5px solid {RED};
        border-radius: 10px;
        padding: 14px 18px;
        box-shadow: 0 2px 8px rgba(228,0,43,0.25);
    }}
    div[data-testid="stMetricValue"] {{ color: {GOLD}; }}
    .stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {{
        background: {RED}; color: white; border: 1px solid {GOLD};
        border-radius: 8px; font-weight: 600;
    }}
    .stButton > button:hover, .stFormSubmitButton > button:hover,
    .stDownloadButton > button:hover {{
        background: {DARK_RED}; color: {GOLD}; border-color: {RED};
    }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
    .stTabs [data-baseweb="tab"] {{ background: {PANEL}; border-radius: 8px 8px 0 0; }}
    .stTabs [aria-selected="true"] {{ background: {RED}; color: white; }}
    </style>
    """,
    unsafe_allow_html=True,
)


def style_fig(fig):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#F5F5F5",
        colorway=[RED, GOLD, "#FFFFFF", DARK_RED, "#888888"],
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
    "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands",
    "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
    "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
GST_RATES = [0, 5, 12, 18, 28]


# ----------------------------------------------------------------------------
# PASSWORD HASHING
# ----------------------------------------------------------------------------
def hash_pw(password, salt=None):
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 200_000
    ).hex()
    return f"{salt}${digest}"


def verify_pw(password, stored):
    try:
        salt, digest = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_pw(password, salt).split("$")[1], digest)


# ----------------------------------------------------------------------------
# DATABASE (Neon PostgreSQL, connection string comes from Streamlit secrets)
# ----------------------------------------------------------------------------
def get_conn():
    return psycopg2.connect(st.secrets["DATABASE_URL"])


def _pg(sql):
    return sql.replace("?", "%s")


def run(sql, params=()):
    """Run INSERT/UPDATE/DELETE. For INSERT returns the new row id."""
    sql = _pg(sql)
    is_insert = sql.lstrip().upper().startswith("INSERT")
    if is_insert:
        sql = sql.rstrip().rstrip(";") + " RETURNING id"
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()[0] if is_insert else None
    finally:
        conn.close()


def query(sql, params=()):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_pg(sql), params)
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)
    finally:
        conn.close()


@st.cache_resource
def init_db():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS customers (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        phone TEXT,
                        email TEXT,
                        address TEXT
                    );
                    CREATE TABLE IF NOT EXISTS products (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        price DOUBLE PRECISION NOT NULL,
                        stock INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS orders (
                        id SERIAL PRIMARY KEY,
                        customer_id INTEGER NOT NULL REFERENCES customers(id),
                        order_date TEXT NOT NULL,
                        total DOUBLE PRECISION NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS order_items (
                        id SERIAL PRIMARY KEY,
                        order_id INTEGER NOT NULL REFERENCES orders(id),
                        product_id INTEGER NOT NULL REFERENCES products(id),
                        qty INTEGER NOT NULL,
                        price DOUBLE PRECISION NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS payments (
                        id SERIAL PRIMARY KEY,
                        order_id INTEGER NOT NULL REFERENCES orders(id),
                        amount DOUBLE PRECISION NOT NULL,
                        method TEXT,
                        paid_on TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'staff'
                    );
                    CREATE TABLE IF NOT EXISTS settings (
                        id SERIAL PRIMARY KEY,
                        key TEXT NOT NULL UNIQUE,
                        value TEXT
                    );
                    CREATE TABLE IF NOT EXISTS sessions (
                        id SERIAL PRIMARY KEY,
                        token_hash TEXT NOT NULL UNIQUE,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        expires_at TIMESTAMPTZ NOT NULL
                    );
                    ALTER TABLE customers ADD COLUMN IF NOT EXISTS gstin TEXT;
                    ALTER TABLE customers ADD COLUMN IF NOT EXISTS state TEXT;
                    ALTER TABLE products ADD COLUMN IF NOT EXISTS gst_rate DOUBLE PRECISION NOT NULL DEFAULT 18;
                    ALTER TABLE order_items ADD COLUMN IF NOT EXISTS gst_rate DOUBLE PRECISION NOT NULL DEFAULT 0;
                    """
                )
    finally:
        conn.close()
    return True


init_db()


def ensure_admin():
    """Create the first admin from Streamlit secrets when there are no users."""
    n = int(query("SELECT COUNT(*) AS n FROM users")["n"][0])
    if n > 0:
        return n
    admin_pass = st.secrets.get("ADMIN_PASSWORD")
    if admin_pass:
        admin_user = st.secrets.get("ADMIN_USERNAME", "admin")
        run(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            (admin_user, hash_pw(admin_pass), "admin"),
        )
        return 1
    return 0


def get_settings():
    df = query("SELECT key, value FROM settings")
    return {r["key"]: (r["value"] or "") for _, r in df.iterrows()}


def clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v)


# ----------------------------------------------------------------------------
# LOGIN (stays logged in for 30 days using a browser cookie)
# ----------------------------------------------------------------------------
SESSION_COOKIE = "rcb_session"
SESSION_DAYS = 30


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id):
    run("DELETE FROM sessions WHERE expires_at < NOW()")
    token = _secrets.token_urlsafe(32)
    run(
        "INSERT INTO sessions (token_hash, user_id, expires_at) "
        f"VALUES (?, ?, NOW() + INTERVAL '{SESSION_DAYS} days')",
        (_hash_token(token), int(user_id)),
    )
    return token


def user_from_token(token):
    df = query(
        "SELECT u.id, u.username, u.role FROM sessions s "
        "JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > NOW()",
        (_hash_token(token),),
    )
    if df.empty:
        return None
    return {"id": int(df.loc[0, "id"]), "username": df.loc[0, "username"],
            "role": df.loc[0, "role"]}


cookie_manager = stx.CookieManager(key="rcb_cookie_manager")

if "user" not in st.session_state:
    saved_token = cookie_manager.get(SESSION_COOKIE)
    if saved_token:
        saved_user = user_from_token(saved_token)
        if saved_user is not None:
            st.session_state.user = saved_user
            st.session_state.token_hash = _hash_token(saved_token)
            st.rerun()

    n_users = ensure_admin()
    st.title("🏏 RCB Business Manager")
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        if n_users == 0:
            st.error(
                "Admin user inka create avvaledu. Streamlit Secrets lo ADMIN_USERNAME "
                "and ADMIN_PASSWORD add cheyyandi."
            )
        else:
            st.subheader("🔐 Login")
            with st.form("login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Login")
            if submitted:
                df = query(
                    "SELECT id, username, password_hash, role FROM users "
                    "WHERE LOWER(username) = LOWER(?)",
                    (u.strip(),),
                )
                if not df.empty and verify_pw(p, df.loc[0, "password_hash"]):
                    token = create_session(df.loc[0, "id"])
                    cookie_manager.set(
                        SESSION_COOKIE, token,
                        expires_at=datetime.now() + timedelta(days=SESSION_DAYS),
                        key="set_session_cookie",
                    )
                    st.session_state.user = {
                        "id": int(df.loc[0, "id"]),
                        "username": df.loc[0, "username"],
                        "role": df.loc[0, "role"],
                    }
                    st.session_state.token_hash = _hash_token(token)
                    st.success("Login successful...")
                    time.sleep(1)
                    st.rerun()
                else:
                    time.sleep(1)
                    st.error("Wrong username or password.")
    st.stop()

user = st.session_state.user
is_admin = user["role"] == "admin"

# ----------------------------------------------------------------------------
# ORDER HELPERS
# ----------------------------------------------------------------------------
ORDERS_SQL = """
SELECT o.id AS order_id, c.name AS customer, o.order_date, o.total,
       COALESCE(SUM(p.amount), 0) AS paid,
       o.total - COALESCE(SUM(p.amount), 0) AS balance
FROM orders o
JOIN customers c ON c.id = o.customer_id
LEFT JOIN payments p ON p.order_id = o.id
GROUP BY o.id, c.name
ORDER BY o.id DESC
"""


def add_status(df):
    def status(row):
        if row["balance"] <= 0:
            return "Paid"
        if row["paid"] > 0:
            return "Partial"
        return "Unpaid"

    if not df.empty:
        df["status"] = df.apply(status, axis=1)
    return df


# ----------------------------------------------------------------------------
# GST INVOICE (PDF)
# ----------------------------------------------------------------------------
def build_invoice(order_id):
    cfg = get_settings()
    o = query(
        """SELECT o.id, o.order_date, c.name, c.phone, c.address, c.gstin, c.state
           FROM orders o JOIN customers c ON c.id = o.customer_id
           WHERE o.id = ?""",
        (int(order_id),),
    ).iloc[0]
    items = query(
        """SELECT p.name, i.qty, i.price, i.gst_rate
           FROM order_items i JOIN products p ON p.id = i.product_id
           WHERE i.order_id = ? ORDER BY i.id""",
        (int(order_id),),
    )
    paid = float(
        query("SELECT COALESCE(SUM(amount), 0) AS paid FROM payments WHERE order_id = ?",
              (int(order_id),))["paid"][0]
    )

    seller_state = cfg.get("state", "")
    cust_state = clean(o["state"])
    intra = (not cust_state) or cust_state.strip().lower() == seller_state.strip().lower()

    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, leading=12)
    right = ParagraphStyle("right", parent=small, alignment=2)
    title = ParagraphStyle("title", parent=styles["Title"], textColor=colors.HexColor(RED),
                           fontSize=20, spaceAfter=2)
    heading = ParagraphStyle("heading", parent=styles["Heading3"], fontSize=12,
                             textColor=colors.HexColor(DARK_RED))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm,
                            title=f"Invoice {order_id}")
    story = []

    biz = cfg.get("business_name") or "Your Business Name"
    story.append(Paragraph(escape(biz), title))
    seller_lines = []
    if cfg.get("address"):
        seller_lines.append(escape(cfg["address"]).replace("\n", "<br/>"))
    if cfg.get("phone"):
        seller_lines.append("Phone: " + escape(cfg["phone"]))
    if cfg.get("gstin"):
        seller_lines.append("GSTIN: " + escape(cfg["gstin"]))
    if seller_state:
        seller_lines.append("State: " + escape(seller_state))
    story.append(Paragraph("<br/>".join(seller_lines), small))
    story.append(Spacer(1, 6))
    story.append(Paragraph("TAX INVOICE", heading))

    meta = Table(
        [[Paragraph(f"<b>Invoice No:</b> INV-{int(order_id):05d}", small),
          Paragraph(f"<b>Date:</b> {escape(str(o['order_date']))}", right)]],
        colWidths=[90 * mm, 90 * mm],
    )
    story.append(meta)
    story.append(Spacer(1, 4))

    bill = [f"<b>Bill To:</b> {escape(clean(o['name']))}"]
    if clean(o["address"]):
        bill.append(escape(clean(o["address"])).replace("\n", "<br/>"))
    if clean(o["phone"]):
        bill.append("Phone: " + escape(clean(o["phone"])))
    if clean(o["gstin"]):
        bill.append("GSTIN: " + escape(clean(o["gstin"])))
    if cust_state:
        bill.append("State: " + escape(cust_state))
    story.append(Paragraph("<br/>".join(bill), small))
    story.append(Spacer(1, 8))

    rows = [["#", "Item", "Qty", "Rate", "Taxable", "GST %", "GST Amt", "Amount"]]
    taxable_total = 0.0
    gst_total = 0.0
    for idx, it in enumerate(items.itertuples(index=False), start=1):
        taxable = it.qty * it.price
        gst = taxable * it.gst_rate / 100
        taxable_total += taxable
        gst_total += gst
        rows.append([
            str(idx), Paragraph(escape(it.name), small), str(it.qty),
            f"{it.price:,.2f}", f"{taxable:,.2f}", f"{it.gst_rate:g}%",
            f"{gst:,.2f}", f"{taxable + gst:,.2f}",
        ])
    table = Table(rows, colWidths=[8 * mm, 52 * mm, 12 * mm, 22 * mm, 24 * mm,
                                   14 * mm, 22 * mm, 26 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(RED)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F6F6")]),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))

    grand = taxable_total + gst_total
    summary = [["Taxable Value", f"Rs. {taxable_total:,.2f}"]]
    if intra:
        summary.append(["CGST", f"Rs. {gst_total / 2:,.2f}"])
        summary.append(["SGST", f"Rs. {gst_total / 2:,.2f}"])
    else:
        summary.append(["IGST", f"Rs. {gst_total:,.2f}"])
    summary += [
        ["Grand Total", f"Rs. {grand:,.2f}"],
        ["Paid", f"Rs. {paid:,.2f}"],
        ["Balance Due", f"Rs. {max(grand - paid, 0):,.2f}"],
    ]
    st_table = Table(summary, colWidths=[40 * mm, 40 * mm], hAlign="RIGHT")
    st_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -3), (-1, -3), "Helvetica-Bold"),
        ("LINEABOVE", (0, -3), (-1, -3), 0.8, colors.HexColor(RED)),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor(DARK_RED)),
    ]))
    story.append(st_table)
    story.append(Spacer(1, 18))
    footer = cfg.get("footer") or "Thank you for your business!"
    story.append(Paragraph(escape(footer), small))
    story.append(Paragraph("This is a computer generated invoice.", small))

    doc.build(story)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# SIDEBAR NAVIGATION
# ----------------------------------------------------------------------------
st.sidebar.markdown("## 🏏 RCB Business Manager")
st.sidebar.caption("Play Bold. Manage Better.")
st.sidebar.write(f"👤 **{user['username']}** ({user['role']})")

pages = [
    "📊 Dashboard",
    "👥 Customers",
    "📦 Products",
    "🛒 New Order",
    "💳 Orders & Payments",
    "📈 Reports",
    "👤 My Account",
]
if is_admin:
    pages += ["🔑 Users", "⚙️ Business Settings"]
page = st.sidebar.radio("Navigate", pages)

if st.sidebar.button("🚪 Logout"):
    th = st.session_state.get("token_hash")
    if th:
        run("DELETE FROM sessions WHERE token_hash=?", (th,))
    cookie_manager.delete(SESSION_COOKIE, key="del_session_cookie")
    time.sleep(1)
    for k in ("user", "cart", "token_hash"):
        st.session_state.pop(k, None)
    st.rerun()

# ----------------------------------------------------------------------------
# DASHBOARD
# ----------------------------------------------------------------------------
if page == "📊 Dashboard":
    st.title("📊 Dashboard")

    orders = add_status(query(ORDERS_SQL))
    n_cust = query("SELECT COUNT(*) AS n FROM customers")["n"][0]
    n_prod = query("SELECT COUNT(*) AS n FROM products")["n"][0]
    revenue = orders["paid"].sum() if not orders.empty else 0
    due = orders["balance"].sum() if not orders.empty else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Customers", int(n_cust))
    c2.metric("Products", int(n_prod))
    c3.metric("Orders", len(orders))
    c4.metric("Collected", f"₹{revenue:,.0f}")
    c5.metric("Outstanding", f"₹{due:,.0f}")

    if orders.empty:
        st.info("No orders yet. Add customers and products, then create your first order.")
    else:
        left, right = st.columns(2)
        daily = orders.groupby("order_date", as_index=False)["total"].sum()
        left.plotly_chart(
            style_fig(px.line(daily, x="order_date", y="total", markers=True,
                              title="Sales by Day")),
            use_container_width=True,
        )
        status_df = orders["status"].value_counts().reset_index()
        status_df.columns = ["status", "count"]
        right.plotly_chart(
            style_fig(px.pie(status_df, names="status", values="count", hole=0.5,
                             title="Payment Status")),
            use_container_width=True,
        )

        low = query("SELECT name, stock FROM products WHERE stock <= 5 ORDER BY stock")
        if not low.empty:
            st.subheader("⚠️ Low Stock")
            st.dataframe(low, use_container_width=True, hide_index=True)

# ----------------------------------------------------------------------------
# CUSTOMERS
# ----------------------------------------------------------------------------
elif page == "👥 Customers":
    st.title("👥 Customers")
    tab_list, tab_add = st.tabs(["All Customers", "Add Customer"])

    with tab_add:
        with st.form("add_customer", clear_on_submit=True):
            name = st.text_input("Name *")
            phone = st.text_input("Phone")
            email = st.text_input("Email")
            address = st.text_area("Address")
            gstin = st.text_input("GSTIN (optional)")
            state = st.selectbox("State", [""] + INDIAN_STATES)
            if st.form_submit_button("Save Customer"):
                if name.strip():
                    run(
                        "INSERT INTO customers (name, phone, email, address, gstin, state) "
                        "VALUES (?,?,?,?,?,?)",
                        (name.strip(), phone, email, address, gstin.strip().upper(), state),
                    )
                    st.success(f"Customer '{name}' added.")
                else:
                    st.error("Name is required.")

    with tab_list:
        search = st.text_input("🔍 Search by name or phone")
        df = query("SELECT * FROM customers ORDER BY name")
        if search:
            mask = df["name"].str.contains(search, case=False, na=False) | \
                   df["phone"].fillna("").str.contains(search, case=False)
            df = df[mask]
        st.dataframe(df, use_container_width=True, hide_index=True)

        if not df.empty:
            with st.expander("Delete a customer"):
                choice = st.selectbox(
                    "Customer", df["id"],
                    format_func=lambda i: df.loc[df["id"] == i, "name"].iloc[0],
                )
                if st.button("Delete"):
                    has_orders = query(
                        "SELECT COUNT(*) AS n FROM orders WHERE customer_id=?", (int(choice),)
                    )["n"][0]
                    if has_orders:
                        st.error("Cannot delete: this customer has orders.")
                    else:
                        run("DELETE FROM customers WHERE id=?", (int(choice),))
                        st.success("Deleted.")
                        st.rerun()

# ----------------------------------------------------------------------------
# PRODUCTS
# ----------------------------------------------------------------------------
elif page == "📦 Products":
    st.title("📦 Products")
    tab_list, tab_add = st.tabs(["Inventory", "Add Product"])

    with tab_add:
        with st.form("add_product", clear_on_submit=True):
            name = st.text_input("Product name *")
            price = st.number_input("Price before GST (₹)", min_value=0.0, step=1.0)
            gst_rate = st.selectbox("GST %", GST_RATES, index=GST_RATES.index(18))
            stock = st.number_input("Opening stock", min_value=0, step=1)
            if st.form_submit_button("Save Product"):
                if name.strip():
                    run(
                        "INSERT INTO products (name, price, stock, gst_rate) VALUES (?,?,?,?)",
                        (name.strip(), float(price), int(stock), float(gst_rate)),
                    )
                    st.success(f"Product '{name}' added.")
                else:
                    st.error("Name is required.")

    with tab_list:
        df = query("SELECT * FROM products ORDER BY name")
        st.dataframe(df, use_container_width=True, hide_index=True)

        if not df.empty:
            with st.expander("Update price / stock / GST"):
                pid = st.selectbox(
                    "Product", df["id"],
                    format_func=lambda i: df.loc[df["id"] == i, "name"].iloc[0],
                )
                row = df[df["id"] == pid].iloc[0]
                new_price = st.number_input("Price before GST (₹)",
                                            value=float(row["price"]), min_value=0.0)
                cur_gst = int(row["gst_rate"]) if int(row["gst_rate"]) in GST_RATES else 18
                new_gst = st.selectbox("GST %", GST_RATES, index=GST_RATES.index(cur_gst))
                new_stock = st.number_input("Stock", value=int(row["stock"]), min_value=0)
                if st.button("Update"):
                    run("UPDATE products SET price=?, stock=?, gst_rate=? WHERE id=?",
                        (float(new_price), int(new_stock), float(new_gst), int(pid)))
                    st.success("Updated.")
                    st.rerun()

# ----------------------------------------------------------------------------
# NEW ORDER
# ----------------------------------------------------------------------------
elif page == "🛒 New Order":
    st.title("🛒 New Order")

    customers = query("SELECT id, name FROM customers ORDER BY name")
    products = query("SELECT * FROM products WHERE stock > 0 ORDER BY name")

    if customers.empty or products.empty:
        st.warning("Add at least one customer and one in-stock product first.")
        st.stop()

    if "cart" not in st.session_state:
        st.session_state.cart = []

    cust_id = st.selectbox(
        "Customer", customers["id"],
        format_func=lambda i: customers.loc[customers["id"] == i, "name"].iloc[0],
    )

    col1, col2, col3 = st.columns([3, 1, 1])
    prod_id = col1.selectbox(
        "Product", products["id"],
        format_func=lambda i: "{} (₹{:,.0f} + {:g}% GST, stock {})".format(
            products.loc[products["id"] == i, "name"].iloc[0],
            products.loc[products["id"] == i, "price"].iloc[0],
            products.loc[products["id"] == i, "gst_rate"].iloc[0],
            products.loc[products["id"] == i, "stock"].iloc[0],
        ),
    )
    qty = col2.number_input("Qty", min_value=1, value=1, step=1)
    col3.write("")
    col3.write("")
    if col3.button("➕ Add"):
        p = products[products["id"] == prod_id].iloc[0]
        already = sum(i["qty"] for i in st.session_state.cart if i["product_id"] == int(prod_id))
        if already + qty > p["stock"]:
            st.error(f"Only {p['stock']} in stock.")
        else:
            st.session_state.cart.append(
                {"product_id": int(prod_id), "name": p["name"], "qty": int(qty),
                 "price": float(p["price"]), "gst_rate": float(p["gst_rate"])}
            )

    if st.session_state.cart:
        cart_df = pd.DataFrame(st.session_state.cart)
        cart_df["taxable"] = cart_df["qty"] * cart_df["price"]
        cart_df["gst_amt"] = cart_df["taxable"] * cart_df["gst_rate"] / 100
        cart_df["amount"] = cart_df["taxable"] + cart_df["gst_amt"]
        st.dataframe(
            cart_df[["name", "qty", "price", "taxable", "gst_rate", "gst_amt", "amount"]],
            use_container_width=True, hide_index=True,
        )
        taxable_total = cart_df["taxable"].sum()
        gst_total = cart_df["gst_amt"].sum()
        total = taxable_total + gst_total
        m1, m2, m3 = st.columns(3)
        m1.metric("Taxable", f"₹{taxable_total:,.2f}")
        m2.metric("GST", f"₹{gst_total:,.2f}")
        m3.metric("Grand Total", f"₹{total:,.2f}")

        advance = st.number_input("Advance payment (₹)", min_value=0.0,
                                  max_value=float(total), step=10.0)
        method = st.selectbox("Payment method", ["Cash", "UPI", "Card", "Bank Transfer"])

        b1, b2 = st.columns(2)
        if b1.button("✅ Place Order"):
            order_id = run(
                "INSERT INTO orders (customer_id, order_date, total) VALUES (?,?,?)",
                (int(cust_id), date.today().isoformat(), float(round(total, 2))),
            )
            for item in st.session_state.cart:
                run("INSERT INTO order_items (order_id, product_id, qty, price, gst_rate) "
                    "VALUES (?,?,?,?,?)",
                    (order_id, item["product_id"], item["qty"], item["price"], item["gst_rate"]))
                run("UPDATE products SET stock = stock - ? WHERE id=?",
                    (item["qty"], item["product_id"]))
            if advance > 0:
                run("INSERT INTO payments (order_id, amount, method, paid_on) VALUES (?,?,?,?)",
                    (order_id, float(advance), method, date.today().isoformat()))
            st.session_state.cart = []
            st.success(f"Order #{order_id} placed. Invoice: Orders & Payments page lo download cheyyandi.")
            st.rerun()
        if b2.button("🗑️ Clear Cart"):
            st.session_state.cart = []
            st.rerun()

# ----------------------------------------------------------------------------
# ORDERS & PAYMENTS
# ----------------------------------------------------------------------------
elif page == "💳 Orders & Payments":
    st.title("💳 Orders & Payments")
    orders = add_status(query(ORDERS_SQL))

    if orders.empty:
        st.info("No orders yet.")
        st.stop()

    flt = st.radio("Filter", ["All", "Unpaid", "Partial", "Paid"], horizontal=True)
    view = orders if flt == "All" else orders[orders["status"] == flt]
    st.dataframe(view, use_container_width=True, hide_index=True)

    st.subheader("Record a Payment")
    pending = orders[orders["balance"] > 0]
    if pending.empty:
        st.success("All orders are fully paid. 🎉")
    else:
        oid = st.selectbox(
            "Order", pending["order_id"],
            format_func=lambda i: "#{} - {} (due ₹{:,.0f})".format(
                i,
                pending.loc[pending["order_id"] == i, "customer"].iloc[0],
                pending.loc[pending["order_id"] == i, "balance"].iloc[0],
            ),
        )
        due = float(pending.loc[pending["order_id"] == oid, "balance"].iloc[0])
        amt = st.number_input("Amount (₹)", min_value=1.0, max_value=due, value=due)
        method = st.selectbox("Method", ["Cash", "UPI", "Card", "Bank Transfer"])
        if st.button("Save Payment"):
            run("INSERT INTO payments (order_id, amount, method, paid_on) VALUES (?,?,?,?)",
                (int(oid), float(amt), method, date.today().isoformat()))
            st.success("Payment recorded.")
            st.rerun()

    st.subheader("🧾 Order Details & GST Invoice")
    sel = st.selectbox("Order #", orders["order_id"])
    items = query(
        """SELECT p.name AS product, i.qty, i.price, i.gst_rate,
                  i.qty * i.price AS taxable,
                  i.qty * i.price * i.gst_rate / 100 AS gst
           FROM order_items i JOIN products p ON p.id = i.product_id
           WHERE i.order_id = ?""", (int(sel),))
    st.dataframe(items, use_container_width=True, hide_index=True)
    pays = query("SELECT amount, method, paid_on FROM payments WHERE order_id=?", (int(sel),))
    st.caption("Payments")
    st.dataframe(pays, use_container_width=True, hide_index=True)

    st.download_button(
        "⬇️ Download GST Invoice (PDF)",
        build_invoice(int(sel)),
        file_name=f"invoice_INV-{int(sel):05d}.pdf",
        mime="application/pdf",
    )

# ----------------------------------------------------------------------------
# REPORTS
# ----------------------------------------------------------------------------
elif page == "📈 Reports":
    st.title("📈 Reports")

    c1, c2 = st.columns(2)
    start = c1.date_input("From", date.today() - timedelta(days=30))
    end = c2.date_input("To", date.today())

    orders = add_status(query(ORDERS_SQL))
    if not orders.empty:
        orders = orders[(orders["order_date"] >= start.isoformat()) &
                        (orders["order_date"] <= end.isoformat())]

    if orders.empty:
        st.info("No orders in this range.")
        st.stop()

    m1, m2, m3 = st.columns(3)
    m1.metric("Sales", f"₹{orders['total'].sum():,.0f}")
    m2.metric("Collected", f"₹{orders['paid'].sum():,.0f}")
    m3.metric("Outstanding", f"₹{orders['balance'].sum():,.0f}")

    tab1, tab2, tab3 = st.tabs(["Top Products", "Top Customers", "Outstanding"])

    with tab1:
        top_p = query(
            """SELECT p.name AS product, SUM(i.qty) AS units, SUM(i.qty * i.price) AS revenue
               FROM order_items i
               JOIN products p ON p.id = i.product_id
               JOIN orders o ON o.id = i.order_id
               WHERE o.order_date BETWEEN ? AND ?
               GROUP BY p.id, p.name ORDER BY revenue DESC""",
            (start.isoformat(), end.isoformat()))
        st.plotly_chart(style_fig(px.bar(top_p, x="product", y="revenue",
                                         title="Revenue by Product (before GST)")),
                        use_container_width=True)
        st.dataframe(top_p, use_container_width=True, hide_index=True)

    with tab2:
        top_c = orders.groupby("customer", as_index=False)["total"].sum() \
                      .sort_values("total", ascending=False)
        st.plotly_chart(style_fig(px.bar(top_c, x="customer", y="total",
                                         title="Sales by Customer")),
                        use_container_width=True)
        st.dataframe(top_c, use_container_width=True, hide_index=True)

    with tab3:
        out = orders[orders["balance"] > 0]
        st.dataframe(out, use_container_width=True, hide_index=True)

    st.download_button(
        "⬇️ Download orders CSV",
        orders.to_csv(index=False).encode("utf-8"),
        file_name="orders_report.csv",
        mime="text/csv",
    )

# ----------------------------------------------------------------------------
# MY ACCOUNT (every user can change their own password)
# ----------------------------------------------------------------------------
elif page == "👤 My Account":
    st.title("👤 My Account")
    st.write(f"Username: **{user['username']}**  |  Role: **{user['role']}**")

    st.subheader("Change my password")
    with st.form("change_pw", clear_on_submit=True):
        cur_pw = st.text_input("Current password", type="password")
        new_pw = st.text_input("New password (min 6 characters)", type="password")
        new_pw2 = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Change Password"):
            row = query("SELECT password_hash FROM users WHERE id=?", (user["id"],))
            if row.empty or not verify_pw(cur_pw, row.loc[0, "password_hash"]):
                st.error("Current password is wrong.")
            elif len(new_pw) < 6:
                st.error("New password must be at least 6 characters.")
            elif new_pw != new_pw2:
                st.error("New passwords do not match.")
            else:
                run("UPDATE users SET password_hash=? WHERE id=?",
                    (hash_pw(new_pw), user["id"]))
                run("DELETE FROM sessions WHERE user_id=? AND token_hash<>?",
                    (user["id"], st.session_state.get("token_hash", "")))
                st.success("Password changed. Next login ki kotha password vadandi.")

# ----------------------------------------------------------------------------
# USERS (admin only)
# ----------------------------------------------------------------------------
elif page == "🔑 Users" and is_admin:
    st.title("🔑 Users")
    users_df = query("SELECT id, username, role FROM users ORDER BY id")
    st.dataframe(users_df, use_container_width=True, hide_index=True)

    tab_add, tab_edit, tab_del = st.tabs(["Add User", "Change Username / Password", "Delete User"])

    with tab_add:
        with st.form("add_user", clear_on_submit=True):
            new_u = st.text_input("Username")
            new_p = st.text_input("Password (min 6 characters)", type="password")
            role = st.selectbox("Role", ["staff", "admin"])
            if st.form_submit_button("Create User"):
                if not new_u.strip() or len(new_p) < 6:
                    st.error("Username required and password min 6 characters.")
                else:
                    try:
                        run("INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                            (new_u.strip(), hash_pw(new_p), role))
                        st.success(f"User '{new_u.strip()}' created.")
                    except pg_errors.UniqueViolation:
                        st.error("This username already exists.")

    with tab_edit:
        uid = st.selectbox(
            "User", users_df["id"],
            format_func=lambda i: users_df.loc[users_df["id"] == i, "username"].iloc[0],
            key="edit_uid",
        )
        cur_name = users_df.loc[users_df["id"] == uid, "username"].iloc[0]
        with st.form("edit_user"):
            e_name = st.text_input("Username", value=cur_name)
            e_pass = st.text_input("New password (khali vadilesthe password maradu)",
                                   type="password")
            if st.form_submit_button("Save Changes"):
                if not e_name.strip():
                    st.error("Username cannot be empty.")
                elif e_pass and len(e_pass) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    try:
                        run("UPDATE users SET username=? WHERE id=?", (e_name.strip(), int(uid)))
                        if e_pass:
                            run("UPDATE users SET password_hash=? WHERE id=?",
                                (hash_pw(e_pass), int(uid)))
                            keep = st.session_state.get("token_hash", "") \
                                if int(uid) == user["id"] else ""
                            run("DELETE FROM sessions WHERE user_id=? AND token_hash<>?",
                                (int(uid), keep))
                        if int(uid) == user["id"]:
                            st.session_state.user["username"] = e_name.strip()
                        st.success("Saved.")
                        st.rerun()
                    except pg_errors.UniqueViolation:
                        st.error("This username already exists.")

    with tab_del:
        others = users_df[users_df["id"] != user["id"]]
        if others.empty:
            st.info("No other users to delete.")
        else:
            did = st.selectbox(
                "User", others["id"],
                format_func=lambda i: others.loc[others["id"] == i, "username"].iloc[0],
                key="del_uid",
            )
            if st.button("Delete User"):
                run("DELETE FROM users WHERE id=?", (int(did),))
                st.success("User deleted.")
                st.rerun()

# ----------------------------------------------------------------------------
# BUSINESS SETTINGS (admin only) - used on the GST invoice
# ----------------------------------------------------------------------------
elif page == "⚙️ Business Settings" and is_admin:
    st.title("⚙️ Business Settings")
    st.caption("Ee details GST invoice paina vastayi.")
    cfg = get_settings()
    with st.form("settings"):
        business_name = st.text_input("Business name", value=cfg.get("business_name", ""))
        address = st.text_area("Address", value=cfg.get("address", ""))
        phone = st.text_input("Phone", value=cfg.get("phone", ""))
        gstin = st.text_input("Your GSTIN", value=cfg.get("gstin", ""))
        cur_state = cfg.get("state", "")
        state = st.selectbox(
            "Your state", [""] + INDIAN_STATES,
            index=([""] + INDIAN_STATES).index(cur_state) if cur_state in INDIAN_STATES else 0,
        )
        footer = st.text_input("Invoice footer message",
                               value=cfg.get("footer", "Thank you for your business!"))
        if st.form_submit_button("Save Settings"):
            for k, v in {
                "business_name": business_name, "address": address, "phone": phone,
                "gstin": gstin.strip().upper(), "state": state, "footer": footer,
            }.items():
                run("INSERT INTO settings (key, value) VALUES (?,?) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (k, v))
            st.success("Settings saved.")
