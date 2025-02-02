from flask import Flask
from datetime import timedelta
from flask_cors import CORS
import base64
import json
import os

from db import GoogleConnector
from auth import auth_bp
from home import home_bp
from tasks import tsk_bp
from approve import approve_bp

dev = False

def create_app():
    # create and configure the app
    app = Flask(__name__)
    
    # Adding 30 mins timeout
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  
    app.config['DEV_MODE'] = dev
    app.config['UPLOAD_FOLDER'] = 'uploads'

    # Getting locally if dev
    if not dev:
        # Set secret key
        app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'yippeeakey645SDDF98646547DSFgcf8S234g434F54899687cv8d87')

        # Get creds
        encoded = os.getenv('CREDENTIALS_JSON')

        # Raiseing errors if env variable doenst exist
        if encoded is None:
            raise RuntimeError(f"Failed to decode or load credentials")

        # Decode the base64 string
        decoded_content = base64.b64decode(encoded).decode("utf-8")
        decoded_content = decoded_content.strip()

        json_creds = json.loads(decoded_content)

    else:
        with open("credentials.json", "r") as f:
            json_creds = json.load(f)
        
        app.config['SECRET_KEY'] = 'dev'


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
    db = GoogleConnector(credential_json=json_creds)

    # Store database so can use later
    app.config["DATABASE"] = db

    # Create the user nickname cache
    nick_cache = db.get_nicknames()
    app.config["NICKNAME_LOOKUP"] = nick_cache

    return app

# Expose the app object for Gunicorn
app = create_app()
CORS(app)

if __name__ == '__main__':
   app.run()