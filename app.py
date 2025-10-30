# --- Imports ---
import os
from functools import wraps
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    send_from_directory,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import text
import datetime

# --- App & DB Configuration ---
app = Flask(
    __name__,
    template_folder=".",
    static_folder=".",
)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "uvuhweuiwenfiu7y24hfn2j4c")

default_db_url = "postgresql://postgres:03092006@127.0.0.1:5432/yoga_db"
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", default_db_url)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# --- Uploads & Security Configuration ---
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

ADMIN_PASSWORD_HASH = generate_password_hash("pawar@yoga")

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Database Helper Functions ---
def fetch_all_products():
    result = db.session.execute(text("SELECT * FROM products ORDER BY id DESC"))
    return result.mappings().all()

def fetch_all_gallery_items():
    result = db.session.execute(text("SELECT * FROM gallery ORDER BY id DESC"))
    return result.mappings().all()

def fetch_all_requests():
    result = db.session.execute(text(
        "SELECT * FROM consultation_requests ORDER BY CASE WHEN status = 'pending' THEN 1 ELSE 2 END, requested_on DESC"
    ))
    return result.mappings().all()

# --- Auth Decorator ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return decorated_function

# --- Frontend Routes ---
@app.route("/")
def home():
    products = fetch_all_products()
    return render_template("index.html", products=products)

@app.route("/gallery")
def gallery_page():
    gallery_items = fetch_all_gallery_items()
    return render_template("gallery.html", gallery_items=gallery_items)

@app.route("/about")
def about_page():
    return render_template("about.html")

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# --- Admin Auth Routes ---
@app.route("/admin_login", methods=["POST"])
def admin_login():
    password = request.json.get("password")
    if password and check_password_hash(ADMIN_PASSWORD_HASH, password):
        session["admin_logged_in"] = True
        return jsonify({"success": True, "redirect": url_for("admin_panel")})
    else:
        session["admin_logged_in"] = False
        return jsonify({"success": False, "message": "Incorrect Password"})

@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("home"))

# --- Main Admin Panel ---
@app.route("/admin")
@admin_required
def admin_panel():
    products = fetch_all_products()
    gallery_items = fetch_all_gallery_items()
    requests = fetch_all_requests() 
    
    message = session.pop("message", None)
    message_type = session.pop("message_type", None)

    return render_template(
        "admin.html",
        products=products,
        gallery_items=gallery_items,
        requests=requests, 
        message=message,
        message_type=message_type,
    )

# --- Product Management Routes ---
@app.route("/add_product", methods=["POST"])
@admin_required
def add_product():
    name = request.form["name"]
    description = request.form["description"]
    price = request.form.get("price", 0.0)

    if "image" not in request.files or request.files["image"].filename == "":
        session["message"] = "No selected file"
        session["message_type"] = "error"
        return redirect(url_for("admin_panel"))

    file = request.files["image"]
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        try:
            sql = text("INSERT INTO products (name, description, price, image_filename) VALUES (:name, :description, :price, :filename)")
            db.session.execute(sql, {"name": name, "description": description, "price": price, "filename": filename})
            db.session.commit()
            
            session["message"] = f"Product '{name}' added successfully!"
            session["message_type"] = "success"
        except Exception as e:
            db.session.rollback()
            session["message"] = f"Database error: {str(e)}"
            session["message_type"] = "error"
            app.logger.error(f"Error adding product: {e}")
            
    else:
        session["message"] = "File type not allowed"
        session["message_type"] = "error"

    return redirect(url_for("admin_panel"))

@app.route("/delete_product/<int:id>", methods=["POST"])
@admin_required
def delete_product(id):
    product = db.session.execute(text("SELECT image_filename FROM products WHERE id = :id"), {"id": id}).mappings().fetchone()
    
    if product:
        try:
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], product["image_filename"]))
        except OSError as e:
            app.logger.error(f"Error deleting file: {e.filename} - {e.strerror}")
            
        try:
            db.session.execute(text("DELETE FROM products WHERE id = :id"), {"id": id})
            db.session.commit()
            session["message"] = f"Product ID {id} has been deleted."
            session["message_type"] = "success"
        except Exception as e:
            db.session.rollback()
            session["message"] = f"Database error during deletion: {str(e)}"
            session["message_type"] = "error"
            app.logger.error(f"Error deleting product from DB: {e}")
    else:
        session["message"] = f"Product ID {id} not found."
        session["message_type"] = "error"
        
    return redirect(url_for("admin_panel"))

# --- Gallery Management Routes ---
@app.route("/add_gallery_image", methods=["POST"])
@admin_required
def add_gallery_image():
    title = request.form["title"]
    category = request.form.get("category", "all")

    if "image" not in request.files or request.files["image"].filename == "":
        session["message"] = "No image file selected"
        session["message_type"] = "error"
        return redirect(url_for("admin_panel"))

    file = request.files["image"]
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        try:
            sql = text("INSERT INTO gallery (title, image_filename, category) VALUES (:title, :filename, :category)")
            db.session.execute(sql, {"title": title, "filename": filename, "category": category})
            db.session.commit()

            session["message"] = "Gallery image added successfully!"
            session["message_type"] = "success"
        except Exception as e:
            db.session.rollback()
            session["message"] = f"Database error: {str(e)}"
            session["message_type"] = "error"
            app.logger.error(f"Error adding gallery image: {e}")
            
    else:
        session["message"] = "File type not allowed"
        session["message_type"] = "error"

    return redirect(url_for("admin_panel"))

@app.route("/delete_gallery_image/<int:id>", methods=["POST"])
@admin_required
def delete_gallery_image(id):
    item = db.session.execute(text("SELECT image_filename FROM gallery WHERE id = :id"), {"id": id}).mappings().fetchone()
    
    if item:
        try:
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], item["image_filename"]))
        except OSError as e:
            app.logger.error(f"Error deleting file: {e.filename} - {e.strerror}")

        try:
            db.session.execute(text("DELETE FROM gallery WHERE id = :id"), {"id": id})
            db.session.commit()
            session["message"] = f"Gallery image ID {id} has been deleted."
            session["message_type"] = "success"
        except Exception as e:
            db.session.rollback()
            session["message"] = f"Database error during deletion: {str(e)}"
            session["message_type"] = "error"
            app.logger.error(f"Error deleting gallery image from DB: {e}")
            
    else:
        session["message"] = f"Gallery image ID {id} not found."
        session["message_type"] = "error"

    return redirect(url_for("admin_panel"))

# --- Consultation Request API ---
@app.route("/submit_consultation", methods=["POST"])
def submit_consultation():
    try:
        data = request.json
        name = data.get("name")
        contact = data.get("contact")
        notes = data.get("notes", "")

        if not name or not contact:
            return jsonify({"success": False, "message": "Name and Contact are required."}), 400

        sql = text("INSERT INTO consultation_requests (name, contact, notes, status) VALUES (:name, :contact, :notes, 'pending')")
        db.session.execute(sql, {"name": name, "contact": contact, "notes": notes})
        db.session.commit()
        
        return jsonify({"success": True, "message": "Request submitted successfully."})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error submitting consultation: {e}")
        return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500

# --- Consultation Request Handling (Admin) ---
@app.route("/handle_request/<string:action>/<int:id>", methods=["POST"])
@admin_required
def handle_request(action, id):
    new_status = 'pending'
    if action == 'accept':
        new_status = 'accepted'
    elif action == 'reject':
        new_status = 'rejected'
    else:
        session["message"] = "Invalid action."
        session["message_type"] = "error"
        return redirect(url_for("admin_panel"))

    try:
        sql = text("UPDATE consultation_requests SET status = :status WHERE id = :id")
        db.session.execute(sql, {"status": new_status, "id": id})
        db.session.commit()
        session["message"] = f"Request ID {id} has been {new_status}."
        session["message_type"] = "success"
    except Exception as e:
        db.session.rollback()
        session["message"] = f"Database error: {str(e)}"
        session["message_type"] = "error"
        app.logger.error(f"Error updating request status: {e}")

    return redirect(url_for("admin_panel"))

# --- Run App ---
if __name__ == "__main__":
   app.run(debug=True)