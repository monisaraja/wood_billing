"""
app.py
------
Run with:   streamlit run app.py

Layout:
  - Left sidebar : login user, MENU (New Bill / Analysis / Deep Analysis),
                   Add Customer, Add Wood Type.
  - Main page    : whichever menu item was tapped.

Key points:
  - LIGHT theme (white background, black text) applied with CSS only
    (no JavaScript - the dropdown problem cannot come back).
  - Wood Type / Payment Status / Payment Mode are TAP-TO-SELECT buttons
    (st.radio), not dropdowns. Only Party Name stays a searchable
    dropdown because you type to find a customer.
  - No Storage Location field.
  - First row: Wood Type, Party Name, Vehicle No, Date.
  - Compact layout designed to fit without scrolling.
  - 🖨️ Print Bill button generates a clean PDF (needs fpdf2 -
    `pip install fpdf2`).
  - Grand Total = (Total Weight kg / 1000) x Rate per ton - Weighment Fee
"""

import datetime
import os
import shutil
import pandas as pd
import streamlit as st

try:
    import plotly.express as px
    HAVE_PLOTLY = True
except Exception:
    HAVE_PLOTLY = False

try:
    from fpdf import FPDF
    HAVE_PDF = True
except Exception:
    HAVE_PDF = False

from database import (
    init_db, verify_user,
    add_customer, get_customer_names,
    add_wood_type, get_all_wood_types,
    save_bill, get_connection, hash_password,
)

st.set_page_config(page_title="Wood Billing System", page_icon="🪵",
                   layout="wide")
init_db()


# ======================================================================
# LIGHT THEME  (pure CSS - no script, safe for the dropdown)
# ======================================================================
def apply_dark_theme():
    st.markdown(
        """
        <style>
        .stApp, [data-testid="stAppViewContainer"],
        [data-testid="stHeader"] { background-color: #ffffff; }
        section[data-testid="stSidebar"] { background-color: #f5f5f5; }
        .stApp, .stApp p, .stApp span, .stApp label, .stApp div,
        h1, h2, h3, h4, h5, h6, .stMarkdown, .stCaption {
            color: #111111 !important;
        }
        /* tighten vertical spacing so everything fits one page */
        .block-container { padding-top: 1.2rem; padding-bottom: 1rem; }
        [data-testid="stVerticalBlock"] { gap: 0.55rem; }
        hr { margin: 0.5rem 0; border-color: #dddddd; }
        /* text / number inputs */
        input, textarea,
        .stTextInput input, .stNumberInput input, .stDateInput input {
            background-color: #ffffff !important;
            color: #111111 !important;
            border: 1px solid #cccccc !important;
        }
        /* the only remaining dropdown (Party Name): readable on white */
        [data-baseweb="select"] > div {
            background-color: #ffffff !important;
            color: #111111 !important;
            border: 1px solid #cccccc !important;
        }
        [data-baseweb="popover"], [role="listbox"] {
            background-color: #ffffff !important;
            color: #111111 !important;
            border: 1px solid #cccccc !important;
        }
        [role="option"] { color: #111111 !important; }
        [data-testid="stMetricValue"] { color: #000000 !important; }
        [data-testid="stMetricLabel"] { color: #555555 !important; }
        /* tap-to-select chips */
        div[role="radiogroup"] label {
            background: #ffffff; border: 1px solid #cccccc;
            color: #111111;
            padding: 4px 12px; border-radius: 6px; margin: 2px 4px 2px 0;
        }
        .stDataFrame, [data-testid="stDataFrame"] { background-color:#ffffff; }
        /* Watermark - visible on every page, sits above content but does
           not block clicks. */
        #mr-watermark {
            position: fixed;
            right: 14px;
            bottom: 10px;
            font-size: 12px;
            font-style: italic;
            color: #555;
            opacity: 0.7;
            letter-spacing: 0.3px;
            pointer-events: none;
            z-index: 9999;
            user-select: none;
        }
        </style>
        <div id="mr-watermark">Powered by Monisa_raja</div>
        """,
        unsafe_allow_html=True,
    )


# ---- session memory ----
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "view" not in st.session_state:
    st.session_state.view = "bill"


# ======================================================================
# LOGIN PAGE
# ======================================================================
def login_page():
    left, center, right = st.columns([1, 1.4, 1])
    with center:
        st.title("🪵 Wood Billing System")
        st.subheader("Please log in")
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password",
                                  key="login_pass")
        if st.button("Login", type="primary", use_container_width=True):
            if verify_user(username, password):
                st.session_state.logged_in = True
                st.session_state.username = username
                st.rerun()
            else:
                st.error("Invalid username or password.")
        st.caption("First time? Default login is  **admin / admin123**")


# ======================================================================
# ANALYSIS HELPERS
# ======================================================================
def _weight_per_bill_subquery():
    return ("(SELECT bill_id, SUM(total_weight) AS tw "
            "FROM bill_items GROUP BY bill_id)")


def run_analysis(from_date, to_date, party):
    conn = get_connection()
    try:
        sql = f"""
            SELECT b.customer_name              AS Party,
                   COUNT(*)                     AS Bills,
                   COALESCE(SUM(w.tw), 0)       AS "Total Weight (kg)",
                   COALESCE(SUM(b.grand_total), 0) AS "Total Amount (Rs)"
            FROM bills b
            LEFT JOIN {_weight_per_bill_subquery()} w ON w.bill_id = b.id
            WHERE date(b.bill_date) BETWEEN date(?) AND date(?)
        """
        params = [str(from_date), str(to_date)]
        if party and party != "All parties":
            sql += " AND b.customer_name = ?"
            params.append(party)
        sql += " GROUP BY b.customer_name ORDER BY \"Total Amount (Rs)\" DESC"
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def run_deep_analysis(from_date, to_date):
    conn = get_connection()
    try:
        w_sub = _weight_per_bill_subquery()
        wood_df = pd.read_sql_query(
            f"""SELECT b.wood_type AS Wood,
                       COALESCE(SUM(w.tw), 0) AS Weight
                FROM bills b
                LEFT JOIN {w_sub} w ON w.bill_id = b.id
                WHERE date(b.bill_date) BETWEEN date(?) AND date(?)
                GROUP BY b.wood_type HAVING Weight > 0""",
            conn, params=[str(from_date), str(to_date)],
        )
        party_df = pd.read_sql_query(
            f"""SELECT b.customer_name AS Party,
                       COALESCE(SUM(w.tw), 0) AS Weight
                FROM bills b
                LEFT JOIN {w_sub} w ON w.bill_id = b.id
                WHERE date(b.bill_date) BETWEEN date(?) AND date(?)
                GROUP BY b.customer_name HAVING Weight > 0
                ORDER BY Weight DESC""",
            conn, params=[str(from_date), str(to_date)],
        )
        rate_row = pd.read_sql_query(
            """SELECT AVG(rate) AS avg_rate
               FROM bill_items
               WHERE rate > 0 AND bill_id IN (
                   SELECT id FROM bills
                   WHERE date(bill_date) BETWEEN date(?) AND date(?))""",
            conn, params=[str(from_date), str(to_date)],
        )
        avg_rate = float(rate_row["avg_rate"].iloc[0] or 0.0)
        intake = pd.read_sql_query(
            f"""SELECT COALESCE(SUM(w.tw), 0) AS total_w,
                       COUNT(DISTINCT b.bill_date) AS days
                FROM bills b
                LEFT JOIN {w_sub} w ON w.bill_id = b.id
                WHERE date(b.bill_date) BETWEEN date(?) AND date(?)""",
            conn, params=[str(from_date), str(to_date)],
        )
        total_w = float(intake["total_w"].iloc[0] or 0.0)
        days = int(intake["days"].iloc[0] or 0)
        avg_intake = (total_w / days) if days else 0.0
        return wood_df, party_df, avg_rate, avg_intake
    finally:
        conn.close()


def _style_dark(fig):
    fig.update_layout(template="plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#111111"),
                      height=360, margin=dict(l=0, r=0, t=10, b=0))
    return fig


# ======================================================================
# SIDEBAR
# ======================================================================
def sidebar():
    with st.sidebar:
        st.write(f"👤 **{st.session_state.username}**")
        if st.button("Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.rerun()

        with st.expander("🔑 Change username / password"):
            with st.form("change_creds_form", clear_on_submit=False):
                cur_pw = st.text_input("Current password", type="password",
                                       key="cc_cur_pw")
                new_user = st.text_input(
                    "New username",
                    value=st.session_state.username,
                    help="Leave as-is to keep the current username.",
                    key="cc_new_user",
                )
                new_pw = st.text_input("New password", type="password",
                                       key="cc_new_pw",
                                       help="Leave blank to keep current.")
                confirm_pw = st.text_input("Confirm new password",
                                           type="password",
                                           key="cc_confirm_pw")
                submitted = st.form_submit_button("Update credentials",
                                                  use_container_width=True)

            if submitted:
                old_user = st.session_state.username
                new_user_clean = (new_user or "").strip()

                # 1. Verify current password before allowing any change.
                if not cur_pw or not verify_user(old_user, cur_pw):
                    st.error("Current password is incorrect.")
                # 2. Username cannot be blank.
                elif not new_user_clean:
                    st.error("Username cannot be empty.")
                # 3. If a new password was entered, it must match confirm.
                elif new_pw and new_pw != confirm_pw:
                    st.error("New password and confirmation do not match.")
                # 4. Require an actual change.
                elif new_user_clean == old_user and not new_pw:
                    st.info("Nothing to change.")
                else:
                    try:
                        conn = get_connection()
                        cur = conn.cursor()
                        # Block username collisions with a different user.
                        if new_user_clean != old_user:
                            cur.execute(
                                "SELECT 1 FROM users WHERE username = ?",
                                (new_user_clean,),
                            )
                            if cur.fetchone() is not None:
                                conn.close()
                                st.error("That username is already taken.")
                                st.stop()
                        if new_pw:
                            cur.execute(
                                "UPDATE users "
                                "SET username = ?, password_hash = ? "
                                "WHERE username = ?",
                                (new_user_clean, hash_password(new_pw),
                                 old_user),
                            )
                        else:
                            cur.execute(
                                "UPDATE users SET username = ? "
                                "WHERE username = ?",
                                (new_user_clean, old_user),
                            )
                        conn.commit()
                        conn.close()
                        st.session_state.username = new_user_clean
                        st.success("Credentials updated. Use the new "
                                   "ones next time you log in.")
                    except Exception as e:
                        st.error(f"Update failed: {e}")

        st.divider()
        st.subheader("📂 Menu")
        if st.button("🧾 New Bill", use_container_width=True,
                     type="primary" if st.session_state.view == "bill"
                     else "secondary"):
            st.session_state.view = "bill"
            st.rerun()
        if st.button("📊 Analysis", use_container_width=True,
                     type="primary" if st.session_state.view == "analysis"
                     else "secondary"):
            st.session_state.view = "analysis"
            st.rerun()
        if st.button("🔍 Deep Analysis", use_container_width=True,
                     type="primary" if st.session_state.view == "deep"
                     else "secondary"):
            st.session_state.view = "deep"
            st.rerun()

        st.divider()
        st.header("➕ Add Customer")
        with st.form("add_customer_form", clear_on_submit=True):
            c_name = st.text_input("Customer Name *")
            c_phone = st.text_input("Phone")
            c_addr = st.text_input("Address")
            if st.form_submit_button("Save Customer",
                                     use_container_width=True):
                if add_customer(c_name, c_phone, c_addr):
                    st.success(f"Added '{c_name}'.")
                    st.rerun()
                else:
                    st.error("Customer name is required.")

        with st.expander("🪵 Add Wood Type"):
            with st.form("add_wood_form", clear_on_submit=True):
                w_name = st.text_input("Wood Type *")
                if st.form_submit_button("Save Wood Type",
                                         use_container_width=True):
                    if add_wood_type(w_name, ""):
                        st.success(f"Added '{w_name}'.")
                        st.rerun()
                    else:
                        st.error("Name required, or it already exists.")

        with st.expander("💾 Backup & Restore"):
            db_path = "wood_billing.db"
            # ---- Download a backup of the current database ----
            if os.path.exists(db_path):
                try:
                    with open(db_path, "rb") as f:
                        db_bytes = f.read()
                    today_str = datetime.date.today().isoformat()
                    st.download_button(
                        "⬇️ Download backup",
                        data=db_bytes,
                        file_name=f"wood_billing_{today_str}.db",
                        mime="application/x-sqlite3",
                        use_container_width=True,
                        help="Saves the entire database as a single file. "
                             "Keep it somewhere safe (Google Drive, "
                             "pen-drive, email to yourself).",
                    )
                except Exception as e:
                    st.warning(f"Backup unavailable: {e}")
            else:
                st.caption("Database file not found yet — save a bill "
                           "first.")

            st.markdown("---")

            # ---- Restore from a previously-downloaded backup ----
            up = st.file_uploader(
                "Restore from a backup file",
                type=["db"], key="restore_upload",
                help="Pick a .db file you downloaded earlier. This "
                     "REPLACES all current data.",
            )
            if up is not None:
                st.warning("This will replace ALL current data. A safety "
                           "copy of the current database will be kept as "
                           "`wood_billing.before_restore.db`.")
                if st.button("Confirm Restore", type="primary",
                             use_container_width=True):
                    try:
                        if os.path.exists(db_path):
                            shutil.copy2(
                                db_path,
                                "wood_billing.before_restore.db",
                            )
                        with open(db_path, "wb") as f:
                            f.write(up.getbuffer())
                        st.success("Restored. Reloading...")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Restore failed: {e}")

            st.caption("Tip: keep `wood_billing.db` inside a folder synced "
                       "by Google Drive Desktop and you get automatic "
                       "cloud backup with zero code.")


# ======================================================================
# PDF BILL BUILDER  (used by the 🖨️ Print Bill button)
# ======================================================================
def build_bill_pdf(party, wood, vehicle, bill_date, status, mode,
                   rows_df, weighment_fee, grand_total):
    """Return the bill as PDF bytes. Requires fpdf2."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Wood Billing - Receipt", ln=True, align="C")
    pdf.ln(2)

    # Header info (two columns)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(95, 7, f"Date: {bill_date}", ln=0)
    pdf.cell(95, 7, f"Vehicle: {vehicle or '-'}", ln=1)
    pdf.cell(95, 7, f"Party: {party or '-'}", ln=0)
    pdf.cell(95, 7, f"Wood Type: {wood or '-'}", ln=1)
    pdf.cell(0, 7, f"Payment: {status} ({mode})", ln=1)
    pdf.ln(3)

    # Items table header
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(35, 8, "Initial (kg)", border=1, align="C")
    pdf.cell(35, 8, "Empty (kg)", border=1, align="C")
    pdf.cell(35, 8, "Total (kg)", border=1, align="C")
    pdf.cell(40, 8, "Rate (per ton)", border=1, align="C")
    pdf.cell(45, 8, "Row Value (Rs)", border=1, align="C", ln=1)

    # Items rows
    pdf.set_font("Helvetica", "", 10)
    total_w = 0.0
    total_v = 0.0
    for _, r in rows_df.iterrows():
        if r["Initial Weight"] <= 0:
            continue
        pdf.cell(35, 7, f"{r['Initial Weight']:.2f}", border=1, align="R")
        pdf.cell(35, 7, f"{r['Empty Weight']:.2f}", border=1, align="R")
        pdf.cell(35, 7, f"{r['Total Weight']:.2f}", border=1, align="R")
        pdf.cell(40, 7, f"{r['Rate']:.2f}", border=1, align="R")
        pdf.cell(45, 7, f"Rs {r['Row Value']:,.2f}", border=1,
                 align="R", ln=1)
        total_w += float(r["Total Weight"])
        total_v += float(r["Row Value"])

    pdf.ln(4)

    # Totals block
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(150, 7, "Total Weight:", align="R")
    pdf.cell(40, 7, f"{total_w:,.2f} kg", ln=1, align="R")
    pdf.cell(150, 7, "Weight x Rate:", align="R")
    pdf.cell(40, 7, f"Rs {total_v:,.2f}", ln=1, align="R")
    pdf.cell(150, 7, "Weighment Fee:", align="R")
    pdf.cell(40, 7, f"- Rs {weighment_fee:,.2f}", ln=1, align="R")
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(150, 9, "GRAND TOTAL:", align="R")
    pdf.cell(40, 9, f"Rs {grand_total:,.2f}", ln=1, align="R")

    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 5, "Powered by Monisa_raja", ln=1, align="R")

    # fpdf2 returns bytearray; older fpdf returned str. Handle both.
    out = pdf.output(dest="S")
    if isinstance(out, str):
        out = out.encode("latin-1", errors="replace")
    return bytes(out)


# ======================================================================
# MAIN PAGE: ANALYSIS
# ======================================================================
def analysis_page():
    st.title("📊 Analysis")
    today = datetime.date.today()
    c1, c2, c3 = st.columns(3)
    a_from = c1.date_input("From Date",
                           value=today - datetime.timedelta(days=30),
                           key="an_from")
    a_to = c2.date_input("To Date", value=today, key="an_to")
    a_party = c3.selectbox("Party Name",
                           ["All parties"] + get_customer_names(),
                           key="an_party")
    try:
        tbl = run_analysis(a_from, a_to, a_party)
        if tbl.empty:
            st.info("No bills in this date range.")
        else:
            st.dataframe(
                tbl.style.format({
                    "Total Weight (kg)": "{:,.2f}",
                    "Total Amount (Rs)": "Rs {:,.2f}",
                }),
                use_container_width=True, hide_index=True,
            )
            t1, t2 = st.columns(2)
            t1.metric("Total Weight",
                      f"{tbl['Total Weight (kg)'].sum():,.2f} kg")
            t2.metric("Total Amount",
                      f"Rs {tbl['Total Amount (Rs)'].sum():,.2f}")
    except Exception as e:
        st.warning(f"Analysis unavailable: {e}")


# ======================================================================
# MAIN PAGE: DEEP ANALYSIS
# ======================================================================
def deep_analysis_page():
    st.title("🔍 Deep Analysis")
    today = datetime.date.today()
    d1, d2 = st.columns(2)
    d_from = d1.date_input("From Date",
                           value=today - datetime.timedelta(days=30),
                           key="da_from")
    d_to = d2.date_input("To Date", value=today, key="da_to")
    try:
        wood_df, party_df, avg_rate, avg_intake = run_deep_analysis(
            d_from, d_to)
        m1, m2 = st.columns(2)
        m1.metric("Avg Wood Rate", f"Rs {avg_rate:,.2f}")
        m2.metric("Avg Intake / Day", f"{avg_intake:,.1f} kg")
        st.divider()
        g1, g2 = st.columns(2)
        with g1:
            st.subheader("Wood-type distribution")
            if wood_df.empty:
                st.caption("No data yet.")
            elif HAVE_PLOTLY:
                fig = px.pie(wood_df, names="Wood", values="Weight",
                             hole=0.55)
                fig.update_traces(textposition="inside",
                                  textinfo="percent+label")
                st.plotly_chart(_style_dark(fig), use_container_width=True)
            else:
                st.dataframe(wood_df, use_container_width=True,
                             hide_index=True)
        with g2:
            st.subheader("Party-wise distribution")
            if party_df.empty:
                st.caption("No data yet.")
            elif HAVE_PLOTLY:
                fig2 = px.pie(party_df, names="Party", values="Weight",
                              hole=0.55)
                fig2.update_traces(textposition="inside",
                                   textinfo="percent+label")
                st.plotly_chart(_style_dark(fig2), use_container_width=True)
            else:
                st.dataframe(party_df, use_container_width=True,
                             hide_index=True)
    except Exception as e:
        st.warning(f"Deep Analysis unavailable: {e}")


# ======================================================================
# MAIN PAGE: BILLING
# ======================================================================
def billing_interface():
    st.title("📋 New Bill")

    # ---- First row: Wood Type, Party Name, Vehicle No, Date ----
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])

    with c1:
        wood_list = [w["name"] for w in get_all_wood_types()] or ["(none)"]
        wood_type = st.radio("Wood Type", wood_list, horizontal=True)

    with c2:
        party_name = st.selectbox(
            "Party Name (type to search)",
            options=["-- select --"] + get_customer_names(),
            help="Add customers from the left sidebar.",
        )

    with c3:
        vehicle_number = st.text_input("Vehicle No",
                                       placeholder="TN-09-AB-1234")

    with c4:
        bill_date = st.date_input("Date", value=datetime.date.today())

    # ---- Second row: payment status + mode (tap to select) ----
    p1, p2 = st.columns(2)
    with p1:
        payment_status = st.radio("Payment Status",
                                  ["Paid", "Pending", "Partial"],
                                  horizontal=True)
    with p2:
        payment_mode = st.radio("Mode of Payment",
                                ["Cash", "GPay", "Bank Account"],
                                horizontal=True)

    st.divider()
    st.caption("Weight Rows — use the + at the bottom of the table to add "
               "rows. Rate is per ton; weight is in kg.")

    if "bill_rows" not in st.session_state:
        st.session_state.bill_rows = pd.DataFrame(
            [{"Initial Weight": 0.0, "Empty Weight": 0.0, "Rate": 0.0}]
        )

    edited = st.data_editor(
        st.session_state.bill_rows,
        num_rows="dynamic",
        use_container_width=True,
        key="weight_editor",
        column_config={
            "Initial Weight": st.column_config.NumberColumn(
                min_value=0.0, format="%.2f"),
            "Empty Weight": st.column_config.NumberColumn(
                min_value=0.0, format="%.2f"),
            "Rate": st.column_config.NumberColumn(
                "Rate (per ton)", min_value=0.0, format="%.2f"),
        },
    )

    df = pd.DataFrame(edited).copy().fillna(0.0)
    df["Total Weight"] = (df["Initial Weight"]
                          - df["Empty Weight"]).clip(lower=0)
    df["Row Value"] = (df["Total Weight"] / 1000.0) * df["Rate"]

    used_rows = int((df["Initial Weight"] > 0).sum())
    total_weight = float(df["Total Weight"].sum())
    rows_value_sum = float(df["Row Value"].sum())
    auto_fee = float(used_rows * 100)

    if "wf_rows_seen" not in st.session_state:
        st.session_state.wf_rows_seen = None
    if "weighment_fee_input" not in st.session_state:
        st.session_state.weighment_fee_input = auto_fee
    if st.session_state.wf_rows_seen != used_rows:
        st.session_state.weighment_fee_input = auto_fee
        st.session_state.wf_rows_seen = used_rows

    # ---- Compact totals row (no duplicate table) ----
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Weight", f"{total_weight:,.2f} kg")
    m2.metric("Weight × Rate", f"₹ {rows_value_sum:,.2f}")
    with m3:
        weighment_fee = st.number_input(
            "Weighment Fee (₹)", min_value=0.0, step=50.0,
            key="weighment_fee_input",
            help="Auto = used rows × ₹100. Edit if needed.",
        )

    grand_total = rows_value_sum - weighment_fee

    g1, g2 = st.columns([2, 1])
    with g2:
        st.subheader(f"🧾 Grand Total: ₹ {grand_total:,.2f}")
        save_clicked = st.button("💾 Save Bill", type="primary",
                                 use_container_width=True)
        # ---- Print Bill: build a PDF from the current form state ----
        if HAVE_PDF and used_rows > 0:
            try:
                import re
                pdf_bytes = build_bill_pdf(
                    party_name if party_name != "-- select --" else "",
                    wood_type, vehicle_number, bill_date,
                    payment_status, payment_mode,
                    df, weighment_fee, grand_total,
                )
                party_safe = re.sub(
                    r"[^A-Za-z0-9_-]", "_",
                    party_name if party_name != "-- select --" else "draft",
                ) or "draft"
                st.download_button(
                    "🖨️ Print Bill (PDF)",
                    data=pdf_bytes,
                    file_name=f"bill_{party_safe}_{bill_date}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    help="Downloads a printable PDF. Open it and use "
                         "your usual Print to print or save.",
                )
            except Exception as e:
                st.caption(f"PDF unavailable: {e}")
        elif not HAVE_PDF:
            st.caption("To enable Print: `pip install fpdf2` and restart.")
        else:
            st.caption("Add at least one weight row to enable Print.")

    if save_clicked:
        if party_name == "-- select --":
            st.error("Please select a Party Name (add one in the sidebar).")
        elif used_rows == 0:
            st.error("Enter at least one row with an Initial Weight.")
        else:
            rows_payload = [
                {
                    "initial_weight": float(r["Initial Weight"]),
                    "empty_weight": float(r["Empty Weight"]),
                    "total_weight": float(r["Total Weight"]),
                    "rate": float(r["Rate"]),
                    "total_cost": float(r["Row Value"]),
                }
                for _, r in df.iterrows()
                if r["Initial Weight"] > 0
            ]
            # storage no longer shown; pass empty string to keep the
            # existing database function unchanged.
            bill_id = save_bill(
                party_name, wood_type, "", bill_date,
                vehicle_number, payment_status, payment_mode,
                weighment_fee, 0.0, grand_total, rows_payload,
            )
            st.success(f"Bill #{bill_id} saved successfully!")
            st.session_state.pop("weight_editor", None)
            st.session_state.bill_rows = pd.DataFrame(
                [{"Initial Weight": 0.0, "Empty Weight": 0.0, "Rate": 0.0}]
            )
            st.rerun()


# ======================================================================
# ROUTER
# ======================================================================
apply_dark_theme()
if st.session_state.logged_in:
    sidebar()
    if st.session_state.view == "analysis":
        analysis_page()
    elif st.session_state.view == "deep":
        deep_analysis_page()
    else:
        billing_interface()
else:
    login_page()