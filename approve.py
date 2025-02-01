from flask import (
    Blueprint,  redirect, render_template, request, session, url_for, send_from_directory, send_file, Response, jsonify
)
from auth import login_required, approve_required
import os
import json
from db import GoogleConnector
import pandas as pd

approve_bp = Blueprint('approve', __name__)
APPROVE_PASSWORD = "testing123"

@approve_bp.route('/approve_tasks')
@approve_required
@login_required
def approve_tasks():    
    db: GoogleConnector = approve_bp.app.config["DATABASE"]
    nickname_lookup = approve_bp.app.config['NICKNAME_LOOKUP']

    unapproved_tasks = []
    unique_people = set()
    activites = db.get_activities()
    
    for k, v in activites.items():
        # Transpose to get the '0's
        melted_df = v.melt(id_vars=['Activities'], var_name='Name', value_name='Value')
        filtered_df = melted_df[melted_df['Value'] == '0']
        results = filtered_df[['Activities', 'Name']].to_dict('records')
        
        # Collect unique people from the filtered results
        unique_people.update(task['Name'] for task in results)
    
    # Fetch media once per unique person
    all_user_media = {person: db.get_all_media_from_user(person.replace(' ', '-')) for person in unique_people}
    
    for k, v in activites.items():
        # Transpose to get the '0's
        melted_df = v.melt(id_vars=['Activities'], var_name='Name', value_name='Value')
        filtered_df = melted_df[melted_df['Value'] == '0']
        results = filtered_df[['Activities', 'Name']].to_dict('records')
        
        # Added people
        already_added = set()

        for task_collection in results:
            # Making file name safe
            task_safe = task_collection['Activities'].replace(' ', '-')
            person_name_safe = task_collection['Name'].replace(' ', '-')

            # Only addding tasks once per person
            if person_name_safe not in already_added:
                already_added.add(person_name_safe)
            else:
                continue

            # Use pre-fetched media info
            media_info_df = all_user_media.get(task_collection['Name'], pd.DataFrame())
            
            # Grouping all media by Task
            grouped_all_media = media_info_df.groupby("Task").agg(lambda x: list(x)).reset_index()
        
            # Only getting the Tasks for the specific person
            media_tasks_filtered = grouped_all_media[grouped_all_media["Task"].isin(filtered_df["Activities"])]
            
            # Getting the merged data
            combined_df = pd.merge(filtered_df, media_tasks_filtered, left_on="Activities", right_on="Task", how="left")

            # Only getting the correct Name
            combined_df = combined_df[combined_df['Name'] == task_collection['Name']]

            # Add a nickname column using the nickname_lookup dictionary
            combined_df.loc[:, 'Nickname'] = combined_df['Name'].map(nickname_lookup)

           # Combining the columns into JSON data for the front end
            final_combined_df = (
                combined_df[["Activities", "Name", "Nickname", "uploaded_time"]]
                .assign(media_info=combined_df.iloc[:, 2:-2].apply(lambda x: json.dumps(x.to_dict()), axis=1))
                .to_dict(orient='records')
            )

            unapproved_tasks += final_combined_df

    # Sort efficiently using pre-extracted `uploaded_time`
    unapproved_tasks.sort(key=lambda task: task.get("uploaded_time", pd.NaT))

    return render_template('home/approve.html', unapproved_tasks=unapproved_tasks)

@approve_bp.route('/approve_task/<string:task_name>/<string:user_name>', methods=['POST'])
@approve_required
@login_required
def approve_task(task_name, user_name):
    db: GoogleConnector = approve_bp.app.config["DATABASE"]

    # Getting the task names stored in the database
    task_real = task_name.replace('-', ' ')
    name_real = user_name.replace('-', ' ')
    
    activites = db.get_activities()

    # Try to update the database for the given task
    try:
        for key, value in activites.items():
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

    activities = db.get_activities()

    # Try to update the database for the given task
    try:
        for key, value in activities.items():
            if task_real not in [activity for activity in value['Activities']]:
                continue

            # Update DataFrame
            value.loc[value['Activities'] == task_real, name_real] = ''
        
            # Call the database update method
            db.change_task(key, task_real, '', name_real)

            # Delete from bucket
            db.delete_from_storage(task_name=task_name, user_name=user_name, compressed=False)
            db.delete_from_storage(task_name=task_name, user_name=user_name, compressed=True)

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