from flask import (
    Blueprint,  redirect, render_template, request, session, url_for, send_from_directory, send_file, Response, jsonify
)
from flaskr.auth import login_required, approve_required
import os
import json
from .db import GoogleConnector

approve_bp = Blueprint('approve', __name__)
APPROVE_PASSWORD = "testing123"

@approve_bp.route('/approve_tasks')
@approve_required
@login_required
def approve_tasks():    
    db: GoogleConnector = approve_bp.app.config["DATABASE"]

    unapproved_tasks = []
    for k, v in db.activities.items():
        # Transpose to get the '0's
        melted_df = v.melt(id_vars=['Activities'], var_name='Name', value_name='Value')
        filtered_df = melted_df[melted_df['Value'] == '0']
        results = filtered_df[['Activities', 'Name']].to_dict('records')
        
        for task_collection in results:
            # makeing file name safe
            task_safe = task_collection['Activities'].replace(' ', '-')
            person_name_safe = task_collection['Name'].replace(' ', '-')

            # test to get the google links
            task_collection['media_info'] = json.dumps(db.get_media_from_folder(person_name_safe, task_safe))
    
        unapproved_tasks += results

    return render_template('home/approve.html', unapproved_tasks = unapproved_tasks)


@approve_bp.route('/approve_task/<string:task_name>/<string:user_name>', methods=['POST'])
@approve_required
@login_required
def approve_task(task_name, user_name):
    db: GoogleConnector = approve_bp.app.config["DATABASE"]

    # Getting the task names stored in the database
    task_real = task_name.replace('-', ' ')
    name_real = user_name.replace('-', ' ')

    # Try to update the database for the given task
    try:
        for key, value in db.activities.items():
            if task_real not in [activity for activity in value['Activities']]:
                continue
            # Get point value
            point_value = key.split('_')[0]

            # Update DataFrame
            value.loc[value['Activities'] == task_real, name_real] = '1'

            # Call the database update method
            db.change_task(key, task_real, '1', name_real)

            # Add to recent done tasks
            db.add_task_to_hist(name=name_real, task=task_real, point_value=point_value)

            # updating the totals
            db.update_totals()
            
            # Add to the task messge db
            db.edit_task_status(user=name_real, task=task_real, status="1", message="")

            return jsonify({"status": "success", "message": f"Task '{task_real}' for user '{name_real}' has been approved."}), 200
        
    except Exception as e:
        # If any error occurs, return an error message
        return jsonify({"status": "error", "message": f"An error occurred while approving the task: {str(e)}"}), 500

@approve_bp.route('/deny_task/<string:task_name>/<string:user_name>/<string:deny_message>', methods=['POST'])
@approve_required
@login_required
def deny_task(task_name, user_name, deny_message):
    db: GoogleConnector = approve_bp.app.config["DATABASE"]

    task_real = task_name.replace('-', ' ')
    name_real = user_name.replace('-', ' ')              
    deny_message_real = deny_message.replace('-', ' ')

    # Try to update the database for the given task
    try:
        for key, value in db.activities.items():
            if task_real not in [activity for activity in value['Activities']]:
                continue

            # Update DataFrame
            value.loc[value['Activities'] == task_real, name_real] = ''
        
            # Call the database update method
            db.change_task(key, task_real, '', name_real)

            # Delete from google drive
            db.detete_from_drive(task_name=task_name, user_name=user_name)

            # Add to the task messge db 
            db.edit_task_status(user=name_real, task=task_real, status="0", message=deny_message_real)
            
            return jsonify({"status": "success", "message": f"Task '{task_real}' for user '{name_real}' has been denied."}), 200
        
    except Exception as e:
        # If any error occurs, return an error message
        return jsonify({"status": "error", "message": f"An error occurred while denying the task: {str(e)}"}), 500
    
# Basic webapge to scare people also to get them to log in
@approve_bp.route('/approve_login', methods=['GET', 'POST'])
@login_required
def approve_login():
    if request.method == 'POST':
        password = request.form.get('password')

        # Check if the password is correct
        if password == APPROVE_PASSWORD:
            session['approved'] = True  # Set a session variable
            return redirect(url_for('approve.approve_tasks'))  # Redirect to the approve tasks page
        else:
            return "Incorrect password. Please try again."

    # Render the login form for GET requests
    return '''

        <h2 class="text-center mt-5">Enter Password to Access Approve Tasks:</h2>

        <div class="d-flex justify-content-center align-items-center">
        <div class="text-center">
            <form method="post" class="mb-3">
            <div class="mb-3">
                <label for="password" class="form-label">Password</label>
                <input type="password" name="password" id="password" class="form-control" required>
            </div>
            <button type="submit" class="btn btn-primary">Submit</button>
            </form>

        </div>
        </div>
    '''

# Route to make the image appear
@approve_bp.route('/media/<username>/<filename>')
@login_required
def uploaded_file(username, filename):
    return send_from_directory(os.path.join(approve_bp.app.config['UPLOAD_FOLDER'], username, 'compressed'), filename)
