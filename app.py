from flask import Flask
from datetime import timedelta
import os

from db import GoogleConnector
from auth import auth_bp
from home import home_bp
from tasks import tsk_bp
from approve import approve_bp

UPLOAD_FOLDER = os.path.join('uploads')

def create_app():
    # create and configure the app
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY='dev',
    )

    # Adding 30 mins timeout
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    # add data base to bluprints
    auth_bp.app = app
    home_bp.app = app
    tsk_bp.app = app
    approve_bp.app = app

    # Registering the blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(tsk_bp)
    app.register_blueprint(approve_bp)

    # Url rules
    app.add_url_rule('/', endpoint='index')

    # Connect to Db
    db = GoogleConnector()

    # Store database so can use later
    app.config["DATABASE"] = db


    return app

if __name__ == '__main__':
    create_app().run()