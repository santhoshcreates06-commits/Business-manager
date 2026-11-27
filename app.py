from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st

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


# ----------------------------------------------------------------------------
# DATABASE (Neon PostgreSQL, connection string comes from Streamlit secrets)
# ----------------------------------------------------------------------------
def get_conn():
    return psycopg2.connect(st.secrets["DATABASE_URL"])


def _pg(sql):
    # keep "?" placeholders in the app code, convert for PostgreSQL
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
                    """
                )
    finally:
        conn.close()
    return True


init_db()

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
# SIDEBAR NAVIGATION
# ----------------------------------------------------------------------------
st.sidebar.markdown("## 🏏 RCB Business Manager")
st.sidebar.caption("Play Bold. Manage Better.")
page = st.sidebar.radio(
    "Navigate",
    [
        "📊 Dashboard",
        "👥 Customers",
        "📦 Products",
        "🛒 New Order",
        "💳 Orders & Payments",
        "📈 Reports",
    ],
)

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
            if st.form_submit_button("Save Customer"):
                if name.strip():
                    run(
                        "INSERT INTO customers (name, phone, email, address) VALUES (?,?,?,?)",
                        (name.strip(), phone, email, address),
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
            price = st.number_input("Price (₹)", min_value=0.0, step=1.0)
            stock = st.number_input("Opening stock", min_value=0, step=1)
            if st.form_submit_button("Save Product"):
                if name.strip():
                    run(
                        "INSERT INTO products (name, price, stock) VALUES (?,?,?)",
                        (name.strip(), float(price), int(stock)),
                    )
                    st.success(f"Product '{name}' added.")
                else:
                    st.error("Name is required.")

    with tab_list:
        df = query("SELECT * FROM products ORDER BY name")
        st.dataframe(df, use_container_width=True, hide_index=True)

        if not df.empty:
            with st.expander("Update price / stock"):
                pid = st.selectbox(
                    "Product", df["id"],
                    format_func=lambda i: df.loc[df["id"] == i, "name"].iloc[0],
                )
                row = df[df["id"] == pid].iloc[0]
                new_price = st.number_input("Price (₹)", value=float(row["price"]), min_value=0.0)
                new_stock = st.number_input("Stock", value=int(row["stock"]), min_value=0)
                if st.button("Update"):
                    run("UPDATE products SET price=?, stock=? WHERE id=?",
                        (float(new_price), int(new_stock), int(pid)))
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
        format_func=lambda i: "{} (₹{:,.0f}, stock {})".format(
            products.loc[products["id"] == i, "name"].iloc[0],
            products.loc[products["id"] == i, "price"].iloc[0],
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
                {"product_id": int(prod_id), "name": p["name"],
                 "qty": int(qty), "price": float(p["price"])}
            )

    if st.session_state.cart:
        cart_df = pd.DataFrame(st.session_state.cart)
        cart_df["subtotal"] = cart_df["qty"] * cart_df["price"]
        st.dataframe(cart_df[["name", "qty", "price", "subtotal"]],
                     use_container_width=True, hide_index=True)
        total = cart_df["subtotal"].sum()
        st.subheader(f"Total: ₹{total:,.2f}")

        advance = st.number_input("Advance payment (₹)", min_value=0.0,
                                  max_value=float(total), step=10.0)
        method = st.selectbox("Payment method", ["Cash", "UPI", "Card", "Bank Transfer"])

        b1, b2 = st.columns(2)
        if b1.button("✅ Place Order"):
            order_id = run(
                "INSERT INTO orders (customer_id, order_date, total) VALUES (?,?,?)",
                (int(cust_id), date.today().isoformat(), float(total)),
            )
            for item in st.session_state.cart:
                run("INSERT INTO order_items (order_id, product_id, qty, price) VALUES (?,?,?,?)",
                    (order_id, item["product_id"], item["qty"], item["price"]))
                run("UPDATE products SET stock = stock - ? WHERE id=?",
                    (item["qty"], item["product_id"]))
            if advance > 0:
                run("INSERT INTO payments (order_id, amount, method, paid_on) VALUES (?,?,?,?)",
                    (order_id, float(advance), method, date.today().isoformat()))
            st.session_state.cart = []
            st.success(f"Order #{order_id} placed.")
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

    with st.expander("Order details"):
        sel = st.selectbox("Order #", orders["order_id"])
        items = query(
            """SELECT p.name AS product, i.qty, i.price, i.qty * i.price AS subtotal
               FROM order_items i JOIN products p ON p.id = i.product_id
               WHERE i.order_id = ?""", (int(sel),))
        st.dataframe(items, use_container_width=True, hide_index=True)
        pays = query("SELECT amount, method, paid_on FROM payments WHERE order_id=?", (int(sel),))
        st.caption("Payments")
        st.dataframe(pays, use_container_width=True, hide_index=True)

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
                                         title="Revenue by Product")),
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
