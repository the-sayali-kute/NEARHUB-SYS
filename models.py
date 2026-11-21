from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, login_manager

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum("student", "hostel_owner", "mess_owner"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Hostel(db.Model):
    __tablename__ = "hostels"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    name = db.Column(db.String(150), nullable=False)
    locality = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    college = db.Column(db.String(150))

    rent = db.Column(db.Numeric(10, 2), nullable=False)
    deposit = db.Column(db.Numeric(10, 2), default=0)

    room_type = db.Column(db.String(80), default="Shared")
    gender_policy = db.Column(db.String(40), default="Any")

    total_rooms = db.Column(db.Integer, nullable=False, default=1)
    available_rooms = db.Column(db.Integer, nullable=False, default=1)

    facilities = db.Column(db.Text)
    description = db.Column(db.Text)
    contact_phone = db.Column(db.String(20))

    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User", backref="hostels")
    photos = db.relationship(
        "HostelPhoto",
        back_populates="hostel",
        cascade="all, delete-orphan",
        order_by="HostelPhoto.id",
    )


class HostelPhoto(db.Model):
    __tablename__ = "hostel_photos"

    id = db.Column(db.Integer, primary_key=True)
    hostel_id = db.Column(
        db.Integer,
        db.ForeignKey("hostels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    image_filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    hostel = db.relationship("Hostel", back_populates="photos")


class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    hostel_id = db.Column(db.Integer, db.ForeignKey("hostels.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.Enum("pending","approved","rejected","cancelled","completed"), default="pending")
    owner_reason = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship("User", foreign_keys=[student_id])
    hostel = db.relationship("Hostel", backref="bookings")

class Mess(db.Model):
    __tablename__ = "messes"
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    locality = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    food_type = db.Column(db.String(60), default="Veg")
    opening_hours = db.Column(db.String(120))
    contact_phone = db.Column(db.String(20))
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    owner = db.relationship("User", backref="messes")

class MenuItem(db.Model):
    __tablename__ = "menu_items"

    id = db.Column(db.Integer, primary_key=True)
    mess_id = db.Column(
        db.Integer,
        db.ForeignKey("messes.id"),
        nullable=False
    )
    menu_date = db.Column(db.Date, nullable=False)
    meal_type = db.Column(db.String(30), nullable=False)
    item_name = db.Column(db.String(255), nullable=False)
    price = db.Column(db.Numeric(10, 2), default=0)

    # True = Available, False = Sold Out
    is_available = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.true()
    )

    mess = db.relationship("Mess", backref="menu_items")

class MealPlan(db.Model):
    __tablename__ = "meal_plans"
    id = db.Column(db.Integer, primary_key=True)
    mess_id = db.Column(db.Integer, db.ForeignKey("messes.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    duration_days = db.Column(db.Integer, nullable=False)
    meals_included = db.Column(db.String(120), nullable=False)
    price = db.Column(db.Numeric(10,2), nullable=False)
    capacity = db.Column(db.Integer, default=100)
    active = db.Column(db.Boolean, default=True)
    mess = db.relationship("Mess", backref="plans")

class Subscription(db.Model):
    __tablename__ = "subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("meal_plans.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.Enum("pending","approved","rejected","cancelled","completed"), default="pending")
    owner_reason = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship("User", foreign_keys=[student_id])
    plan = db.relationship("MealPlan", backref="subscriptions")


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)

    student_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    hostel_id = db.Column(
        db.Integer,
        db.ForeignKey("hostels.id")
    )

    mess_id = db.Column(
        db.Integer,
        db.ForeignKey("messes.id")
    )

    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # Relationships for displaying review details
    student = db.relationship(
        "User",
        foreign_keys=[student_id]
    )

    hostel = db.relationship(
        "Hostel",
        foreign_keys=[hostel_id]
    )

    mess = db.relationship(
        "Mess",
        foreign_keys=[mess_id]
    )

class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
