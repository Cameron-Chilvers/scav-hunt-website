from flask import (
    Blueprint, render_template, session, request, jsonify
)
from auth import login_required
import os
import pandas as pd
from PIL import Image
from moviepy import VideoFileClip
import json
import glob
import random
from datetime import datetime
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

def compress_and_save_files(file, task_safe, user_folder, output_folder, quality=50, video_bitrate="400k"):
    """
    Compress and save image and video files.

    Args:
        files (list): List of file objects to process.
        output_folder (str): Path to the folder where compressed files will be saved.
        quality (int): Compression quality for images (1-100, higher is better quality).
        video_bitrate (str): Bitrate for video compression (e.g., "800k").

    Returns:
        list: List of paths to the compressed files.
    """
    compressed_files = []

    # Generate safe filename
    filename = f"{task_safe}_{file.filename.replace(' ', '-')}"

    # Create temp file path
    file_path = os.path.join(user_folder, filename)
    
    # Save the file locally
    file.save(file_path)

    # Determine if the file is an image or video based on extension
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext in [".jpg", ".jpeg", ".png", ".webp"]:
        # Compress image
        try:
            with Image.open(file_path) as img:
                img = img.convert("RGB")  # Ensure RGB mode for consistency
                compressed_path = os.path.join(output_folder, filename)
                img.save(compressed_path, optimize=True, quality=quality)
                compressed_files.append(compressed_path)
        except Exception as e:
            print(f"Error compressing image {filename}: {e}")

    elif ext in [".mp4", ".mov", ".avi", ".mkv"]:
        # Compress video
        try:
            compressed_path = os.path.join(output_folder, filename)
            with VideoFileClip(file_path) as video:
                video.write_videofile(compressed_path, bitrate=video_bitrate, audio_codec="aac")
                compressed_files.append(compressed_path)
        except Exception as e:
            print(f"Error compressing video {filename}: {e}")

    else:
        print(f"Unsupported file type for {filename}. Skipping.")

    return compressed_files


@tsk_bp.route('/upload_files', methods=['POST'])
@login_required
def upload_files():
    db: GoogleConnector = tsk_bp.app.config["DATABASE"]

    # Get the activity and personName from the form data
    task = request.form.get('task')
    person_name = request.form.get('name')

    # Replace spaces with '-' in activity and personName
    task_safe = task.replace(' ', '-')
    person_name_safe = person_name.replace(' ', '-')

    # Getting files
    files = request.files.getlist('files')

    # Gettin gfolder path and the user id
    upload_folder = os.path.join(tsk_bp.app.config['UPLOAD_FOLDER'])
    user_id = session.get('user_id')

    # Creating folder to use to hold temp files
    user_folder = os.path.join(upload_folder, person_name_safe)
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)

    compressed_folder = os.path.join(upload_folder, person_name_safe, 'compressed')
    if not os.path.exists(compressed_folder):
        os.makedirs(compressed_folder)

    for file in files:
        compress_and_save_files(file=file, task_safe=task_safe, user_folder=user_folder, output_folder=compressed_folder)

    # Uploading to google drive
    db.google_drive_file_upload(task_safe, person_name_safe, files, task, user_id, user_folder)

    # Task_status here with nothing to preserve time
    db.add_to_task_status(user=person_name, task=task, status="", message='')
    
    return jsonify({"message": "Files uploaded successfully!"})


@tsk_bp.route('/gallery')
@login_required
def gallery():
    db: GoogleConnector = tsk_bp.app.config["DATABASE"]
    all_data = []
    pic_paths = []

    # Getting the dataframes
    all_data.append(db.activities['1_point'])
    all_data.append(db.activities['3_point'])
    all_data.append(db.activities['5_point'])
    
    for df in all_data:
        filtered_df = df.loc[(df == '1').any(axis=1)]

        # Looping columns
        for col in filtered_df:
            # Skipping the activites
            if col == 'Activities':
                continue
            
            # Filtering by the name
            only_approved = filtered_df.loc[filtered_df[col] == '1']

            # Getting specific folder
            upload_folder = os.path.join(tsk_bp.app.config['UPLOAD_FOLDER'])
            user_folder = os.path.join(upload_folder, col.replace(' ', '-'))

            # Only getting images
            image_extensions = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp']

            # Getting all photos for it
            for task in only_approved['Activities'].values.tolist():
                task_safe = task.replace(' ', '-')

                # Use glob with multiple patterns
                for ext in image_extensions:
                    pic_paths.extend(glob.glob(os.path.join(user_folder, "compressed", f"{task_safe}*.{ext}")))
                    pic_paths.extend(glob.glob(os.path.join(user_folder, "compressed", f"{task_safe}*.{ext.upper()}")))

    # Converting the paths to work with the media files
    real_pic_paths = [pic_path[15:].replace('compressed\\', '') for pic_path in pic_paths] if len(pic_paths) > 0 else None
    random.shuffle(real_pic_paths)

    return render_template('task/gallery.html', pic_paths = real_pic_paths)

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
        tasks_list = [[activity, status] for activity, status in tasks_base if status == '1']
        
        formatted_name = k.replace("_", " ")

        # Calculate the number of tasks with status '1'
        count = v[v[username].isin(['1'])].shape[0]
        total_tasks = v.shape[0]

        # create the media info
        for i, task in enumerate(tasks_list):
            # Skipping if empty
            if task[1] == '':
                tasks_list[i].append(dict())
                continue   
            
            # Get the info
            task_safe = task[0].replace(' ', '-')
            person_name_safe = username.replace(' ', '-')

            # test to get the google links
            media_info = {'media_info': json.dumps(db.get_media_from_folder(person_name_safe, task_safe))}
            
            # Add back to the task as a dict
            tasks_list[i].append(media_info)

        # Create a list with the formatted name, tasks, and count
        category_data = [formatted_name, tasks_list, count, total_tasks]

        # Putting in the correct columns
        if any(i in k for i in ["1", "3"]) and "10" not in k: 
            col_one.append(category_data)
        else:
            col_two.append(category_data)

    # Making sure the points in correct order
    col_one_sorted = sorted(col_one, key=lambda x: x[0])
    col_two_sorted = sorted(col_two, key=lambda x: int(x[0].split(" ")[0]))

    return render_template('task/tasks_completed.html', rank = rank, points = points, col_one = col_one_sorted, col_two = col_two_sorted, user = username)
