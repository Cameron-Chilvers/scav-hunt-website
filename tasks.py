from flask import (
    Blueprint, render_template, session, request, jsonify
)
from auth import login_required
import os
import pandas as pd
from PIL import Image
from moviepy import VideoFileClip
import tempfile
import json

from datetime import datetime
import io
from werkzeug.utils import secure_filename
from pytz import timezone
import time

from db import GoogleConnector

tsk_bp = Blueprint('tasks', __name__)

@tsk_bp.route('/tasks')
@login_required
def tasks():   
    db: GoogleConnector = tsk_bp.app.config["DATABASE"]
    username = session.get('user_id')

    # Getting all the uploded media from the player
    all_media = db.get_all_media_from_user(username.replace(" ", '-'))

    # Getting totals for the user
    totals: pd.DataFrame = db.get_totals()
    row = totals[totals['name'] == username]
    points = row['points'].values[0]
    rank = row.index.tolist()[0] + 1

    # Taken from the home.py
    col_one = []
    col_two = []
    for k, v in db.activities.items():
        # Gets the remaining tasks
        tasks_base = list(zip(v['Activities'], v[username]))
        tasks_list = [[activity, status] for activity, status in tasks_base]
        
        task_df = pd.DataFrame(tasks_list, columns=["Task", "Status"])

        # Grouping all the multiple media to one group
        grouped_all_media = all_media.groupby("Task").agg(
        lambda x: list(x)
        ).reset_index()

        # Only getting the Tasks for the point value
        media_tasks_filtered = grouped_all_media[grouped_all_media["Task"].isin(task_df["Task"])]

        # Getting the merged data
        combined_df = pd.merge(task_df, media_tasks_filtered, on="Task", how="left")

        # Combing the columns into json data to be used in the front end
        final_combined_df = (
            combined_df[["Task", "Status"]]
            .assign(media_info=combined_df.iloc[:, 2:].apply(lambda x: json.dumps(x.to_dict()), axis=1))
            .values.tolist()
        )

        # Getting clean task name
        formatted_name = k.replace("_", " ")

        # Calculate the number of tasks with status '1' or '0'
        count = v[v[username].isin(['1'])].shape[0]
        total_tasks = v.shape[0]

        # Create a list with the formatted name, tasks, and count
        category_data = [formatted_name, final_combined_df, count, total_tasks]

        # Putting in the correct columns
        if any(i in k for i in ["1", "3"]) and "10" not in k: 
            col_one.append(category_data)
        else:
            col_two.append(category_data)

    # Making sure the points in correct order
    col_one_sorted = sorted(col_one, key=lambda x: x[0])
    col_two_sorted = sorted(col_two, key=lambda x: int(x[0].split(" ")[0]))

    # Checking if playerts can upload tasks
    tz = timezone('Australia/Sydney')

    # Create datetime objects with proper timezone localization
    time_start = tz.localize(datetime(2025, 2, 3, 7))
    time_end = tz.localize(datetime(2025, 2, 17, 20))

    # Get the current time in the same timezone
    timenow = datetime.now(tz)

    # Check if the current time is within the range
    allow_tasks = (time_start <= timenow and timenow <= time_end)
    allow_tasks = True
    
    return render_template('task/tasks.html', rank = rank, points = points, col_one = col_one_sorted, col_two = col_two_sorted, allow_tasks = allow_tasks)

def compress_file(file, task_safe, quality=40, video_bitrate="200k"):
    """
    Compress an image or video file and return a file-like object.

    Args:
        file (FileStorage): File object to process.
        task_safe (str): Safe task identifier to prepend to filename.
        quality (int): Compression quality for images (1-100, higher is better quality).
        video_bitrate (str): Bitrate for video compression (e.g., "800k").

    Returns:
        tuple: (file-like object, new filename, content_type)
    """
    filename = f"{task_safe}_{secure_filename(file.filename)}"
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext in [".jpg", ".jpeg", ".png", ".webp"]:
        try:
            img = Image.open(file)
            img = img.convert("RGB")
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", optimize=True, quality=quality)
            buffer.seek(0)
            return buffer, filename, "image/jpeg"
        except Exception as e:
            print(f"Error compressing image {filename}: {e}")
            return None

    elif ext in [".mp4", ".mov", ".avi", ".mkv"]:
       # Use BytesIO to store the video file in memory
        file.seek(0)  # Ensure we read from the start of the file
        buffer = io.BytesIO(file.read())
        buffer.seek(0)  # Reset the buffer's position to the start

        # Write to a temporary file so MoviePy can process it
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_file:
            temp_file.write(buffer.read())  # Write the video data to the temp file
            temp_file_path = temp_file.name  # Get the path to the temporary file

        try:
            # Use VideoFileClip with the path to the temp file
            with VideoFileClip(temp_file_path) as video:
                # Write the output to a temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_output_file:
                    temp_output_path = temp_output_file.name
                    video.write_videofile(temp_output_path, bitrate=video_bitrate, audio_codec="aac", threads=4)
                
                # Read the output video file into a buffer
                with open(temp_output_path, "rb") as f:
                    output_buffer = io.BytesIO(f.read())
                output_buffer.seek(0)
        except Exception as e:
            print(f"Error processing video {filename}: {e}")
            os.remove(temp_file_path)
            return None

        # Clean up the temporary file after processing
        os.remove(temp_file_path)

        return output_buffer, filename, "video/mp4"
    
    print(f"Unsupported file type for {filename}. Skipping.")
    return None

@tsk_bp.route('/upload_files', methods=['POST'])
@login_required
def upload_files():
    db: GoogleConnector = tsk_bp.app.config["DATABASE"]

    # Get the task and personName from the form data
    task = request.form.get('task')
    person_name = request.form.get('name')

    # Replace spaces with '-' in task and personName
    task_safe = task.replace(' ', '-')
    person_name_safe = person_name.replace(' ', '-')

    # Getting files
    files = request.files.getlist('files')

    # Getting user id
    user_id = session.get('user_id')

    # Process and upload each file
    processed_files = []
    for file in files:
        compressed_file, filename, content_type = compress_file(file, task_safe)

        if compressed_file:
            processed_files.append((file, compressed_file, filename, content_type))

    # Upload compressed files directly from memory
    db.upload_files(person_name_safe, processed_files, task, user_id)

    # Task status update
    db.add_to_task_status(user=person_name, task=task, status="", message='')

    return jsonify({"message": "Files uploaded successfully!"})


@tsk_bp.route('/completed_tasks')
@login_required
def completed():
    db: GoogleConnector = tsk_bp.app.config["DATABASE"]

    totals: pd.DataFrame = db.get_totals()
    # Getting rankings
    rankings = totals.values.tolist()
    players = sorted(rankings,key=lambda x: (x[0]))

    # Getting the history of all compelted tasks
    history = db.get_history()
    history['time'] = pd.to_datetime(history['time'])
    history_list = history.sort_values(['time'], ascending=[False]).head(50).values.tolist() # only show latest 50 compelted task to stop cheating

    print(history_list)

    return render_template('task/completed_tasks.html', completed_data = history_list, players = players)


@tsk_bp.route('/completed_tasks/<username>')
@login_required
def completed_person(username):
    db: GoogleConnector = tsk_bp.app.config["DATABASE"]
    
    # Reverting username
    username = username.replace('-', ' ')

    # Getting all the uploded media from the player
    all_media = db.get_all_media_from_user(username.replace(" ", '-'))
    print(all_media)

    # Getting totals for the user
    totals: pd.DataFrame = db.get_totals()
    row = totals[totals['name'] == username]
    points = row['points'].values[0]
    rank = row.index.tolist()[0] + 1

    # Taken from the home.py
    col_one = []
    col_two = []
    for k, v in db.activities.items():
        # Gets the remaining tasks
        tasks_base = list(zip(v['Activities'], v[username]))
        tasks_list = [[activity, status] for activity, status in tasks_base]
        
        task_df = pd.DataFrame(tasks_list, columns=["Task", "Status"])

        # Grouping all the multiple media to one group
        grouped_all_media = all_media.groupby("Task").agg(
        lambda x: list(x)
        ).reset_index()

        # Only getting the Tasks for the point value
        media_tasks_filtered = grouped_all_media[grouped_all_media["Task"].isin(task_df["Task"])]

        # Getting the merged data
        combined_df = pd.merge(task_df, media_tasks_filtered, on="Task", how="left")

        # Combing the columns into json data to be used in the front end
        final_combined_df = (
            combined_df[["Task", "Status"]]
            .assign(media_info=combined_df.iloc[:, 2:].apply(lambda x: json.dumps(x.to_dict()), axis=1))
            .values.tolist()
        )

        # Getting clean task name
        formatted_name = k.replace("_", " ")

        # Calculate the number of tasks with status '1' or '0'
        count = v[v[username].isin(['1'])].shape[0]
        total_tasks = v.shape[0]

        # Create a list with the formatted name, tasks, and count
        category_data = [formatted_name, final_combined_df, count, total_tasks]

        # Putting in the correct columns
        if any(i in k for i in ["1", "3"]) and "10" not in k: 
            col_one.append(category_data)
        else:
            col_two.append(category_data)

    # Making sure the points in correct order
    col_one_sorted = sorted(col_one, key=lambda x: x[0])
    col_two_sorted = sorted(col_two, key=lambda x: int(x[0].split(" ")[0]))

    return render_template('task/tasks_completed.html', rank = rank, points = points, col_one = col_one_sorted, col_two = col_two_sorted, user = username)
