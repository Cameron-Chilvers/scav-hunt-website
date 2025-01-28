from flask import (
    Blueprint, flash, redirect, render_template, request, session, url_for
)
from werkzeug.exceptions import abort
from db import GoogleConnector

from auth import login_required, read_rules_required
import pandas as pd

home_bp = Blueprint('home', __name__)

@home_bp.route('/')
@read_rules_required
@login_required
def index():    
    db: GoogleConnector = home_bp.app.config["DATABASE"]
    username = session.get('user_id')

    # Getting totals for the user
    totals: pd.DataFrame = db.get_totals()
    row: pd.DataFrame = totals[totals['name'] == username]
    points = row['points'].values[0]
    rank = row.index.tolist()[0] + 1

    # Getting the ranks in which have been completed
    top_five = totals.iloc[:5].values.tolist()

    # Getting the person just above the current player and the point difference
    player_above = ['Nonoe', '0']
    if rank != 1:
        player_above = totals[totals.index == rank - 2].values.tolist()[0]

    # Getting the tasks remaining for the user
    # Splitting up for the differnet columns
    col_one = []
    col_two = []
    for k, v in db.activities.items():        
        formatted_name = k.replace("_", " ")

        # Calculate the number of tasks with status '1' or '0'
        count = v[v[username].isin(['1'])].shape[0]

        # Calculate the total number of tasks
        total_tasks = v.shape[0]

        # Create a list with the formatted name, tasks, and count
        category_data = [formatted_name, count, total_tasks]

        # Putting in the correct columns
        if any(i in k for i in ["1", "3", "5"]) and "10" not in k: 
            col_one.append(category_data)
        else:
            col_two.append(category_data)

    # Making sure the points in correct order
    col_one_sorted = sorted(col_one, key=lambda x: x[0])
    col_two_sorted = sorted(col_two, key=lambda x: x[0], reverse=True)

    # Get the recently done tasks
    history = db.get_history()
    history['time'] = pd.to_datetime(history['time'])
    recent_five_tasks_done = history.sort_values(['time'], ascending=[False]).head(5).values.tolist()

    # Get the updates information
    updates_data: pd.DataFrame = db.get_task_status()

    # Getting the recenct 5 updates
    filtered_udpates_df: pd.DataFrame = updates_data[(updates_data['user'] == username) & (updates_data['status'] != '')]
    filtered_udpates_df.loc[:, 'time'] = pd.to_datetime(filtered_udpates_df['time'])
    filtered_udpates_list = filtered_udpates_df.sort_values(['time'], ascending=[False]).head(5).values.tolist()
    
    return render_template('home/index.html', points = points, rank = rank, top_five = top_five, player_above = player_above,
                           col_one= col_one_sorted, col_two = col_two_sorted, recent_tasks = recent_five_tasks_done, updates_list = filtered_udpates_list)


@home_bp.route('/updates')
@login_required
def updates():
    db: GoogleConnector = home_bp.app.config["DATABASE"]
    username = session.get('user_id')

    # Geting totals and points
    totals: pd.DataFrame = db.get_totals()
    row: pd.DataFrame = totals[totals['name'] == username]
    points = row['points'].values[0]
    rank = row.index.tolist()[0] + 1

    # Get the updates information
    updates_data: pd.DataFrame = db.get_task_status()

    # Filitered df
    filtered_udpates_df: pd.DataFrame = updates_data[updates_data['user'] == username]
    filtered_udpates_df['time'] = pd.to_datetime(filtered_udpates_df['time'])
    filtered_udpates_list = filtered_udpates_df.sort_values(['time'], ascending=[False]).head(75).values.tolist() # Only show last 75 of your updates

    return render_template('home/updates.html', updates_data = filtered_udpates_list, points = points, rank = rank)

@home_bp.route('/test_stuff')
@login_required
def test_stuff():
    db: GoogleConnector = home_bp.app.config["DATABASE"]
    username = session.get('user_id')


    db.send_email(
    sender_email="jpscavdb@jpscavdb.iam.gserviceaccount.com",
    recipient_email="awin7052@gmail.com",
    subject="Hello from cameron website",
    body="This is a test email sent from my scav hunt website!")

    db.send_email(
    sender_email="jpscavdb@jpscavdb.iam.gserviceaccount.com",
    recipient_email="camchilvers123@gmail.com",
    subject="Hello from cameron website",
    body="This is a test email sent from my scav hunt website!")

    db.update_totals()
    return 'hellow'

# Making people read the rules
@home_bp.route("/rules", methods = ['GET', 'POST'])
@login_required
def rules():
    db: GoogleConnector = home_bp.app.config["DATABASE"]

    read_rules = session.get('read_rules')
    username = session.get('user_id')
    
    if request.method == 'POST': 
        # Set the read rules to be '1' in the database
        db.set_read_rules(username, '1')

        # Also set the session to be '1'
        session['read_rules'] = '1'

        return redirect(url_for('index'))


    return render_template('home/rules.html', read_rules = read_rules)
