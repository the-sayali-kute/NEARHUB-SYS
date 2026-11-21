from datetime import date, timedelta
import os
import uuid
from decimal import Decimal, InvalidOperation
from functools import wraps
from ai_recommender import recommend_hostels
from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    abort,
)
from flask_login import (
    login_user,
    logout_user,
    login_required,
    current_user,
)
from sqlalchemy import or_
from werkzeug.utils import secure_filename
from PIL import Image, UnidentifiedImageError

from config import Config
from extensions import db, login_manager
from models import (
    User,
    Hostel,
    Booking,
    Mess,
    MenuItem,
    MealPlan,
    Subscription,
    Review,
    Notification,
    HostelPhoto,
)


def role_required(*roles):
    def decorator(view_function):
        @wraps(view_function)
        @login_required
        def wrapped_view(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)

            return view_function(*args, **kwargs)

        return wrapped_view

    return decorator


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    os.makedirs(app.config["HOSTEL_UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    # ---------------------------------------------------------
    # HELPER FUNCTIONS
    # ---------------------------------------------------------

    def get_decimal(value, field_name, default=None):
        value = (value or "").strip()

        if value == "" and default is not None:
            return Decimal(str(default))

        try:
            number = Decimal(value)
        except (InvalidOperation, ValueError):
            raise ValueError(f"Please enter a valid {field_name}.")

        if not number.is_finite():
            raise ValueError(f"Please enter a valid {field_name}.")

        return number

    def get_integer(value, field_name, default=None):
        value = (value or "").strip()

        if value == "" and default is not None:
            return int(default)

        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Please enter a valid {field_name}.")

    def get_required_text(field_name):
        value = request.form.get(field_name, "").strip()

        if not value:
            raise ValueError(f"{field_name.replace('_', ' ').title()} is required.")

        return value

    # ---------------------------------------------------------
    # HOSTEL PHOTO UPLOAD HELPERS
    # ---------------------------------------------------------
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
    MAX_PHOTOS_PER_HOSTEL = 5
    MAX_IMAGE_SIZE = 5 * 1024 * 1024

    def validate_hostel_photo_uploads(uploaded_files):
        valid_files = []
        for uploaded_file in uploaded_files:
            if not uploaded_file or not uploaded_file.filename:
                continue
            original_name = secure_filename(uploaded_file.filename)
            if not original_name or "." not in original_name:
                raise ValueError("One of the selected files has an invalid filename.")
            extension = original_name.rsplit(".", 1)[1].lower()
            if extension not in ALLOWED_IMAGE_EXTENSIONS:
                raise ValueError("Only JPG, JPEG, PNG and WEBP images are allowed.")
            uploaded_file.stream.seek(0, os.SEEK_END)
            file_size = uploaded_file.stream.tell()
            uploaded_file.stream.seek(0)
            if file_size <= 0:
                raise ValueError("An uploaded image is empty.")
            if file_size > MAX_IMAGE_SIZE:
                raise ValueError("Each hostel photo must be 5 MB or smaller.")
            image_format = None
            try:
                image = Image.open(uploaded_file.stream)
                image_format = image.format
                image.verify()
            except (UnidentifiedImageError, OSError, ValueError):
                raise ValueError("One of the selected files is not a valid image.")
            finally:
                uploaded_file.stream.seek(0)
            expected_formats = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}
            if image_format != expected_formats[extension]:
                raise ValueError("An image's file extension does not match its content.")
            valid_files.append((uploaded_file, extension))
        return valid_files

    def store_hostel_photos(hostel, validated_files):
        saved_paths = []
        try:
            for uploaded_file, extension in validated_files:
                filename = f"{uuid.uuid4().hex}.{extension}"
                destination = os.path.join(app.config["HOSTEL_UPLOAD_FOLDER"], filename)
                uploaded_file.save(destination)
                saved_paths.append(destination)
                db.session.add(
                    HostelPhoto(hostel_id=hostel.id, image_filename=filename)
                )
            return saved_paths
        except Exception:
            remove_saved_files(saved_paths)
            raise

    def remove_saved_files(file_paths):
        for file_path in file_paths:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError:
                app.logger.exception("Could not remove hostel image: %s", file_path)

    # ---------------------------------------------------------
    # GLOBAL NOTIFICATION COUNT
    # ---------------------------------------------------------

    @app.context_processor
    def inject_notifications():
        if current_user.is_authenticated:
            count = Notification.query.filter_by(
                user_id=current_user.id,
                is_read=False
            ).count()
        else:
            count = 0

        return {"unread_notifications": count}

    # ---------------------------------------------------------
    # HOME PAGE
    # ---------------------------------------------------------

    @app.route("/")
    def index():
        hostels = (
            Hostel.query
            .filter_by(active=True)
            .order_by(Hostel.created_at.desc())
            .limit(6)
            .all()
        )

        messes = (
            Mess.query
            .filter_by(active=True)
            .order_by(Mess.id.desc())
            .limit(6)
            .all()
        )

        return render_template(
            "index.html",
            hostels=hostels,
            messes=messes
        )

    # ---------------------------------------------------------
    # REGISTRATION
    # ---------------------------------------------------------

    @app.route("/register", methods=["GET", "POST"])
    def register():

        if request.method == "POST":

            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            phone = request.form.get("phone", "").strip()
            password = request.form.get("password", "")
            role = request.form.get("role", "")

            if not all([name, email, phone, password]):
                flash("Please complete all fields.", "danger")

            elif role not in (
                "student",
                "hostel_owner",
                "mess_owner"
            ):
                flash("Please choose a valid account type.", "danger")

            elif len(password) < 8:
                flash(
                    "Password must contain at least 8 characters.",
                    "danger"
                )

            elif User.query.filter(
                or_(
                    User.email == email,
                    User.phone == phone
                )
            ).first():
                flash(
                    "Email or phone number is already registered.",
                    "danger"
                )

            else:
                try:
                    user = User(
                        name=name,
                        email=email,
                        phone=phone,
                        role=role
                    )

                    user.set_password(password)

                    db.session.add(user)
                    db.session.commit()

                    login_user(user)

                    flash(
                        "Account created successfully.",
                        "success"
                    )

                    return redirect(url_for("dashboard"))

                except Exception:
                    db.session.rollback()
                    app.logger.exception("Registration failed.")
                    flash(
                        "Registration failed. Please try again.",
                        "danger"
                    )

        return render_template("register.html")

    # ---------------------------------------------------------
    # LOGIN
    # ---------------------------------------------------------

    @app.route("/login", methods=["GET", "POST"])
    def login():

        if request.method == "POST":

            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            role = request.form.get("role", "")

            user = User.query.filter_by(
                email=email,
                role=role
            ).first()

            if user and user.check_password(password):

                login_user(user)

                flash("Welcome back!", "success")

                return redirect(url_for("dashboard"))

            flash(
                "Invalid email, password, or account type.",
                "danger"
            )

        return render_template("login.html")

    # ---------------------------------------------------------
    # LOGOUT
    # ---------------------------------------------------------

    @app.route("/logout")
    @login_required
    def logout():

        logout_user()

        flash("You have been logged out.", "info")

        return redirect(url_for("index"))

    # ---------------------------------------------------------
    # ROLE-BASED DASHBOARD
    # ---------------------------------------------------------

    @app.route("/dashboard")
    @login_required
    def dashboard():

        # STUDENT DASHBOARD
        if current_user.role == "student":

            bookings = (
                Booking.query
                .filter_by(student_id=current_user.id)
                .order_by(Booking.created_at.desc())
                .all()
            )

            subscriptions = (
                Subscription.query
                .filter_by(student_id=current_user.id)
                .order_by(Subscription.created_at.desc())
                .all()
            )

            return render_template(
                "student/dashboard.html",
                bookings=bookings,
                subscriptions=subscriptions,
                today=date.today()
            )

        # HOSTEL OWNER DASHBOARD
        if current_user.role == "hostel_owner":

            hostels = Hostel.query.filter_by(
                owner_id=current_user.id
            ).all()

            hostel_ids = [hostel.id for hostel in hostels]

            if hostel_ids:
                bookings = (
                    Booking.query
                    .filter(Booking.hostel_id.in_(hostel_ids))
                    .order_by(Booking.created_at.desc())
                    .all()
                )
            else:
                bookings = []

            return render_template(
                "hostel_owner/dashboard.html",
                hostels=hostels,
                bookings=bookings
            )

        # MESS OWNER DASHBOARD
        if current_user.role == "mess_owner":

            messes = Mess.query.filter_by(
                owner_id=current_user.id
            ).all()

            mess_ids = [mess.id for mess in messes]

            if mess_ids:

                plans = (
                    MealPlan.query
                    .filter(MealPlan.mess_id.in_(mess_ids))
                    .all()
                )

                subscriptions = (
                    Subscription.query
                    .join(MealPlan)
                    .filter(MealPlan.mess_id.in_(mess_ids))
                    .order_by(Subscription.created_at.desc())
                    .all()
                )

            else:
                plans = []
                subscriptions = []

            return render_template(
                "mess_owner/dashboard.html",
                messes=messes,
                plans=plans,
                subscriptions=subscriptions
            )

        abort(403)

    # =========================================================
    # HOSTEL MODULE
    # =========================================================

    # ---------------------------------------------------------
    # VIEW AND SEARCH HOSTELS
    # ---------------------------------------------------------

    @app.route("/hostels")
    def hostels():

        query = Hostel.query.filter_by(active=True)

        locality = request.args.get("locality", "").strip()
        room_type = request.args.get("room_type", "").strip()
        max_rent = request.args.get("max_rent", "").strip()

        if locality:
            query = query.filter(
                Hostel.locality.ilike(f"%{locality}%")
            )

        if room_type:
            query = query.filter(
                Hostel.room_type == room_type
            )

        if max_rent:
            try:
                maximum = get_decimal(max_rent, "maximum rent")

                if maximum < 0:
                    raise ValueError("Maximum rent cannot be negative.")

                query = query.filter(Hostel.rent <= maximum)

            except ValueError as error:
                flash(str(error), "warning")

        hostel_list = query.order_by(Hostel.rent).all()

        return render_template(
            "hostels.html",
            hostels=hostel_list
        )


    # ---------------------------------------------------------
    # AI HOSTEL RECOMMENDATIONS
    # ---------------------------------------------------------

    @app.route("/ai-recommendations", methods=["GET", "POST"])
    @role_required("student")
    def ai_recommendations():

        recommendations = []
        preferences = {}

        if request.method == "POST":

            try:
                # Get student preferences
                locality = request.form.get(
                    "locality", ""
                ).strip()

                room_type = request.form.get(
                    "room_type", ""
                ).strip()

                gender_policy = request.form.get(
                    "gender_policy", ""
                ).strip()

                facilities = request.form.get(
                    "facilities", ""
                ).strip()

                college = request.form.get(
                    "college", ""
                ).strip()

                max_budget = get_decimal(
                    request.form.get("max_budget"),
                    "maximum monthly budget"
                )

                if max_budget <= 0:
                    raise ValueError(
                        "Maximum budget must be greater than zero."
                    )

                if not any([
                    locality,
                    room_type,
                    gender_policy,
                    facilities,
                    college
                ]):
                    raise ValueError(
                        "Please enter at least one hostel preference."
                    )

                preferences = {
                    "locality": locality,
                    "room_type": room_type,
                    "gender_policy": gender_policy,
                    "facilities": facilities,
                    "college": college,
                    "max_budget": max_budget
                }

                # Only consider active hostels within budget
                matching_hostels = (
                    Hostel.query
                    .filter_by(active=True)
                    .filter(Hostel.rent <= max_budget)
                    .all()
                )

                # Run the AI recommendation algorithm
                recommendations = recommend_hostels(
                    matching_hostels,
                    preferences
                )

                if not recommendations:
                    flash(
                        "No suitable hostels found. "
                        "Try changing your preferences.",
                        "warning"
                    )

            except ValueError as error:
                flash(str(error), "danger")

        return render_template(
            "ai_recommendations.html",
            recommendations=recommendations,
            preferences=preferences
        )



    # ---------------------------------------------------------
    # ADD NEW HOSTEL
    # ---------------------------------------------------------

    @app.route("/hostels/add", methods=["GET", "POST"])
    @role_required("hostel_owner")
    def add_hostel():
        if request.method == "POST":
            saved_paths = []
            try:
                total_rooms = get_integer(request.form.get("total_rooms"), "total number of rooms")
                available_rooms = get_integer(request.form.get("available_rooms"), "available rooms")
                if total_rooms < 1:
                    raise ValueError("Total rooms must be at least 1.")
                if available_rooms < 0 or available_rooms > total_rooms:
                    raise ValueError("Available rooms must be between 0 and total rooms.")
                rent = get_decimal(request.form.get("rent"), "rent")
                deposit = get_decimal(request.form.get("deposit"), "deposit", default=0)
                if rent < 0 or deposit < 0:
                    raise ValueError("Rent and deposit cannot be negative.")

                uploaded_files = validate_hostel_photo_uploads(request.files.getlist("hostel_photos"))
                if not uploaded_files:
                    raise ValueError("Please upload at least one hostel photo.")
                if len(uploaded_files) > MAX_PHOTOS_PER_HOSTEL:
                    raise ValueError("You can upload a maximum of 5 photos.")

                hostel = Hostel(
                    owner_id=current_user.id,
                    name=get_required_text("name"),
                    locality=get_required_text("locality"),
                    address=get_required_text("address"),
                    college=request.form.get("college", "").strip(),
                    rent=rent,
                    deposit=deposit,
                    room_type=request.form.get("room_type", "Shared"),
                    gender_policy=request.form.get("gender_policy", "Any"),
                    total_rooms=total_rooms,
                    available_rooms=available_rooms,
                    facilities=request.form.get("facilities", "").strip(),
                    description=request.form.get("description", "").strip(),
                    contact_phone=request.form.get("contact_phone", "").strip() or current_user.phone
                )
                db.session.add(hostel)
                db.session.flush()
                saved_paths = store_hostel_photos(hostel, uploaded_files)
                db.session.commit()
                flash("Hostel listing and photos published successfully!", "success")
                return redirect(url_for("dashboard"))
            except (ValueError, TypeError, ArithmeticError) as error:
                db.session.rollback()
                remove_saved_files(saved_paths)
                flash(str(error), "danger")
            except Exception:
                db.session.rollback()
                remove_saved_files(saved_paths)
                app.logger.exception("Adding hostel failed.")
                flash("Unable to publish hostel. Please check the details and try again.", "danger")
        return render_template("hostel_form.html", hostel=None)

    # ---------------------------------------------------------
    # VIEW HOSTEL DETAILS
    # ---------------------------------------------------------


    @app.route("/hostels/<int:hostel_id>")
    def hostel_detail(hostel_id):

        hostel = Hostel.query.filter_by(
            id=hostel_id,
            active=True
        ).first_or_404()

        reviews = (
            Review.query
            .filter_by(hostel_id=hostel.id)
            .order_by(Review.created_at.desc())
            .all()
        )

        can_review = False
        already_reviewed = False

        # Check eligibility only for logged-in students
        if current_user.is_authenticated and current_user.role == "student":

            can_review = Booking.query.filter_by(
                student_id=current_user.id,
                hostel_id=hostel.id,
                status="approved"
            ).first() is not None

            already_reviewed = Review.query.filter_by(
                student_id=current_user.id,
                hostel_id=hostel.id
            ).first() is not None

        return render_template(
            "hostel_detail.html",
            hostel=hostel,
            reviews=reviews,
            can_review=can_review,
            already_reviewed=already_reviewed,
            today=date.today().isoformat()
        )

    # ---------------------------------------------------------
    # EDIT EXISTING HOSTEL
    # ---------------------------------------------------------

    @app.route(
        "/hostels/<int:hostel_id>/edit",
        methods=["GET", "POST"]
    )
    @role_required("hostel_owner")
    def edit_hostel(hostel_id):
        hostel = Hostel.query.get_or_404(hostel_id)
        if hostel.owner_id != current_user.id:
            abort(403)

        if request.method == "POST":
            saved_paths = []
            files_to_remove_after_commit = []
            try:
                total_rooms = get_integer(request.form.get("total_rooms"), "total number of rooms")
                available_rooms = get_integer(request.form.get("available_rooms"), "available rooms")
                if total_rooms < 1:
                    raise ValueError("Total rooms must be at least 1.")
                if available_rooms < 0 or available_rooms > total_rooms:
                    raise ValueError("Available rooms cannot exceed total rooms.")
                rent = get_decimal(request.form.get("rent"), "rent")
                deposit = get_decimal(request.form.get("deposit"), "deposit", default=0)
                if rent < 0 or deposit < 0:
                    raise ValueError("Rent and deposit cannot be negative.")

                uploaded_files = validate_hostel_photo_uploads(request.files.getlist("hostel_photos"))
                delete_ids = {
                    int(value) for value in request.form.getlist("delete_photo_ids")
                    if value.isdigit()
                }
                photos_to_delete = [photo for photo in hostel.photos if photo.id in delete_ids]
                final_photo_count = len(hostel.photos) - len(photos_to_delete) + len(uploaded_files)
                if final_photo_count < 1:
                    raise ValueError("A hostel listing must have at least one photo.")
                if final_photo_count > MAX_PHOTOS_PER_HOSTEL:
                    raise ValueError("A hostel can have a maximum of 5 photos.")

                hostel.name = get_required_text("name")
                hostel.locality = get_required_text("locality")
                hostel.address = get_required_text("address")
                hostel.college = request.form.get("college", "").strip()
                hostel.rent = rent
                hostel.deposit = deposit
                hostel.room_type = request.form.get("room_type", "Shared")
                hostel.gender_policy = request.form.get("gender_policy", "Any")
                hostel.total_rooms = total_rooms
                hostel.available_rooms = available_rooms
                hostel.facilities = request.form.get("facilities", "").strip()
                hostel.description = request.form.get("description", "").strip()
                hostel.contact_phone = request.form.get("contact_phone", "").strip() or current_user.phone

                for photo in photos_to_delete:
                    files_to_remove_after_commit.append(
                        os.path.join(app.config["HOSTEL_UPLOAD_FOLDER"], photo.image_filename)
                    )
                    db.session.delete(photo)

                saved_paths = store_hostel_photos(hostel, uploaded_files)
                db.session.commit()
                remove_saved_files(files_to_remove_after_commit)
                flash("Hostel details and photos updated successfully!", "success")
                return redirect(url_for("hostel_detail", hostel_id=hostel.id))
            except (ValueError, TypeError, ArithmeticError) as error:
                db.session.rollback()
                remove_saved_files(saved_paths)
                flash(str(error), "danger")
            except Exception:
                db.session.rollback()
                remove_saved_files(saved_paths)
                app.logger.exception("Editing hostel failed.")
                flash("Unable to update hostel details. Please try again.", "danger")
        return render_template("hostel_form.html", hostel=hostel)

    # ---------------------------------------------------------
    # STUDENT SENDS HOSTEL BOOKING REQUEST
    # ---------------------------------------------------------

    @app.route("/book/<int:hostel_id>", methods=["POST"])
    @role_required("student")
    def book_hostel(hostel_id):

        hostel = Hostel.query.filter_by(
            id=hostel_id,
            active=True
        ).first_or_404()

        try:
            start_date = date.fromisoformat(
                request.form.get("start_date", "")
            )

            end_date = date.fromisoformat(
                request.form.get("end_date", "")
            )

            if start_date < date.today():
                raise ValueError("Start date cannot be in the past.")

            if end_date <= start_date:
                raise ValueError(
                    "End date must be after the start date."
                )

            if hostel.available_rooms <= 0:
                raise ValueError(
                    "This hostel currently has no available rooms."
                )

            booking = Booking(
                student_id=current_user.id,
                hostel_id=hostel.id,
                start_date=start_date,
                end_date=end_date
            )

            db.session.add(booking)

            db.session.add(
                Notification(
                    user_id=hostel.owner_id,
                    message=(
                        f"New hostel booking request for {hostel.name}."
                    )
                )
            )

            db.session.commit()

            flash(
                "Booking request sent. It is pending owner approval.",
                "success"
            )

        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")

        except Exception:
            db.session.rollback()
            app.logger.exception("Hostel booking request failed.")
            flash(
                "Unable to send booking request. Please try again.",
                "danger"
            )

        return redirect(
            url_for("hostel_detail", hostel_id=hostel.id)
        )

    # ---------------------------------------------------------
    # HOSTEL OWNER APPROVES OR REJECTS BOOKING
    # ---------------------------------------------------------
    @app.route(
        "/bookings/<int:booking_id>/decision",
        methods=["POST"]
    )
    @role_required("hostel_owner")
    def booking_decision(booking_id):

        booking = Booking.query.get_or_404(booking_id)

        if booking.hostel.owner_id != current_user.id:
            abort(403)

        decision = request.form.get("decision")

        if booking.status != "pending":
            flash("This booking has already been processed.", "warning")

        elif decision not in ("approved", "rejected"):
            flash("Invalid booking decision.", "danger")

        elif decision == "approved" and booking.hostel.available_rooms <= 0:
            flash("No rooms are currently available.", "danger")

        else:
            if decision == "approved":
                booking.hostel.available_rooms -= 1

            booking.status = decision
            booking.owner_reason = request.form.get("reason", "").strip()

            db.session.add(
                Notification(
                    user_id=booking.student_id,
                    message=f"Your booking for {booking.hostel.name} was {decision}."
                )
            )

            db.session.commit()

            flash(f"Booking {decision} successfully.", "success")

        return redirect(url_for("dashboard"))
    
    # =========================================================
    # MESS MODULE
    # =========================================================

    # ---------------------------------------------------------
    # VIEW AND SEARCH MESSES
    # ---------------------------------------------------------

    @app.route("/messes")
    def messes():

        query = Mess.query.filter_by(active=True)

        locality = request.args.get("locality", "").strip()
        food_type = request.args.get("food_type", "").strip()

        if locality:
            query = query.filter(
                Mess.locality.ilike(f"%{locality}%")
            )

        if food_type:
            query = query.filter(
                Mess.food_type == food_type
            )

        mess_list = query.order_by(Mess.name).all()

        return render_template(
            "messes.html",
            messes=mess_list
        )

    # ---------------------------------------------------------
    # ADD MESS LISTING
    # ---------------------------------------------------------

    @app.route("/messes/add", methods=["GET", "POST"])
    @role_required("mess_owner")
    def add_mess():

        if request.method == "POST":

            try:
                mess = Mess(
                    owner_id=current_user.id,
                    name=get_required_text("name"),
                    locality=get_required_text("locality"),
                    address=get_required_text("address"),
                    food_type=request.form.get("food_type", "Veg"),
                    opening_hours=request.form.get(
                        "opening_hours",
                        ""
                    ).strip(),
                    contact_phone=current_user.phone,
                    description=request.form.get(
                        "description",
                        ""
                    ).strip()
                )

                db.session.add(mess)
                db.session.commit()

                flash(
                    "Mess listing published successfully.",
                    "success"
                )

                return redirect(url_for("dashboard"))

            except Exception:
                db.session.rollback()
                app.logger.exception("Adding mess failed.")
                flash(
                    "Unable to publish mess listing. Please try again.",
                    "danger"
                )

        return render_template("mess_form.html")

    # ---------------------------------------------------------
    # VIEW MESS DETAILS, MENUS AND PLANS
    # ---------------------------------------------------------

    @app.route("/messes/<int:mess_id>")
    def mess_detail(mess_id):

        mess = Mess.query.filter_by(
            id=mess_id,
            active=True
        ).first_or_404()

        plans = MealPlan.query.filter_by(
            mess_id=mess.id,
            active=True
        ).all()

        menus = MenuItem.query.filter_by(
            mess_id=mess.id,
            menu_date=date.today()
        ).all()

        reviews = (
            Review.query
            .filter_by(mess_id=mess.id)
            .order_by(Review.created_at.desc())
            .all()
        )

        can_review = False
        already_reviewed = False

        # Check eligibility only for logged-in students
        if current_user.is_authenticated and current_user.role == "student":

            can_review = (
                Subscription.query
                .join(MealPlan)
                .filter(
                    Subscription.student_id == current_user.id,
                    MealPlan.mess_id == mess.id,
                    Subscription.status == "approved"
                )
                .first() is not None
            )

            already_reviewed = Review.query.filter_by(
                student_id=current_user.id,
                mess_id=mess.id
            ).first() is not None

        return render_template(
            "mess_detail.html",
            mess=mess,
            plans=plans,
            menus=menus,
            reviews=reviews,
            can_review=can_review,
            already_reviewed=already_reviewed,
            today=date.today().isoformat()
        )

    # ---------------------------------------------------------
    # MESS OWNER ADDS MENU ITEM
    # ---------------------------------------------------------


    # ---------------------------------------------------------
    # MESS OWNER ADDS MENU ITEM
    # ---------------------------------------------------------

    @app.route(
        "/messes/<int:mess_id>/menu",
        methods=["POST"]
    )
    @role_required("mess_owner")
    def add_menu(mess_id):

        mess = Mess.query.get_or_404(mess_id)

        if mess.owner_id != current_user.id:
            abort(403)

        try:
            # Validate menu date
            menu_date_value = request.form.get("menu_date", "").strip()

            if not menu_date_value:
                raise ValueError("Please select a menu date.")

            try:
                menu_date = date.fromisoformat(menu_date_value)
            except ValueError:
                raise ValueError("Please enter a valid menu date.")

            if menu_date < date.today():
                raise ValueError("You cannot add menu items for past dates.")

            # Validate meal category
            meal_type = request.form.get(
                "meal_type", ""
            ).strip()

            allowed_meal_types = (
                "Breakfast",
                "Lunch",
                "Snacks",
                "Dinner"
            )

            if meal_type not in allowed_meal_types:
                raise ValueError("Please select a valid meal category.")

            # Validate food item
            item_name = get_required_text("item_name")

            if len(item_name) > 255:
                raise ValueError("Food item name cannot exceed 255 characters.")

            # Validate price
            price = get_decimal(
                request.form.get("price"),
                "menu item price",
                default=0
            )

            if price < 0:
                raise ValueError("Menu item price cannot be negative.")

            # Create menu item
            item = MenuItem(
                mess_id=mess.id,
                menu_date=menu_date,
                meal_type=meal_type,
                item_name=item_name,
                price=price
            )

            db.session.add(item)
            db.session.commit()

            flash("Menu item added successfully!", "success")

        except (ValueError, TypeError, ArithmeticError) as error:
            db.session.rollback()
            flash(str(error), "danger")

        except Exception:
            db.session.rollback()
            app.logger.exception("Adding menu item failed.")

            flash(
                "Unable to add menu item. Please try again.",
                "danger"
            )

        return redirect(
            url_for("mess_detail", mess_id=mess.id)
        )


    # ---------------------------------------------------------
    # MESS OWNER UPDATES MENU ITEM AVAILABILITY
    # ---------------------------------------------------------

    @app.route(
        "/menu-items/<int:item_id>/availability",
        methods=["POST"]
    )
    @role_required("mess_owner")
    def update_menu_availability(item_id):

        item = MenuItem.query.get_or_404(item_id)
        mess = Mess.query.get_or_404(item.mess_id)

        # Ensure this menu item belongs to the logged-in owner
        if mess.owner_id != current_user.id:
            abort(403)

        try:
            availability = request.form.get("is_available", "").strip()

            if availability not in ("0", "1"):
                raise ValueError("Invalid availability status.")

            item.is_available = (availability == "1")

            db.session.commit()

            status = "Available" if item.is_available else "Sold Out"

            flash(
                f"{item.item_name} marked as {status}.",
                "success"
            )

        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")

        except Exception:
            db.session.rollback()
            app.logger.exception("Updating menu availability failed.")
            flash(
                "Unable to update menu availability. Please try again.",
                "danger"
            )

        return redirect(
            url_for("mess_detail", mess_id=mess.id)
        )
  
    # ---------------------------------------------------------
    # MESS OWNER CREATES MEAL PLAN
    # ---------------------------------------------------------

    @app.route(
        "/messes/<int:mess_id>/plans/add",
        methods=["POST"]
    )
    @role_required("mess_owner")
    def add_plan(mess_id):

        mess = Mess.query.get_or_404(mess_id)

        if mess.owner_id != current_user.id:
            abort(403)

        try:
            duration_days = get_integer(
                request.form.get("duration_days"),
                "plan duration"
            )

            capacity = get_integer(
                request.form.get("capacity"),
                "plan capacity",
                default=100
            )

            price = get_decimal(
                request.form.get("price"),
                "plan price"
            )

            if duration_days < 1:
                raise ValueError(
                    "Plan duration must be at least one day."
                )

            if capacity < 1:
                raise ValueError(
                    "Plan capacity must be at least one."
                )

            if price < 0:
                raise ValueError(
                    "Plan price cannot be negative."
                )

            plan = MealPlan(
                mess_id=mess.id,
                name=get_required_text("name"),
                duration_days=duration_days,
                meals_included=get_required_text("meals_included"),
                price=price,
                capacity=capacity
            )

            db.session.add(plan)
            db.session.commit()

            flash("Meal plan created successfully.", "success")

        except (ValueError, TypeError, ArithmeticError) as error:
            db.session.rollback()
            flash(str(error), "danger")

        except Exception:
            db.session.rollback()
            app.logger.exception("Creating meal plan failed.")
            flash(
                "Unable to create meal plan. Please try again.",
                "danger"
            )

        return redirect(
            url_for("mess_detail", mess_id=mess.id)
        )

    # ---------------------------------------------------------
    # STUDENT REQUESTS MEAL SUBSCRIPTION
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # STUDENT REQUESTS MEAL SUBSCRIPTION
    # ---------------------------------------------------------

    @app.route("/subscribe/<int:plan_id>", methods=["POST"])
    @role_required("student")
    def subscribe(plan_id):

        plan = MealPlan.query.filter_by(
            id=plan_id,
            active=True
        ).first_or_404()

        try:
            start_date_value = request.form.get(
                "start_date", ""
            ).strip()

            if not start_date_value:
                raise ValueError("Please select a subscription start date.")

            try:
                start_date = date.fromisoformat(start_date_value)
            except ValueError:
                raise ValueError("Please enter a valid start date.")

            if start_date < date.today():
                raise ValueError(
                    "Subscription start date cannot be in the past."
                )

            # Count currently active approved subscriptions
            approved_count = Subscription.query.filter(
                Subscription.plan_id == plan.id,
                Subscription.status == "approved",
                Subscription.end_date >= date.today()
            ).count()

            if approved_count >= plan.capacity:
                raise ValueError(
                    "Sorry! This meal plan is currently full."
                )

            end_date = start_date + timedelta(
                days=plan.duration_days
            )

            subscription = Subscription(
                student_id=current_user.id,
                plan_id=plan.id,
                start_date=start_date,
                end_date=end_date,
                status="pending"
            )

            db.session.add(subscription)

            db.session.add(
                Notification(
                    user_id=plan.mess.owner_id,
                    message=(
                        f"New meal subscription request for {plan.name}."
                    )
                )
            )

            db.session.commit()

            flash(
                "Subscription request sent for mess owner approval.",
                "success"
            )

        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error), "danger")

        except Exception:
            db.session.rollback()
            app.logger.exception("Subscription request failed.")

            flash(
                "Unable to send subscription request. Please try again.",
                "danger"
            )

        return redirect(url_for("dashboard"))



    # ---------------------------------------------------------
    # MESS OWNER APPROVES OR REJECTS SUBSCRIPTION
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # MESS OWNER APPROVES OR REJECTS SUBSCRIPTION
    # WITH CAPACITY VALIDATION
    # ---------------------------------------------------------

    @app.route(
        "/subscriptions/<int:sub_id>/decision",
        methods=["POST"]
    )
    @role_required("mess_owner")
    def subscription_decision(sub_id):

        subscription = Subscription.query.get_or_404(sub_id)

        # Lock the meal plan row while processing approval.
        # This helps prevent simultaneous approvals exceeding capacity.
        plan = (
            MealPlan.query
            .filter_by(id=subscription.plan_id)
            .with_for_update()
            .first_or_404()
        )

        if plan.mess.owner_id != current_user.id:
            abort(403)

        decision = request.form.get("decision", "").strip()

        if subscription.status != "pending":

            flash(
                "This subscription request has already been processed.",
                "warning"
            )

        elif decision not in ("approved", "rejected"):

            flash("Invalid subscription decision.", "danger")

        else:

            try:
                # Check capacity only when approving
                if decision == "approved":

                    approved_count = Subscription.query.filter(
                        Subscription.plan_id == plan.id,
                        Subscription.status == "approved",
                        Subscription.end_date >= date.today()
                    ).count()

                    if approved_count >= plan.capacity:

                        flash(
                            f"Cannot approve! The {plan.name} "
                            f"plan has reached its capacity of "
                            f"{plan.capacity} students.",
                            "danger"
                        )

                        return redirect(url_for("dashboard"))

                subscription.status = decision

                subscription.owner_reason = request.form.get(
                    "reason",
                    ""
                ).strip()

                db.session.add(
                    Notification(
                        user_id=subscription.student_id,
                        message=(
                            f"Your meal subscription for "
                            f"{plan.name} was {decision}."
                        )
                    )
                )

                db.session.commit()

                flash(
                    f"Subscription {decision} successfully.",
                    "success"
                )

            except Exception:
                db.session.rollback()
                app.logger.exception(
                    "Processing subscription decision failed."
                )

                flash(
                    "Unable to process subscription. Please try again.",
                    "danger"
                )

        return redirect(url_for("dashboard"))



    # ---------------------------------------------------------
    # STUDENT CANCELS MEAL SUBSCRIPTION
    # ---------------------------------------------------------

    @app.route(
        "/subscriptions/<int:sub_id>/cancel",
        methods=["POST"]
    )
    @role_required("student")
    def cancel_subscription(sub_id):

        subscription = Subscription.query.get_or_404(sub_id)

        # Students can cancel only their own subscriptions.
        if subscription.student_id != current_user.id:
            abort(403)

        # Pending requests can be cancelled at any time.
        if subscription.status == "pending":
            pass

        # Approved subscriptions can be cancelled only
        # before their start date.
        elif (
            subscription.status == "approved"
            and subscription.start_date > date.today()
        ):
            pass

        else:
            flash(
                "This subscription cannot be cancelled.",
                "danger"
            )
            return redirect(url_for("dashboard"))

        try:
            subscription.status = "cancelled"

            db.session.add(
                Notification(
                    user_id=subscription.plan.mess.owner_id,
                    message=(
                        f"{current_user.name} cancelled the subscription "
                        f"for {subscription.plan.name}."
                    )
                )
            )

            db.session.commit()

            flash(
                "Subscription cancelled successfully.",
                "success"
            )

        except Exception:
            db.session.rollback()
            app.logger.exception("Subscription cancellation failed.")

            flash(
                "Unable to cancel subscription. Please try again.",
                "danger"
            )

        return redirect(url_for("dashboard"))


    # =========================================================
    # NOTIFICATIONS
    # =========================================================

    @app.route("/notifications")
    @login_required
    def notifications():

        items = (
            Notification.query
            .filter_by(user_id=current_user.id)
            .order_by(Notification.created_at.desc())
            .all()
        )

        for item in items:
            item.is_read = True

        db.session.commit()

        return render_template(
            "notifications.html",
            items=items
        )


    # =========================================================
    # REVIEWS
    # =========================================================

    @app.route("/reviews", methods=["POST"])
    @role_required("student")
    def add_review():

        try:
            rating = int(request.form.get("rating", "0"))
        except (TypeError, ValueError):
            rating = 0

        hostel_id = request.form.get("hostel_id", type=int)
        mess_id = request.form.get("mess_id", type=int)

        redirect_url = request.referrer or url_for("index")

        # Validate rating
        if rating not in range(1, 6):
            flash("Rating must be between 1 and 5.", "danger")
            return redirect(redirect_url)

        # Exactly one target must be selected
        if bool(hostel_id) == bool(mess_id):
            flash("Choose either a hostel or a mess to review.", "danger")
            return redirect(redirect_url)

        if hostel_id:

            hostel = Hostel.query.filter_by(
                id=hostel_id,
                active=True
            ).first()

            if not hostel:
                abort(404)

            # Student must have an approved booking
            eligible = Booking.query.filter_by(
                student_id=current_user.id,
                hostel_id=hostel_id,
                status="approved"
            ).first()

            existing_review = Review.query.filter_by(
                student_id=current_user.id,
                hostel_id=hostel_id
            ).first()

        else:

            mess = Mess.query.filter_by(
                id=mess_id,
                active=True
            ).first()

            if not mess:
                abort(404)

            # Student must have an approved subscription
            eligible = (
                Subscription.query
                .join(MealPlan)
                .filter(
                    Subscription.student_id == current_user.id,
                    MealPlan.mess_id == mess_id,
                    Subscription.status == "approved"
                )
                .first()
            )

            existing_review = Review.query.filter_by(
                student_id=current_user.id,
                mess_id=mess_id
            ).first()

        # Check eligibility
        if not eligible:
            flash(
                "You can review only after your booking or subscription is approved.",
                "warning"
            )
            return redirect(redirect_url)

        # Prevent duplicate reviews
        if existing_review:
            flash(
                "You have already reviewed this listing.",
                "warning"
            )
            return redirect(redirect_url)

        comment = request.form.get("comment", "").strip()

        review = Review(
            student_id=current_user.id,
            hostel_id=hostel_id,
            mess_id=mess_id,
            rating=rating,
            comment=comment
        )

        try:
            db.session.add(review)
            db.session.commit()

            flash("Review submitted successfully!", "success")

        except Exception:
            db.session.rollback()
            app.logger.exception("Submitting review failed.")

            flash(
                "Unable to submit your review. Please try again.",
                "danger"
            )

        return redirect(redirect_url)

    # =========================================================
    # ERROR HANDLERS
    # =========================================================

    @app.errorhandler(403)
    def forbidden(error):
        return "You are not authorized to access this page.", 403

    @app.errorhandler(404)
    def not_found(error):
        return "The requested page was not found.", 404

    @app.errorhandler(500)
    def internal_server_error(error):
        db.session.rollback()
        app.logger.exception("Internal server error.")
        return "An internal server error occurred. Please try again.", 500

    # Return the configured Flask application
    return app


# -------------------------------------------------------------
# APPLICATION ENTRY POINT
# -------------------------------------------------------------

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)



# from datetime import date, timedelta
import os
import uuid
# from decimal import Decimal
# from flask import Flask, render_template, redirect, url_for, flash, request, abort
# from flask_login import login_user, logout_user, login_required, current_user
# from sqlalchemy import or_
from werkzeug.utils import secure_filename
from PIL import Image, UnidentifiedImageError
# from config import Config
# from extensions import db, login_manager
# from models import User, Hostel, Booking, Mess, MenuItem, MealPlan, Subscription, Review, Notification

# def create_app():
#     app = Flask(__name__)
#     app.config.from_object(Config)
#     db.init_app(app)
#     login_manager.init_app(app)

#     def role_required(*roles):
#         def decorator(fn):
#             from functools import wraps
#             @wraps(fn)
#             @login_required
#             def wrapped(*args, **kwargs):
#                 if current_user.role not in roles:
#                     abort(403)
#                 return fn(*args, **kwargs)
#             return wrapped
#         return decorator

#     @app.context_processor
#     def inject_notifications():
#         if current_user.is_authenticated:
#             return {"unread_notifications": Notification.query.filter_by(user_id=current_user.id, is_read=False).count()}
#         return {"unread_notifications": 0}

#     @app.route("/")
#     def index():
#         hostels = Hostel.query.filter_by(active=True).order_by(Hostel.created_at.desc()).limit(6).all()
#         messes = Mess.query.filter_by(active=True).order_by(Mess.id.desc()).limit(6).all()
#         return render_template("index.html", hostels=hostels, messes=messes)

#     @app.route("/register", methods=["GET","POST"])
#     def register():
#         if request.method == "POST":
#             name=request.form.get("name","").strip()
#             email=request.form.get("email","").strip().lower()
#             phone=request.form.get("phone","").strip()
#             password=request.form.get("password","")
#             role=request.form.get("role","")
#             if not all([name,email,phone,password]) or role not in ("student","hostel_owner","mess_owner"):
#                 flash("Please complete all fields and choose a valid account type.","danger")
#             elif len(password)<8:
#                 flash("Password must contain at least 8 characters.","danger")
#             elif User.query.filter(or_(User.email==email,User.phone==phone)).first():
#                 flash("Email or phone number is already registered.","danger")
#             else:
#                 user=User(name=name,email=email,phone=phone,role=role)
#                 user.set_password(password)
#                 db.session.add(user); db.session.commit()
#                 login_user(user)
#                 flash("Account created successfully.","success")
#                 return redirect(url_for("dashboard"))
#         return render_template("register.html")

#     @app.route("/login", methods=["GET","POST"])
#     def login():
#         if request.method=="POST":
#             email=request.form.get("email","").strip().lower()
#             password=request.form.get("password","")
#             role=request.form.get("role","")
#             user=User.query.filter_by(email=email,role=role).first()
#             if user and user.check_password(password):
#                 login_user(user); flash("Welcome back!","success")
#                 return redirect(url_for("dashboard"))
#             flash("Invalid email, password, or account type.","danger")
#         return render_template("login.html")

#     @app.route("/logout")
#     @login_required
#     def logout():
#         logout_user(); flash("You have been logged out.","info")
#         return redirect(url_for("index"))

#     @app.route("/dashboard")
#     @login_required
#     def dashboard():
#         if current_user.role=="student":
#             bookings=Booking.query.filter_by(student_id=current_user.id).order_by(Booking.created_at.desc()).all()
#             subscriptions=Subscription.query.filter_by(student_id=current_user.id).order_by(Subscription.created_at.desc()).all()
#             return render_template("student/dashboard.html",bookings=bookings,subscriptions=subscriptions)
#         if current_user.role=="hostel_owner":
#             hostels=Hostel.query.filter_by(owner_id=current_user.id).all()
#             ids=[h.id for h in hostels]
#             bookings=Booking.query.filter(Booking.hostel_id.in_(ids)).order_by(Booking.created_at.desc()).all() if ids else []
#             return render_template("hostel_owner/dashboard.html",hostels=hostels,bookings=bookings)
#         messes=Mess.query.filter_by(owner_id=current_user.id).all()
#         ids=[m.id for m in messes]
#         plans=MealPlan.query.filter(MealPlan.mess_id.in_(ids)).all() if ids else []
#         subscriptions=Subscription.query.join(MealPlan).filter(MealPlan.mess_id.in_(ids)).order_by(Subscription.created_at.desc()).all() if ids else []
#         return render_template("mess_owner/dashboard.html",messes=messes,plans=plans,subscriptions=subscriptions)

#     @app.route("/hostels")
#     def hostels():
#         q=Hostel.query.filter_by(active=True)
#         locality=request.args.get("locality","").strip()
#         room_type=request.args.get("room_type","").strip()
#         max_rent=request.args.get("max_rent","").strip()
#         if locality: q=q.filter(Hostel.locality.ilike(f"%{locality}%"))
#         if room_type: q=q.filter(Hostel.room_type==room_type)
#         if max_rent:
#             try: q=q.filter(Hostel.rent<=Decimal(max_rent))
#             except: flash("Enter a valid maximum rent.","warning")
#         return render_template("hostels.html",hostels=q.order_by(Hostel.rent).all())


#     @app.route("/hostels/add", methods=["GET", "POST"])
#     @role_required("hostel_owner")
#     def add_hostel():

#         if request.method == "POST":
#             try:
#                 total_rooms = int(request.form["total_rooms"])
#                 available_rooms = int(request.form["available_rooms"])

#                 if total_rooms < 1:
#                     raise ValueError("Total rooms must be at least 1.")

#                 if available_rooms < 0 or available_rooms > total_rooms:
#                     raise ValueError("Available rooms must be between 0 and total rooms.")

#                 rent = Decimal(request.form["rent"])
#                 deposit = Decimal(request.form.get("deposit") or 0)

#                 if rent < 0 or deposit < 0:
#                     raise ValueError("Rent and deposit cannot be negative.")

#                 h = Hostel(
#                     owner_id=current_user.id,
#                     name=request.form["name"].strip(),
#                     locality=request.form["locality"].strip(),
#                     address=request.form["address"].strip(),
#                     college=request.form.get("college", "").strip(),
#                     rent=rent,
#                     deposit=deposit,
#                     room_type=request.form.get("room_type", "Shared"),
#                     gender_policy=request.form.get("gender_policy", "Any"),
#                     total_rooms=total_rooms,
#                     available_rooms=available_rooms,
#                     facilities=request.form.get("facilities", "").strip(),
#                     description=request.form.get("description", "").strip(),
#                     contact_phone=request.form.get("contact_phone", "").strip()
#                 )

#                 db.session.add(h)
#                 db.session.commit()

#                 flash("Hostel listing published successfully!", "success")
#                 return redirect(url_for("dashboard"))

#             except (ValueError, TypeError, ArithmeticError) as e:
#                 db.session.rollback()
#                 flash(str(e) or "Please enter valid hostel details.", "danger")

#         return render_template("hostel_form.html", hostel=None)


#     @app.route("/hostels/<int:hostel_id>")
#     def hostel_detail(hostel_id):

#         h = Hostel.query.filter_by(
#             id=hostel_id,
#             active=True
#         ).first_or_404()

#         reviews = Review.query.filter_by(hostel_id=h.id).all()

#         return render_template(
#             "hostel_detail.html",
#             hostel=h,
#             reviews=reviews,
#             today=date.today().isoformat()
#         )


#     @app.route("/hostels/<int:hostel_id>/edit", methods=["GET", "POST"])
#     @role_required("hostel_owner")
#     def edit_hostel(hostel_id):

#         h = Hostel.query.get_or_404(hostel_id)

#         # Check that the logged-in owner owns this hostel.
#         if h.owner_id != current_user.id:
#             abort(403)

#         if request.method == "POST":
#             try:
#                 total_rooms = int(request.form["total_rooms"])
#                 available_rooms = int(request.form["available_rooms"])

#                 if total_rooms < 1:
#                     raise ValueError("Total rooms must be at least 1.")

#                 if available_rooms < 0 or available_rooms > total_rooms:
#                     raise ValueError("Available rooms cannot exceed total rooms.")

#                 rent = Decimal(request.form["rent"])
#                 deposit = Decimal(request.form.get("deposit") or 0)

#                 if rent < 0 or deposit < 0:
#                     raise ValueError("Rent and deposit cannot be negative.")

#                 h.name = request.form["name"].strip()
#                 h.locality = request.form["locality"].strip()
#                 h.address = request.form["address"].strip()
#                 h.college = request.form.get("college", "").strip()
#                 h.rent = rent
#                 h.deposit = deposit
#                 h.room_type = request.form.get("room_type", "Shared")
#                 h.gender_policy = request.form.get("gender_policy", "Any")
#                 h.total_rooms = total_rooms
#                 h.available_rooms = available_rooms
#                 h.contact_phone = request.form.get("contact_phone", "").strip()
#                 h.facilities = request.form.get("facilities", "").strip()
#                 h.description = request.form.get("description", "").strip()

#                 db.session.commit()

#                 flash("Hostel details updated successfully!", "success")

#                 return redirect(
#                     url_for("hostel_detail", hostel_id=h.id)
#                 )

#             except (ValueError, TypeError, ArithmeticError) as e:
#                 db.session.rollback()
#                 flash(str(e) or "Please enter valid hostel details.", "danger")

#         return render_template("hostel_form.html", hostel=h)



#         @app.route("/book/<int:hostel_id>", methods=["POST"])
#         @role_required("student")
#         def book_hostel(hostel_id):
#             h=Hostel.query.filter_by(id=hostel_id,active=True).first_or_404()
#             try:
#                 start=date.fromisoformat(request.form["start_date"]); end=date.fromisoformat(request.form["end_date"])
#                 if start<date.today() or end<=start: raise ValueError()
#             except ValueError:
#                 flash("Choose valid dates. End date must be after start date.","danger"); return redirect(url_for("hostel_detail",hostel_id=h.id))
#             booking=Booking(student_id=current_user.id,hostel_id=h.id,start_date=start,end_date=end)
#             db.session.add(booking)
#             db.session.add(Notification(user_id=h.owner_id,message=f"New hostel booking request for {h.name}."))
#             db.session.commit(); flash("Booking request sent. It is pending owner approval.","success")
#             return redirect(url_for("dashboard"))

#         @app.route("/bookings/<int:booking_id>/decision", methods=["POST"])
#         @role_required("hostel_owner")
#         def booking_decision(booking_id):
#             b=Booking.query.get_or_404(booking_id)
#             if b.hostel.owner_id!=current_user.id: abort(403)
#             decision=request.form.get("decision")
#             if b.status!="pending" or decision not in ("approved","rejected"):
#                 flash("This request can no longer be changed.","warning")
#             else:
#                 b.status=decision; b.owner_reason=request.form.get("reason","").strip()
#                 db.session.add(Notification(user_id=b.student_id,message=f"Your booking for {b.hostel.name} was {decision}."))
#                 db.session.commit(); flash(f"Booking {decision}.","success")
#             return redirect(url_for("dashboard"))

#         @app.route("/messes")
#         def messes():
#             q=Mess.query.filter_by(active=True)
#             locality=request.args.get("locality","").strip()
#             food_type=request.args.get("food_type","").strip()
#             if locality:q=q.filter(Mess.locality.ilike(f"%{locality}%"))
#             if food_type:q=q.filter(Mess.food_type==food_type)
#             return render_template("messes.html",messes=q.order_by(Mess.name).all())

#         @app.route("/messes/add",methods=["GET","POST"])
#         @role_required("mess_owner")
#         def add_mess():
#             if request.method=="POST":
#                 m=Mess(owner_id=current_user.id,name=request.form["name"].strip(),locality=request.form["locality"].strip(),
#                     address=request.form["address"].strip(),food_type=request.form.get("food_type","Veg"),
#                     opening_hours=request.form.get("opening_hours"),contact_phone=current_user.phone,description=request.form.get("description"))
#                 db.session.add(m);db.session.commit();flash("Mess listing published.","success");return redirect(url_for("dashboard"))
#             return render_template("mess_form.html")

#         @app.route("/messes/<int:mess_id>")
#         def mess_detail(mess_id):
#             m=Mess.query.filter_by(id=mess_id,active=True).first_or_404()
#             plans=MealPlan.query.filter_by(mess_id=m.id,active=True).all()
#             menus=MenuItem.query.filter_by(mess_id=m.id,menu_date=date.today()).all()
#             return render_template("mess_detail.html",mess=m,plans=plans,menus=menus)

#         @app.route("/messes/<int:mess_id>/menu",methods=["POST"])
#         @role_required("mess_owner")
#         def add_menu(mess_id):
#             m=Mess.query.get_or_404(mess_id)
#             if m.owner_id!=current_user.id:abort(403)
#             try: menu_date=date.fromisoformat(request.form["menu_date"])
#             except ValueError: flash("Invalid date.","danger");return redirect(url_for("dashboard"))
#             item=MenuItem(mess_id=m.id,menu_date=menu_date,meal_type=request.form["meal_type"],item_name=request.form["item_name"],price=Decimal(request.form.get("price") or 0))
#             db.session.add(item);db.session.commit();flash("Menu item added.","success");return redirect(url_for("mess_detail",mess_id=m.id))

#         @app.route("/messes/<int:mess_id>/plans/add",methods=["POST"])
#         @role_required("mess_owner")
#         def add_plan(mess_id):
#             m=Mess.query.get_or_404(mess_id)
#             if m.owner_id!=current_user.id:abort(403)
#             p=MealPlan(mess_id=m.id,name=request.form["name"],duration_days=int(request.form["duration_days"]),
#                 meals_included=request.form["meals_included"],price=Decimal(request.form["price"]),capacity=int(request.form.get("capacity") or 100))
#             db.session.add(p);db.session.commit();flash("Meal plan created.","success");return redirect(url_for("mess_detail",mess_id=m.id))

#         @app.route("/subscribe/<int:plan_id>",methods=["POST"])
#         @role_required("student")
#         def subscribe(plan_id):
#             p=MealPlan.query.filter_by(id=plan_id,active=True).first_or_404()
#             start=date.fromisoformat(request.form["start_date"])
#             sub=Subscription(student_id=current_user.id,plan_id=p.id,start_date=start,end_date=start+timedelta(days=p.duration_days),status="pending")
#             db.session.add(sub);db.session.add(Notification(user_id=p.mess.owner_id,message=f"New meal subscription request for {p.name}."))
#             db.session.commit();flash("Subscription request sent for mess owner approval.","success");return redirect(url_for("dashboard"))

#         @app.route("/subscriptions/<int:sub_id>/decision",methods=["POST"])
#         @role_required("mess_owner")
#         def subscription_decision(sub_id):
#             s=Subscription.query.get_or_404(sub_id)
#             if s.plan.mess.owner_id!=current_user.id:abort(403)
#             decision=request.form.get("decision")
#             if s.status!="pending" or decision not in ("approved","rejected"):
#                 flash("This request can no longer be changed.","warning")
#             else:
#                 s.status=decision;s.owner_reason=request.form.get("reason","").strip()
#                 db.session.add(Notification(user_id=s.student_id,message=f"Your meal subscription for {s.plan.name} was {decision}."))
#                 db.session.commit();flash(f"Subscription {decision}.","success")
#             return redirect(url_for("dashboard"))

#         @app.route("/notifications")
#         @login_required
#         def notifications():
#             items=Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
#             for item in items:item.is_read=True
#             db.session.commit()
#             return render_template("notifications.html",items=items)

#         @app.route("/reviews",methods=["POST"])
#         @role_required("student")
#         def add_review():
#             try: rating=int(request.form["rating"])
#             except: rating=0
#             hostel_id=request.form.get("hostel_id",type=int)
#             mess_id=request.form.get("mess_id",type=int)
#             if rating not in range(1,6) or bool(hostel_id)==bool(mess_id):
#                 flash("Choose one listing and a rating from 1 to 5.","danger");return redirect(request.referrer or url_for("index"))
#             if hostel_id:
#                 eligible=Booking.query.filter_by(student_id=current_user.id,hostel_id=hostel_id,status="completed").first()
#             else:
#                 eligible=Subscription.query.join(MealPlan).filter(Subscription.student_id==current_user.id,MealPlan.mess_id==mess_id,Subscription.status=="completed").first()
#             if not eligible:
#                 flash("Reviews are available after a completed booking or subscription.","warning");return redirect(request.referrer or url_for("index"))
#             r=Review(student_id=current_user.id,hostel_id=hostel_id,mess_id=mess_id,rating=rating,comment=request.form.get("comment",""))
#             db.session.add(r);db.session.commit();flash("Review submitted.","success")
#             return redirect(request.referrer or url_for("index"))

#         @app.errorhandler(403)
#         def forbidden(e): return render_template("error.html",code=403,message="You are not allowed to access this page."),403
#         @app.errorhandler(404)
#         def not_found(e): return render_template("error.html",code=404,message="The requested page was not found."),404

#         @app.cli.command("init-db")
#         def init_db():
#             db.create_all()
#             print("Database tables created successfully.")

#         return app

# app=create_app()
# if __name__=="__main__":
#     app.run(debug=True)
