from flask_wtf import FlaskForm
from wtforms import EmailField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, EqualTo, Length, Optional, Regexp

from services.device_service import DEVICE_TYPES, OPERATING_SYSTEMS

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=100)])
    email = EmailField(
        "Email",
        validators=[
            DataRequired(),
            Length(max=150),
            Regexp(EMAIL_PATTERN, message="Enter a valid email address."),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=8, max=128, message="Use at least 8 characters.")],
    )
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords do not match.")],
    )
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in")


class DeviceForm(FlaskForm):
    name = StringField("Device name", validators=[DataRequired(), Length(max=80)])
    device_type = SelectField("Type", choices=[(t, t) for t in DEVICE_TYPES])
    brand = StringField("Brand", validators=[Optional(), Length(max=60)])
    model = StringField("Model", validators=[Optional(), Length(max=80)])
    os = SelectField("Operating system", choices=[(o, o) for o in OPERATING_SYSTEMS])
    notes = TextAreaField(
        "Notes for a technician",
        validators=[Optional(), Length(max=300)],
    )
    submit = SubmitField("Save device")
