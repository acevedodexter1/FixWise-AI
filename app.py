from flask import Flask
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import RequestEntityTooLarge

from config import Config
from extensions import csrf, db, login_manager
from routes.admin import admin_bp
from routes.ai import ai_bp
from routes.auth import auth_bp
from routes.devices import devices_bp
from routes.home import home_bp
from routes.troubleshoot import troubleshoot_bp
from routes.history import history_bp
from routes.reports import reports_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    @app.errorhandler(CSRFError)
    def csrf_failed(error):
        return "Your form expired or was invalid. Go back, refresh the page and try again.", 400

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(error):
        limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return f"That file is larger than {limit} MB. Go back and choose a smaller screenshot.", 413

    from models import (  # noqa: F401  (registers all the tables)
        Device,
        SessionDevice,
        TroubleshootingAnswer,
        TroubleshootingSession,
        TroubleshootingStep,
        User,
    )

    app.register_blueprint(home_bp)
    app.register_blueprint(troubleshoot_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        db.create_all()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)