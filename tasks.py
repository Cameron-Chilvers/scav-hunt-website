from flask import (
    Blueprint, render_template, session, request, jsonify
)
from auth import login_required
import os
import pandas as pd
from PIL import Image
import subprocess
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

    activities = db.get_activities()

    # Taken from the home.py
    col_one = []
    col_two = []
    for k, v in activities.items():
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
    if not tsk_bp.app.config['DEV_MODE']:
        allow_tasks = (time_start <= timenow and timenow <= time_end)
    else:
        allow_tasks == True
        
    return render_template('task/tasks.html', rank = rank, points = points, col_one = col_one_sorted, col_two = col_two_sorted, allow_tasks = allow_tasks)

def compress_file(file, task_safe, file_path, quality=40, video_bitrate="200k"):
    """
    Compress an image or video file and return a file-like object.

    Args:
        file (_io.BufferedReader or str): Opened file object or file path.
        task_safe (str): Safe task identifier to prepend to filename.
        file_path (str): Original file path (used for filename extraction).
        quality (int): Compression quality for images (1-100, higher is better quality).
        video_bitrate (str): Bitrate for video compression (e.g., "800k").

    Returns:
        tuple: (file-like object, new filename, content_type)
    """

    # Generate safe filename
    filename = f"{task_safe}_{secure_filename(os.path.basename(file_path))}"
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    
    # Create a temporary file to store file content
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_input:
        temp_input.write(file.read())  # Read from BufferedReader
        temp_input.flush()  # Ensure all data is written
        input_path = temp_input.name  # Use the temp file path

    if ext in [".jpg", ".jpeg", ".png", ".webp"]:

        try:
        # Process images
            img = Image.open(input_path)
            img = img.convert("RGB")  # Ensure compatibility
            
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", optimize=True, quality=quality)
            buffer.seek(0)

            return buffer, filename, "image/jpeg"
        except Exception as e:
            print(f"Error processing file {filename}: {e}")
            return None
        
        finally:
            # Clean up temporary files
            if os.path.exists(input_path):
                os.remove(input_path)  # Clean up input temp file
        
    elif ext in [".mp4", ".mov", ".avi", ".mkv"]:
        try:
            # Process videos
                temp_output = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                temp_output_path = temp_output.name
                temp_output.close()  # Close so FFmpeg can write to it

                # Optimize FFmpeg command for low memory usage
                command = [
                    "ffmpeg", "-y",
                    "-i", input_path,
                    "-b:v", video_bitrate,
                    "-preset", "veryfast",
                    "-bufsize", "500k",
                    "-maxrate", video_bitrate,
                    "-c:a", "aac", "-b:a", "128k",
                    "-threads", "1",
                    "-movflags", "+faststart",
                    temp_output_path
                ]
                subprocess.run(command, check=True)

                # Read compressed video into memory
                with open(temp_output_path, "rb") as f:
                    output_buffer = io.BytesIO(f.read())
                output_buffer.seek(0)

                return output_buffer, filename, "video/mp4"

        except Exception as e:
            print(f"Error processing file {filename}: {e}")
            return None

        finally:
            # Clean up temporary output file
            if os.path.exists(input_path):
                os.remove(input_path)  # Clean up input temp file

            if os.path.exists(temp_output_path):
                os.remove(temp_output_path)


    print(f"Unsupported file type for {filename}. Skipping.")
    return None
    
@tsk_bp.route('/upload_files', methods=['POST'])
@login_required
def upload_files():
    db: GoogleConnector = tsk_bp.app.config["DATABASE"]

    print("Current working directory:", os.getcwd())
    print("Files in upload directory:", os.listdir("uploads/temp"))

    # Get task and person name
    task = request.form.get('task', '').strip()
    person_name = request.form.get('name', '').strip()

    if not task or not person_name:
        return jsonify({"error": "Task or Name is missing"}), 400

    # Normalize names for safe filenames
    task_safe = task.replace(' ', '-')
    person_name_safe = person_name.replace(' ', '-')

    # Get user ID
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    # Get chunk information
    chunk_index = int(request.form.get('chunkIndex', 0))
    total_chunks = int(request.form.get('totalChunks', 1))
    file_name = secure_filename(request.form.get('fileName', ''))

    if not file_name:
        return jsonify({"error": "File name is missing"}), 400

    temp_dir = os.path.join(os.getcwd(), tsk_bp.app.config['UPLOAD_FOLDER'], 'temp', os.path.splitext(file_name)[0])
    os.makedirs(temp_dir, exist_ok=True)  # Ensure the directory exists

    # Save the chunk
    chunk_file_path = os.path.join(temp_dir, f"{chunk_index}.part")
    print(f"Saving chunk at: {chunk_file_path}")  # Debugging log

    with open(chunk_file_path, 'wb') as f:
        f.write(request.files['file'].read())

    # Check if all chunks have been uploaded
    if chunk_index == total_chunks - 1:
        final_file_path = os.path.join(os.getcwd(), tsk_bp.app.config['UPLOAD_FOLDER'], file_name)
        with open(final_file_path, 'wb') as final_file:
            for i in range(total_chunks):
                chunk_path = os.path.join(temp_dir, f"{i}.part")
                if not os.path.exists(chunk_path):
                    print(f"ERROR: Missing chunk {chunk_path}")  # Debugging log
                    return jsonify({"error": f"Missing chunk {i}"}), 500

                with open(chunk_path, 'rb') as chunk_file:
                    final_file.write(chunk_file.read())

                os.remove(chunk_path)  # Delete the chunk after merging

        os.rmdir(temp_dir)  # Remove the temporary directory after merging

        print(f"File successfully reassembled: {final_file_path}")  # Debugging log

        # Process the final file (e.g., compress and upload to database)
        try:
            with open(final_file_path, 'rb') as final_file:
                compressed_file, filename, content_type = compress_file(final_file, task_safe, final_file_path)

                if compressed_file:
                    db.upload_files(person_name_safe, [(final_file, compressed_file, filename, content_type)], task, user_id)
                    db.add_to_task_status(user=person_name, task=task, status="", message="")
                    return jsonify({"message": "Files uploaded successfully!"})
                else:
                    return jsonify({"error": "Compression failed"}), 500

        except Exception as e:
            print(f"Upload failed: {e}")
            return jsonify({"error": "Upload failed"}), 500
        finally:
            os.remove(final_file_path)  # Clean up the final file

    return jsonify({"message": f"Chunk {chunk_index + 1} of {total_chunks} uploaded"})


@tsk_bp.route('/completed_tasks')
@login_required
def completed():
    db: GoogleConnector = tsk_bp.app.config["DATABASE"]
    nickname_lookup = tsk_bp.app.config['NICKNAME_LOOKUP']

    totals: pd.DataFrame = db.get_totals()
    # Getting rankings
    totals.loc[:, 'name'] = totals['name'].str.lower()
    totals.loc[:, 'name'] = totals['name'].map(nickname_lookup)
    totals['name'] = totals['name'].astype(str)
    rankings = totals.values.tolist()
    print(rankings)
    players = sorted(rankings, key=lambda x: (x[0]))

    # Getting the history of all compelted tasks
    history = db.get_history()
    history['time'] = pd.to_datetime(history['time'])
    # Converting to nick name
    history.loc[:, 'name'] = history['name'].str.lower()
    history.loc[:, 'name'] = history['name'].map(nickname_lookup)
    history_list = history.sort_values(['time'], ascending=[False]).head(50).values.tolist() # only show latest 50 compelted task to stop cheating

    return render_template('task/completed_tasks.html', completed_data = history_list, players = players)


@tsk_bp.route('/completed_tasks/<nickname>')
@login_required
def completed_person(nickname):
    db: GoogleConnector = tsk_bp.app.config["DATABASE"]
    nickname_lookup = tsk_bp.app.config['NICKNAME_LOOKUP']

    nickname = nickname.replace('-', ' ')
    username = next((key for key, val in nickname_lookup.items() if val == nickname), None)

    # Reverting username      
    username = username.replace('-', ' ')

    # Use the nickname
    user_info = db.get_user_info(username)

    # Getting all the uploded media from the player
    all_media = db.get_all_media_from_user(username.replace(" ", '-'))

    # Getting totals for the user
    totals: pd.DataFrame = db.get_totals()
    row = totals[totals['name'] == username]
    points = row['points'].values[0]
    rank = row.index.tolist()[0] + 1

    activities = db.get_activities()

    # Taken from the home.py
    col_one = []
    col_two = []
    for k, v in activities.items():
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

    return render_template('task/tasks_completed.html', rank = rank, points = points, col_one = col_one_sorted, col_two = col_two_sorted, user = user_info['nickname'])
