import os
from datetime import timedelta, datetime
from functools import wraps
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from flask import Flask, flash, g, redirect, render_template, request, session, url_for, abort
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)

secret = os.getenv("SECRET_KEY")
if not secret and not app.debug:
    raise RuntimeError("SECRET_KEY обязателен для запуска")
app.secret_key = secret or "dev-secret-key"

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db_url = os.getenv("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL не найдена в переменных окружения (.env)")

db_pool = ThreadedConnectionPool(1, 5, db_url, sslmode="require")

def get_db():
    if "db" not in g:
        g.db = db_pool.getconn()
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db_pool.putconn(db)


def query_db(query, args=(), one=False, commit=False, returning=False):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, args)
        
            result = None
            if returning or not commit:
                rows = cur.fetchall()
                dict_rows = [dict(row) for row in rows]
                result = (dict_rows[0] if dict_rows else None) if one else dict_rows

            if commit:
                conn.commit()

            return result
    except Exception:
        if conn:
            conn.rollback()
        raise

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            flash("Пожалуйста, войдите в аккаунт.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/")
@login_required
def index():
    user_id = session.get("user_id")
    active_tab = request.args.get("tab", "task")
    if active_tab not in ["task", "forecast"]:
        active_tab = "task"

    status_filter = request.args.get("status", "all")

    query = """
        SELECT i.*, c.name AS category_name, c.color AS category_color
        FROM items i
        LEFT JOIN categories c ON i.category_id = c.id
        WHERE i.user_id = %s AND i.type = %s
    """
    params = [user_id, active_tab]

    if status_filter == "pending":
        query += " AND i.status = 'pending'"
    elif status_filter == "completed":
        query += " AND i.status = 'completed'"

    query += " ORDER BY i.created_at DESC"

    items_raw = query_db(query, tuple(params))
    items = items_raw if isinstance(items_raw, list) else []

    # Считаем счетчики для бейджей табов
    counts_raw = query_db(
        """
        SELECT type, COUNT(*) as count 
        FROM items 
        WHERE user_id = %s AND status = 'pending'
        GROUP BY type
        """,
        (user_id,)
    )
    counts_list = counts_raw if isinstance(counts_raw, list) else []
    counts_map = {row["type"]: row["count"] for row in counts_list}

    return render_template(
        "index.html",
        items=items,
        active_tab=active_tab,
        status_filter=status_filter,
        counts_map=counts_map
    )

@app.route("/login", methods=["POST", "GET"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Заполните все поля.", "danger")
            return render_template("login.html", is_register=False)

        user = query_db(
            "SELECT * FROM users WHERE username = %s",
            (username,),
            one=True
        )

        if not user or not check_password_hash(user["password_hash"], password): # type: ignore
            flash("Неверное имя пользователя или пароль.", "danger")
            return render_template("login.html", is_register=False)

        session.clear()
        session.permanent = True
        session["user_id"] = user["id"] # type: ignore
        session["username"] = user["username"] # type: ignore

        flash(f"С возвращением, {user['username']}!", "success") # type: ignore
        return redirect(url_for("index"))
        
    return render_template("login.html", is_register=False)

@app.route("/logout")
def logout():
    session.clear()
    flash("Вы успешно вышли.", "info")
    return redirect(url_for("login"))


@app.route("/register", methods=["POST", "GET"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")

        if not username:
            flash("Введите имя пользователя.", "danger")
            return render_template("login.html", is_register=True)
        if not password:
            flash("Введите пароль.", "danger")
            return render_template("login.html", is_register=True)
        if password != confirmation:
            flash("Пароли не совпадают.", "danger")
            return render_template("login.html", is_register=True)

        existing_user = query_db(
            "SELECT id FROM users WHERE username = %s", (username,),
            one=True
        )

        if existing_user:
            flash("Пользователь с таким именем уже существует.", "warning")
            return render_template("login.html", is_register=True)

        pwd_hash = generate_password_hash(password)
        new_user = query_db(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
            (username, pwd_hash),
            one=True,
            commit=True,
            returning=True
        )

        if not new_user:
            flash("Ошибка при регистрации пользователя.", "danger")
            return render_template("login.html", is_register=True)
        
        session.clear()
        session.permanent = True
        session["user_id"] = new_user["id"] # type: ignore
        session["username"] = username

        flash(f"Добро пожаловать, {username}!", "success")
        return redirect(url_for("index"))
    
    return render_template("login.html", is_register=True)


@app.route("/create", methods=["GET", "POST"])
@login_required
def create():
    user_id = session["user_id"]

    if request.method == "POST":
        item_type = request.form.get("type", "").strip()
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        target_date_raw = request.form.get("target_date", "").strip()
        target_condition = request.form.get("target_condition", "").strip()
        category_name = request.form.get("category_name", "").strip()

        if item_type not in ["task", "forecast"]:
           flash("Некорректный тип записи.", "danger")
           return redirect(url_for("create"))
        if not title:
            flash("Укажите название.", "danger")
            return redirect(url_for("create"))

        target_date = None
        if target_date_raw:
            try:
                target_date = datetime.fromisoformat(target_date_raw)
            except ValueError:
                flash("Неверный формат даты.", "danger")
                return redirect(url_for("create"))

        category_id = None
        if category_name:
            cat = query_db(
                "SELECT id FROM categories WHERE user_id = %s AND LOWER(name) = LOWER(%s)",
                (user_id, category_name),
                one=True
            )
            if cat:
                category_id = cat["id"] # type: ignore
            else:
                new_cat = query_db(
                    "INSERT INTO categories (user_id, name) VALUES (%s, %s) RETURNING id",
                    (user_id, category_name),
                    one=True,
                    commit=True,
                    returning=True
                )
                category_id = new_cat["id"] # type: ignore

        query_db(
                    """
                    INSERT INTO items(
                    user_id, category_id, type, title, description, target_date, target_condition, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                    """,
                    (user_id, category_id, item_type, title, description or None, target_date, target_condition or None),
                    commit=True
                )
        flash(
            f"{'Задача' if item_type == 'task' else 'Прогноз'} успешно создана!", 
            "success"
        )
        return redirect(url_for("index", tab=item_type))

    categories = query_db(
        "SELECT * FROM categories WHERE user_id = %s ORDER BY name ASC",
        (user_id,)
    )

    return render_template("create.html", categories=categories)

@app.route("/item/<int:item_id>", methods=["GET", "POST"])
@login_required
def item_detail(item_id):
    user_id = session["user_id"]
    item = query_db(
        """
        SELECT i.*, c.name AS category_name
        FROM items i
        LEFT JOIN categories c ON i.category_id = c.id
        WHERE i.id = %s AND i.user_id = %s
        """,
        (item_id, user_id),
        one=True
    )
    if not item:
        abort(404)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        target_condition = request.form.get("target_condition", "").strip()
        target_date_raw = request.form.get("target_date", "").strip()

        if not title:
            flash("Название не может быть пустым.", "danger")
            return redirect(url_for("item_detail", item_id=item_id))

        target_date = None
        if target_date_raw:
            try:
                target_date = datetime.fromisoformat(target_date_raw)
            except ValueError:
                flash("Неверный формат даты.", "danger")
                return redirect(url_for("item_detail", item_id=item_id))

        query_db(
            """
            UPDATE items
            SET title = %s, description = %s, target_condition = %s, target_date = %s
            WHERE id = %s AND user_id = %s
            """,
            (title, description or None, target_condition or None, target_date, item_id, user_id),
            commit=True
        )
        flash("Изменения сохранены.", "success")
        return redirect(url_for("item_detail", item_id=item_id))
    return render_template("item.html", item=item)

@app.route("/item/<int:item_id>/status", methods=["POST"])
@login_required
def update_status(item_id):
    user_id = session["user_id"]
    new_status = request.form.get("status")

    if new_status not in ["pending", "completed", "failed", "cancelled"]:
        flash("Некорректный статус.", "danger")
        return redirect(url_for("item_detail", item_id=item_id))

    completed_at = datetime.now() if new_status in ["completed", "failed"] else None

    query_db(
        """
        UPDATE items
        SET status = %s, completed_at = %s
        WHERE id = %s AND user_id = %s
        """,
        (new_status, completed_at, item_id, user_id),
        commit=True
    )
    flash("Статус успешно обновлен.", "success")
    return redirect(url_for("item_detail", item_id=item_id))

@app.route("/item/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    user_id = session["user_id"]

    item = query_db("SELECT type FROM items WHERE id = %s AND user_id = %s",
                    (item_id, user_id), one=True)

    if not item:
        abort(404)

    query_db("DELETE FROM items WHERE id = %s AND user_id = %s", (item_id, user_id), commit=True)
    flash("Запись удалена.", "info")
    return redirect(url_for("index", tab=item["type"])) #type: ignore

@app.route("/stats")
@login_required
def stats():
    user_id = session["user_id"]

    raw_stats = query_db(
        """
        SELECT type, status, COUNT(*) as count
        FROM items
        WHERE user_id = %s
        GROUP BY type, status
        """,
        (user_id,),
    )
    stats_list = raw_stats if isinstance(raw_stats, list) else []

    data = {
        "task": {"total": 0, "completed": 0, "pending": 0, "failed": 0, "cancelled": 0},
        "forecast": {"total": 0, "completed": 0, "pending": 0, "failed": 0}
    }
    for row in stats_list:
        t = row["type"]
        s = row["status"]
        if t in data and s in data[t]:
            data[t][s] = row["count"]
            data[t]["total"] += row["count"]

    task_rate = round((data["task"]["completed"] / data["task"]["total"] * 100), 1) if data["task"]["total"] > 0 else 0
    forecast_rate = round((data["forecast"]["completed"] / data["forecast"]["total"] * 100), 1) if data["forecast"]["total"] > 0 else 0

    cat_stats = query_db(
        """
        SELECT COALESCE(c.name, 'Без категории') AS category_name, COUNT(i.id) AS total_items
        FROM items i
        LEFT JOIN categories c ON i.category_id = c.id
        WHERE i.user_id = %s
        GROUP BY c.name
        ORDER BY total_items DESC
        """,
        (user_id,)
    )
    categories_summary = cat_stats if isinstance(cat_stats, list) else []

    return render_template(
        "stats.html",
        data=data,
        task_rate=task_rate,
        forecast_rate=forecast_rate,
        categories_summary=categories_summary
    )

if __name__ == "__main__":

    app.run(debug=True)