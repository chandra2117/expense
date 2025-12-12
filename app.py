from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash
import sqlite3
import datetime
import calendar
from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import io
import json
import os

app = Flask(__name__)
app.secret_key = "replace-with-a-secret"
DB = "expenses.db"

# ---------------- Database Setup & Core Helpers (logic preserved) ----------------
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT,
                    date TEXT NOT NULL
                )""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )""")
    conn.commit()
    conn.close()

def add_expense(amount, category, description, date):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO expenses (amount, category, description, date) VALUES (?, ?, ?, ?)",
              (amount, category, description, date))
    conn.commit()
    conn.close()

def delete_expense(expense_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    conn.commit()
    # if table empty, reset sqlite_sequence for expenses to restart AUTOINCREMENT
    c.execute("SELECT COUNT(*) FROM expenses")
    count = c.fetchone()[0]
    if count == 0:
        try:
            c.execute("DELETE FROM sqlite_sequence WHERE name='expenses'")
            conn.commit()
        except Exception:
            # sqlite_sequence might not exist on some sqlite builds - ignore
            pass
    conn.close()

def fetch_expenses(filters=None):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    query = "SELECT * FROM expenses WHERE 1=1"
    params = []

    if filters:
        if filters.get("from_date"):
            query += " AND date >= ?"
            params.append(filters["from_date"])
        if filters.get("to_date"):
            query += " AND date <= ?"
            params.append(filters["to_date"])
        if filters.get("category") and filters["category"] != "All":
            query += " AND category = ?"
            params.append(filters["category"])

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def get_total_expenses_for_month(year, month):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM expenses WHERE strftime('%Y-%m', date) = ?",
              (f"{year}-{month:02d}",))
    total = c.fetchone()[0]
    conn.close()
    return total if total else 0

def get_budget():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='monthly_budget'")
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else 0

def set_budget(amount):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('monthly_budget', ?)", (str(amount),))
    conn.commit()
    conn.close()

def set_category_limit(category, amount):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    key = f"limit_{category}"
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(amount)))
    conn.commit()
    conn.close()

def get_category_limit(category):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    key = f"limit_{category}"
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else None

def mark_category_unwanted(category, unwanted=True):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    key = f"unwanted_{category}"
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, "1" if unwanted else "0"))
    conn.commit()
    conn.close()

def is_category_unwanted(category):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    key = f"unwanted_{category}"
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row and row[0] == "1"

def set_block_mode(enabled: bool):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('block_mode', ?)", ( "1" if enabled else "0",))
    conn.commit()
    conn.close()

def get_block_mode() -> bool:
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='block_mode'")
    row = c.fetchone()
    conn.close()
    return row and row[0] == "1"

def get_month_spent_by_category(year, month, category):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""SELECT SUM(amount) FROM expenses 
                 WHERE strftime('%Y-%m', date)=? AND category=?""",
              (f"{year}-{month:02d}", category))
    total = c.fetchone()[0]
    conn.close()
    return total if total else 0

def projected_month_end_spend(year, month):
    today = datetime.date.today()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM expenses WHERE strftime('%Y-%m', date)=?", (f"{year}-{month:02d}",))
    spent = c.fetchone()[0] or 0
    conn.close()
    days_in_month = calendar.monthrange(year, month)[1]
    if today.year == year and today.month == month:
        day = today.day
    else:
        day = days_in_month
    if day == 0:
        return spent
    projected = (spent / day) * days_in_month
    return projected

def recommend_actions_for_month(year, month):
    budget = get_budget()
    spent = get_total_expenses_for_month(year, month)
    proj = projected_month_end_spend(year, month)
    suggestions = []
    if budget > 0:
        need_to_save = max(0, proj - budget)
    else:
        need_to_save = 0
    if need_to_save > 0:
        suggestions.append(f"Projected overshoot: ₹{need_to_save:.0f}. Try to cut this month by ₹{need_to_save:.0f}.")
        conn = sqlite3.connect(DB); c = conn.cursor()
        c.execute("""SELECT category, SUM(amount) FROM expenses WHERE strftime('%Y-%m', date)=?
                     GROUP BY category ORDER BY SUM(amount) DESC LIMIT 5""", (f"{year}-{month:02d}",))
        tops = c.fetchall(); conn.close()
        for cat, amt in tops:
            suggestions.append(f"Top: {cat} — spent ₹{amt:.0f}. Consider cutting 20-40% from {cat}.")
    else:
        suggestions.append("You're on track — projected spending is within budget. Consider adding to savings.")
    conn = sqlite3.connect(DB); c = conn.cursor()
    c.execute("""SELECT key FROM settings WHERE key LIKE 'unwanted_%' AND value='1'""")
    unwanted_keys = c.fetchall(); conn.close()
    for (k,) in unwanted_keys:
        cat = k.replace("unwanted_", "")
        cat_spent = get_month_spent_by_category(year, month, cat)
        if cat_spent > 0:
            suggestions.append(f"Unwanted category {cat} already has ₹{cat_spent:.0f} this month. Avoid further purchases in this category.")
    return suggestions

# ---------------- Export helpers ----------------
def export_to_excel_bytes(expenses):
    wb = Workbook()
    ws = wb.active
    ws.title = "Expenses"
    headers = ["ID", "Amount", "Category", "Description", "Date"]
    ws.append(headers)
    for row in expenses:
        ws.append(row)
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio

def export_to_pdf_bytes(expenses):
    bio = io.BytesIO()
    c = canvas.Canvas(bio, pagesize=letter)
    width, height = letter
    y = height - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(200, y, "Expense Report")
    y -= 30
    c.setFont("Helvetica", 10)
    headers = ["ID", "Amount", "Category", "Description", "Date"]
    c.drawString(30, y, " | ".join(headers))
    y -= 20
    for row in expenses:
        line = " | ".join([str(x) for x in row])
        c.drawString(30, y, line[:100])
        y -= 15
        if y < 50:
            c.showPage()
            y = height - 50
    c.save()
    bio.seek(0)
    return bio

# ---------------- API Routes ----------------
CATEGORIES = ["Food", "Travel", "Shopping", "Bills", "Medical", "Trip", "Dress", "Cosmetics", "JunkFood", "Other"]

@app.route("/")
def index():
    init_db()
    return render_template("index.html", categories=CATEGORIES)

@app.route("/api/expenses", methods=["GET", "POST"])
def api_expenses():
    if request.method == "GET":
        # support filters via query params
        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")
        category = request.args.get("category")
        filters = {}
        if from_date: filters["from_date"] = from_date
        if to_date: filters["to_date"] = to_date
        if category: filters["category"] = category
        rows = fetch_expenses(filters)
        # convert to list of dicts
        data = [{"id": r[0], "amount": r[1], "category": r[2], "description": r[3], "date": r[4]} for r in rows]
        return jsonify(data)
    else:
        # add expense
        payload = request.json
        try:
            amount = float(payload.get("amount", 0))
            if amount <= 0:
                return jsonify({"error":"invalid amount"}), 400
        except:
            return jsonify({"error":"invalid amount"}), 400
        date = payload.get("date")
        try:
            datetime.datetime.strptime(date, "%Y-%m-%d")
        except:
            return jsonify({"error":"invalid date"}), 400
        category = payload.get("category")
        desc = payload.get("description","")

        # check before add (preserve original logic)
        y, m, _ = map(int, date.split("-"))
        cat_limit = get_category_limit(category)
        cat_spent = get_month_spent_by_category(y, m, category)
        if cat_limit is not None and (cat_spent + amount) > cat_limit:
            # return a specific status so frontend can choose to confirm override
            return jsonify({"warning":"category_limit_exceeded", "limit":cat_limit, "current_spent":cat_spent}), 200

        if is_category_unwanted(category) and get_block_mode():
            return jsonify({"error":"category_blocked"}), 403

        budget = get_budget()
        spent = get_total_expenses_for_month(y, m)
        new_spent = spent + amount
        if budget > 0 and new_spent > budget:
            return jsonify({"warning":"budget_exceeded", "budget":budget, "spent":spent}), 200

        add_expense(amount, category, desc, date)
        return jsonify({"ok":True}), 201

@app.route("/api/expenses/force_add", methods=["POST"])
def api_expenses_force_add():
    # Force-add even if warnings existed (for frontend confirm override)
    payload = request.json
    amount = float(payload.get("amount", 0))
    date = payload.get("date")
    category = payload.get("category")
    desc = payload.get("description","")
    add_expense(amount, category, desc, date)
    return jsonify({"ok":True}), 201

@app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
def api_delete(expense_id):
    delete_expense(expense_id)
    return jsonify({"ok":True})

@app.route("/api/settings", methods=["GET"])
def api_settings():
    # return budget, block mode, category limits, unwanted flags
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT key, value FROM settings")
    rows = c.fetchall()
    conn.close()
    out = {}
    for k,v in rows:
        out[k] = v
    return jsonify(out)

@app.route("/api/set_budget", methods=["POST"])
def api_set_budget():
    payload = request.json
    try:
        amt = float(payload.get("budget", 0))
        set_budget(amt)
        return jsonify({"ok":True})
    except:
        return jsonify({"error":"invalid"}), 400

@app.route("/api/set_category_limit", methods=["POST"])
def api_set_category_limit():
    payload = request.json
    cat = payload.get("category")
    try:
        amt = float(payload.get("limit", 0))
        set_category_limit(cat, amt)
        return jsonify({"ok":True})
    except:
        return jsonify({"error":"invalid"}), 400

@app.route("/api/mark_unwanted", methods=["POST"])
def api_mark_unwanted():
    payload = request.json
    cat = payload.get("category")
    unw = payload.get("unwanted", False)
    mark_category_unwanted(cat, bool(unw))
    return jsonify({"ok":True})

@app.route("/api/toggle_block", methods=["POST"])
def api_toggle_block():
    payload = request.json
    enabled = bool(payload.get("enabled", False))
    set_block_mode(enabled)
    return jsonify({"ok":True})

@app.route("/api/suggestions", methods=["GET"])
def api_suggestions():
    today = datetime.date.today()
    s = recommend_actions_for_month(today.year, today.month)
    return jsonify(s)

@app.route("/api/export/excel")
def export_excel():
    expenses = fetch_expenses()
    if not expenses:
        return ("", 204)
    bio = export_to_excel_bytes(expenses)
    return send_file(bio, as_attachment=True, download_name="expenses.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/api/export/pdf")
def export_pdf():
    expenses = fetch_expenses()
    if not expenses:
        return ("", 204)
    bio = export_to_pdf_bytes(expenses)
    return send_file(bio, as_attachment=True, download_name="expenses.pdf", mimetype="application/pdf")

@app.route("/api/chart/category_pie")
def api_chart_category_pie():
    # return data for chart.js: labels & values for current month
    today = datetime.date.today()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""SELECT category, SUM(amount) FROM expenses
                 WHERE strftime('%Y-%m', date)=? GROUP BY category""",
              (today.strftime("%Y-%m"),))
    data = c.fetchall()
    conn.close()
    labels = [r[0] for r in data]
    values = [r[1] for r in data]
    return jsonify({"labels": labels, "values": values})

@app.route("/api/chart/monthly_trend")
def api_chart_monthly_trend():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""SELECT strftime('%Y-%m', date) as month, SUM(amount) 
                 FROM expenses GROUP BY month ORDER BY month DESC LIMIT 6""")
    data = c.fetchall()
    conn.close()
    months = [r[0] for r in reversed(data)]
    totals = [r[1] for r in reversed(data)]
    return jsonify({"months": months, "totals": totals})

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
