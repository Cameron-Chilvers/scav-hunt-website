import functools

from flask import (
    Blueprint, flash, redirect, render_template, request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash
from db import GoogleConnector

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# Login register
@auth_bp.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db: GoogleConnector = auth_bp.app.config["DATABASE"]
        error = None

        if not username:
            error = 'Username is required.'
        elif not password:
            error = 'Password is required.'

        if any(substring in username for substring in ['\\', '/', '?']):
            error = 'You cannot include the characters \\, \ or ? in the username'

        if error is None:
            try:
                # Standardising the username and password
                username_standard = username.lower()
                hashed_password = generate_password_hash(password)

                # Checking if it exists in db
                db.check_user(username_standard)

                # Adding the user
                db.add_user(username_standard, hashed_password)

                # Add to the activity tables
                db.add_to_activity_tables(username_standard)
                
            except db.UserAlreadyExistsError:
                error = f'User "{username}" is already registered.'
            except db.UserAdditionError:
                error = f"Unexpected error has occured when adding user: {username}"
            except Exception:
                error = f"If you got here then idk what u did"
            else:
                return redirect(url_for("auth.login"))

        flash(error)

    return render_template('auth/register.html')

# Login route
@auth_bp.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db: GoogleConnector = auth_bp.app.config["DATABASE"]
        error = None

        # GET USER and password FROM DATABASE
        user = db.get_user_by_username(username)

        # include error checking
        if user is None:
            error = f'Incorrect username "{username}" or does not exist.'
        elif not check_password_hash(user['password'], password):
            error = 'Incorrect password.'

        # if no error then log in successfully
        if error is None:
            session.clear()
            session['user_id'] = user['user']
            session.permanent = True

            # Set the read rules flag
            session['read_rules'] = db.get_read_rules(user['user'])
            
            print(session['read_rules'])
            return redirect(url_for('index'))

        flash(error)

    return render_template('auth/login.html')

# change passowrd route
@auth_bp.route('/change-password', methods=('GET', 'POST'))
def change_password():
    error = ''

    if request.method == 'POST':
        # Handle the password change logic here
        username = request.form['username']
        new_password = request.form['new_password']
        db: GoogleConnector = auth_bp.app.config["DATABASE"]

        hashed_password = generate_password_hash(new_password)
        
        try:
            db.change_password(username, hashed_password)
        except db.UserDoesNotExistError:
            error = f'The user "{username}" does not exist'
        except db.UserAdditionError:
            error = f'Password change failed for user "{username}". Try again.'
        except Exception:
            error = "If you got here then idk what u did"

        # If no error return changed password correctly
        if error == "":
            flash('Password changed successfully!')
            return redirect(url_for('auth.login'))
        
    flash(error)
    return render_template('auth/change_password.html')

# Adding log out button
@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# Setting up login required so have to login to access the links
def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if session.get('user_id') is None:
            return redirect(url_for('auth.login'))
        return view(**kwargs)

    return wrapped_view

# Approve person required decorator
def approve_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if not session.get('approved'):
            return redirect(url_for('approve.approve_login'))  # Redirect to approve login if not approved
        return view(**kwargs)
    return wrapped_view

# Make sure they read the rules decorator
def read_rules_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if session.get('read_rules') != '1':
            return redirect(url_for('home.rules'))  # Redirect to read rules if not approved
        return view(**kwargs)
    return wrapped_view

@auth_bp.before_app_request
def check_session():
    # Skip session check for the login route and static files
    if request.endpoint in ['auth.login', 'auth.register', 'auth.change_password', 'static']:
        return

    # Check if the user is logged in
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    # Update the session's modification time to extend the lifetime
    session.modified = True
