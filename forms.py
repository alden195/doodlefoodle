# forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, Regexp, ValidationError
from datetime import datetime

def strip_spaces(x):
    return x.replace(" ", "") if isinstance(x, str) else x

def luhn_valid(num: str) -> bool:
    s, alt = 0, False
    for ch in reversed(num):
        d = ord(ch) - 48  # fast int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        alt = not alt
    return (s % 10) == 0

class PaymentForm(FlaskForm):
    card_number = StringField(
        "Card Number",
        filters=[strip_spaces],
        validators=[
            DataRequired(message="Card number is required."),
            Length(min=16, max=16, message="Card number must be 16 digits."),
            Regexp(r"^\d{16}$", message="Card number must contain only digits.")
        ],
    )
    exp_date = StringField(
        "Expiration Date (MM/YY)",
        validators=[
            DataRequired(message="Expiration date is required."),
            Regexp(r"^(0[1-9]|1[0-2])\/\d{2}$", message="Enter date in MM/YY format.")
        ],
    )
    cvv = StringField(
        "CVV",
        validators=[
            DataRequired(message="CVV is required."),
            Regexp(r"^\d{3,4}$", message="CVV must be 3 or 4 digits.")
        ],
    )
    save_card = BooleanField("Save Card")
    submit = SubmitField("Pay")

    # Extra server checks
    def validate_card_number(self, field):
        if not luhn_valid(field.data):
            raise ValidationError("Card number is invalid.")

    def validate_exp_date(self, field):
        mm, yy = field.data.split("/")
        exp_month = int(mm)
        exp_year = 2000 + int(yy)
        now = datetime.utcnow()
        if exp_year < now.year or (exp_year == now.year and exp_month < now.month):
            raise ValidationError("Expiration date cannot be in the past.")
