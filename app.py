from flask import Flask

from config import Config
from extensions import db, login_manager
from routes.auth import auth_bp
from routes.home import home_bp
from routes.troubleshoot import troubleshoot_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)

    from models import (  # noqa: F401  (registers all the tables)
        TroubleshootingAnswer,
        TroubleshootingSession,
        TroubleshootingStep,
        User,
    )

    app.register_blueprint(home_bp)
    app.register_blueprint(troubleshoot_bp)
    app.register_blueprint(auth_bp)

    with app.app_context():
        db.create_all()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)