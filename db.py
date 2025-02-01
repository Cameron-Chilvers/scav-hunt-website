from flask import Request
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from google.cloud import storage
from datetime import timedelta
import pytz
import pandas as pd
import time
from datetime import datetime

# Simple in-memory cache with expiration (global dictionary)
signed_url_cache = {}

# Set a cache entry with expiration
def set_cache_with_expiration(key, value, ttl_seconds):
    expiration_time = time.time() + ttl_seconds
    signed_url_cache[key] = {'url': value, 'expires_at': expiration_time}

# Get a cache entry, checking if it's expired
def get_cache_with_expiration(key):
    cache_entry = signed_url_cache.get(key)
    if cache_entry and cache_entry['expires_at'] > time.time():
        return cache_entry['url']
    else:
        return None


class GoogleConnector:
    def __init__(self, scopes = ["https://www.googleapis.com/auth/spreadsheets", 
                                 'https://www.googleapis.com/auth/drive',
                                'https://www.googleapis.com/auth/devstorage.full_control'], 
                 credential_json = None, 
                 sheet_id = "1Ue-ugS6uAHgjY6rOvcbGNK92AKasbJiLINxpWmoKtvE"):

        # Connection to Google sheets
        self.__scopes = scopes
        self.__credential_json = credential_json
        self.__sheet_id = sheet_id

        # Connecting to the google client
        creds = Credentials.from_service_account_info(self.__credential_json, scopes=self.__scopes, subject = 'jpscavdb@jpscavdb.iam.gserviceaccount.com')
        
        # Connection to gspread client
        self.sheet_client = gspread.authorize(creds)

        # Connection to google client
        self.__google_sheet_service = build("sheets", "v4", credentials=creds)

        # Getting sheet id and opening it
        self.__sheet_id = sheet_id
        self.__sheet = self.sheet_client.open_by_key(self.__sheet_id)

        # Storage Client
        self.__bucket_client = storage.Client(credentials=creds, project="jpscavdb")
        self.__bucket_name = 'jp_scav_media'
        self.__bucket = self.__bucket_client.bucket(self.__bucket_name)

        # Used for filtering
        self.__activity_worksheets = ["1_point", "3_point", "5_point", "7_point", "10_point"]
    
    # Creating custom errors for adding and checking
    class UserAlreadyExistsError(Exception):
        """Raised when a user already exists in the database."""
        pass

    class UserAdditionError(Exception):
        """Raised when there is an error adding a user to the database."""
        pass

    class UserDoesNotExistError(Exception):
        """Raised when there is an error adding a user to the database."""
        pass


#######################################################################################################################################

# GOOGLE SHEET STUFF BELOW

#######################################################################################################################################
    def __get_time_now(self):
        # Get current time in AEST
        now = datetime.now(pytz.FixedOffset(600))
        
        # Format the date and time
        formatted_time = now.strftime("%m/%d/%Y %H:%M:%S")
        return formatted_time

    # Helper function to get the sheet data
    def __get_worksheet_data(self, worksheet_title):
        # Getting gogoel sheet data
        sheet_data = self.__sheet.worksheet(worksheet_title).get_all_values()
        
        # Getting first row for columns
        columns = sheet_data[0]
        sheet_data = sheet_data[1:]

        return sheet_data, columns

    # Getting the history
    def get_history(self):
        # Getting the totals sheet
        hist_data, cols = self.__get_worksheet_data("History")

        # Convert to Dataframe
        hist_df = pd.DataFrame(hist_data, columns=cols)

        return hist_df

    # Getting the total table
    def get_totals(self):
        # Getting the totals sheet
        total_data, cols = self.__get_worksheet_data("Totals")

        # Convert to Dataframe
        totals_df = pd.DataFrame(total_data, columns=cols)
        
        # Converting to a int
        totals_df['points'] = totals_df['points'].astype(int)

        return totals_df
    
    # Getting all the point tables    
    def get_activities(self):
        # Prepare the batch request to fetch all data from the specified sheets
        ranges = [f"{sheet_name}!A:Z" for sheet_name in self.__activity_worksheets]  # Adjust the range as needed
        batch_request = self.__google_sheet_service.spreadsheets().values().batchGet(
            spreadsheetId=self.__sheet_id,
            ranges=ranges
        )
        response = batch_request.execute()

        # Process the response and convert each sheet's data into a DataFrame
        all_data = {}
        for sheet_name, value_range in zip(self.__activity_worksheets, response.get("valueRanges", [])):
            data = value_range.get("values", [])
            if data:  # Check if the sheet is not empty
                header_length = len(data[0])  
                padded_data = [row + [""] * (header_length - len(row)) for row in data]  # Pad rows with empty strings

                all_data[sheet_name] = pd.DataFrame(padded_data [1:], columns=padded_data [0])  # First row as columns

        return all_data

    # Find value in column
    def __find_value_in_column(self, col_values, target_value):
        # Iterate through the values to find the target
        for row, value in enumerate(col_values, start=1):
            if value == target_value:
                return (row, 1)
        
        # Return None if doesn't exist
        return None
    
    # Find values in row
    def __find_value_in_row(self, row_values, target_value):
        # Iterate through the values to find the target
        for row, value in enumerate(row_values, start=1):
            if value == target_value:
                return (1, row)
        
        # Return None if doesn't exist
        return None

    # Checking if user in the database
    def check_user(self, username):
        # Getting worksheer
        worksheet = self.__sheet.worksheet("user_info")
        column_values = worksheet.col_values(1)

        # Getting user data
        cell = self.__find_value_in_column(column_values, username)

        # Throw error if already existrs
        if cell is not None:
            raise self.UserAlreadyExistsError

    # Adding user to the info 
    def add_user(self, username, password, nickname):
        worksheet = self.__sheet.worksheet("user_info")

        # Adding to the sheet
        try:
            worksheet.append_row([username, password, self.__get_time_now(), '0', nickname])
        except Exception as e:
            # Throw exception if there is an error adding the user
            raise self.UserAdditionError(f"Failed to add user '{username}': {str(e)}")
    
    def add_task_to_hist(self, name, task, point_value):
        worksheet = self.__sheet.worksheet("History")

        # Format the date and time
        formatted_time = self.__get_time_now()

        try:
            worksheet.append_row([formatted_time, name, task, point_value])
        except Exception as e:
            # Throw exception if there is an error adding the user
            raise self.UserAdditionError(f"Failed to add recent tasks: {task} for user '{name}': {str(e)}")
    
    # Get user for login
    def get_user_info(self, username):
        # Getting column
        worksheet = self.__sheet.worksheet("user_info")
        column_values = worksheet.col_values(1)

        # Checking for the cell informaiton
        cell = self.__find_value_in_column(column_values, username)

        # If doenst exist then return
        if cell is None:
            return None
        
        user_info = worksheet.get(f"A{cell[0]}:E{cell[0]}")
       
        return {'user': user_info[0][0], 'password': user_info[0][1], 'time_created': user_info[0][2], 'read_rules': user_info[0][3], 'nickname': user_info[0][4]}

    # Get user for login
    def get_nicknames(self):
        # Getting column
        user_data, cols = self.__get_worksheet_data("user_info")

        # Convert to Dataframe
        user_df = pd.DataFrame(user_data, columns=cols)

        # Only getting needed columns
        user_dicts_list = user_df[['username', 'nickname']].to_dict('records')

        # Creating the lookup dict
        cache_dict = dict()
        for user in user_dicts_list:
            cache_dict[user['username']] = user['nickname']

        return cache_dict


    # Changed password logic
    def change_password(self, username, new_password):
        # Getting the column
        worksheet = self.__sheet.worksheet("user_info")
        column_values = worksheet.col_values(1)

        # Checking if match
        cell = self.__find_value_in_column(column_values, username)

        # if no username return with error
        if cell is None:
            raise self.UserDoesNotExistError
        
        # Changing the password
        try:
            worksheet.update_acell(f'B{cell[0]}', new_password)
        except Exception as e:
            # Throw exception if there is an error adding the user
            raise self.UserAdditionError(f"Failed to add user '{username}': {str(e)}")

    # Add name to tables
    def add_to_activity_tables(self, username):
        # Go into all worksheets and append in the new name
        for worksheet in self.__sheet.worksheets():
            # Only getting activity worksheets
            title = worksheet.title
            if title == 'Totals':
                worksheet.append_row([username, 0]) # adding to the totals table
                continue
            elif "_point" not in title: # removes other pages not needed
                continue
            
            # Getting info from worksheet
            row_values = worksheet.row_values(1)

            # Getting last index
            first_empty_index = len(row_values) + 1            

            # Updating the last index
            worksheet.update_cell(1, first_empty_index, username)

    # Updating totals
    def update_totals(self):
        # go through each person in each dataframe and save to another dict
        current_totals = dict()

        old_totals = self.get_totals()

        activities = self.get_activities()

        # Looping through all of the task dataframes
        for k, df in activities.items():
            point_value = int(k.split('_')[0])

            # Loop though each of the columns
            for username in df.columns:
                if username == "Activities":
                    continue
                
                # Getting how many task completed
                count = df[df[username].isin(['1'])].shape[0]

                # Adding or updating the totals 
                if username not in current_totals:
                    current_totals[username] = point_value * count
                else:
                    current_totals[username] += point_value * count

        # Updating totals dataframe and sorting
        old_totals['points'] = old_totals['name'].map(current_totals).fillna(old_totals['points'])
        old_totals.sort_values(by=['points'], inplace=True, ascending=False) 

        # Getting totals sheet
        worksheet = self.__sheet.worksheet("Totals")

        # Clear tand replace the totals worksheet
        worksheet.clear()
        worksheet.update([ old_totals.columns.values.tolist()] +  old_totals.values.tolist()) 

    # Method for changing stauts for the task
    def change_task(self, worksheetname, task_name, value, user):
        # worksheetname = '1_point'
        worksheet = self.__sheet.worksheet(worksheetname)

        # Get where activity row is
        task_cell = worksheet.find(task_name)

        # Get where user col is
        user_cell =  worksheet.find(user)

        # Changing the task cell value        
        worksheet.update_cell(task_cell.row, user_cell.col, str(value))

    # Adding to the stask status sheet
    def add_to_task_status(self, user, task, status, message):
        worksheet = self.__sheet.worksheet("task_status")

        # Format the date and time
        formatted_time = self.__get_time_now()

        try:
            worksheet.append_row([formatted_time, user, task, status, message])
        except Exception as e:
            # Throw exception if there is an error adding the user
            raise self.UserAdditionError(f"Failed to add recent tas: {task} for user '{user}': {str(e)}")
    
    # Changing the task status
    def edit_task_status(self, user, task, status, message):
        # Get the task_status data
        data, cols = self.__get_worksheet_data("task_status")
        task_df = pd.DataFrame(data, columns=cols)

        # Get the row
        filterd_df = task_df.loc[(task_df['status'] == '') & (task_df['user'] == user) & (task_df['task'] == task)]

        # Get the row number of it
        last_row_index = filterd_df.tail().index.values[0]
        converted_index = last_row_index + 2

        # Updating the task status table
        worksheet = self.__sheet.worksheet("task_status")
        try:
            worksheet.update_acell(f'D{converted_index}', status)
            worksheet.update_acell(f'E{converted_index}', message)

        except Exception as e:
            # Throw exception if there is an error adding the user
            raise self.UserAdditionError(f"Failed to update the status table: {str(e)}")

    # Getting the task status
    def get_task_status(self):
        # Getting the totals sheet
        hist_data, cols = self.__get_worksheet_data("task_status")

        # Convert to Dataframe
        hist_df = pd.DataFrame(hist_data, columns=cols)

        return hist_df
    
    # get the read rules flag
    def get_read_rules(self, username):
        # worksheetname = '1_point'
        worksheet = self.__sheet.worksheet('user_info')

        # Get where user row is
        user_cell =  worksheet.find(username)

        # Getting the read_rules cell value        
        read_rules_flag = worksheet.cell(user_cell.row, 4).value

        return read_rules_flag
    
    # get the read rules flag
    def set_read_rules(self, username, value):
        # worksheetname = '1_point'
        worksheet = self.__sheet.worksheet('user_info')

        # Get where user row is
        user_cell =  worksheet.find(username)

        # Changing the task cell value        
        worksheet.update_cell(user_cell.row, 4, value)


#######################################################################################################################################

# GOOGLE BUCKET STUFF BELOW

#######################################################################################################################################

    # Check if user folder exists
    def check_folder_exists(self, folder_name):
        folder_prefix = f"{folder_name}/"
        blobs = list(self.__bucket.list_blobs(prefix=folder_prefix, max_results=1))
        return len(blobs) > 0

    # creating the "folder" structre needed for the pictures
    def create_user_folder(self, username):
        folder_name = username.replace(' ', '-')  # Normalize folder name

        if self.check_folder_exists(folder_name):
            print(f"Folder {folder_name} exists")
            return

        # Folder path (empty object with a trailing slash)
        folder_blob = self.__bucket.blob(f"{folder_name}/")

        # Creating parent folder
        try:
            folder_blob.upload_from_string('')  # Create an empty object
            print(f"Created folder: {folder_name}/")
        except Exception as e:
            print(f"Error creating folder: {e}")
            raise

        # Create a "compressed" subfolder
        compressed_folder_blob = self.__bucket.blob(f"{folder_name}/compressed/")
        try:
            compressed_folder_blob.upload_from_string('')
            print(f"Created subfolder: {folder_name}/compressed/")
        except Exception as e:
            print(f"Error creating subfolder: {e}")
            raise                

    # Upload files here
    def upload_files(self, person_name_safe, files, task, user_id):
        user_folder_path = f"{person_name_safe}/"
        user_folder_path_compressed = f"{person_name_safe}/compressed/"

        # Creating the subdirectory in cloud storage (if needed)
        self.create_user_folder(person_name_safe)

        activities = self.get_activities()
        
        for original_file, compressed_file, filename, content_type in files:
            # Reset file read from compression
            original_file.seek(0)  

            # Upload original file
            blob_path_original = f"{user_folder_path}{filename}"
            blob_original = self.__bucket.blob(blob_path_original)
            blob_original.upload_from_file(original_file, content_type=content_type)
            print(f"Uploaded original {filename} to {blob_path_original}")

            # Upload compressed file
            blob_path_compressed = f"{user_folder_path_compressed}{filename}"
            blob_compressed = self.__bucket.blob(blob_path_compressed)
            blob_compressed.upload_from_file(compressed_file, content_type=content_type)
            print(f"Uploaded compressed {filename} to {blob_path_compressed}")

        # Update the database for the given task
        for key, value in activities.items():
            if task not in value['Activities'].values.tolist():
                continue

            # Call the database update method
            self.change_task(key, task, '0', user_id)

    # Getting all the media the user has uploaded
    def get_all_media_from_user(self, user_folder_name):
        bucket = self.__bucket  # Assuming `self.__bucket` is a `google.cloud.storage.Bucket` instance
        user_folder_path = f"{user_folder_name}/compressed/"  # Ensure folder path format

        # List all files in the user's folder
        blobs = list(bucket.list_blobs(prefix=user_folder_path))

        # If no files found, return an empty DataFrame
        if not blobs:
            return pd.DataFrame(columns=['id', 'mimeType', 'filename', 'name', 'Task', 'signed_url', 'uploaded_time'])

        # Extract metadata
        media_list = pd.DataFrame(
            [
                (
                    blob.name,  # File "ID" (GCS uses full path as identifier)
                    blob.content_type,  # MIME type
                    blob.name.split('/')[-1],  # Filename
                    user_folder_name,  # User folder name
                    blob.name.split('/')[-1].split('_')[0].replace('-', ' '),  # Task name (parsed from filename)
                    self.generate_or_get_cached_signed_url(self.__bucket.name, blob.name),  # Get signed URL
                    blob.updated  # Upload/last modified time
                )
                for blob in blobs if not blob.name.endswith('/')  # Exclude "directory" placeholders
            ],
            columns=['id', 'mimeType', 'filename', 'name', 'Task', 'signed_url', 'uploaded_time']
        )

        # Convert 'uploaded_time' column back to datetime for sorting, then sort
        media_list = media_list.sort_values(by='uploaded_time', ascending=True).reset_index(drop=True)
        media_list['uploaded_time'] = media_list['uploaded_time'].dt.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        return media_list
    
    # Generate a signed URL (or retrieve from cache)
    def generate_or_get_cached_signed_url(self, bucket_name, blob_name, expiry_time = 60):
        cache_key = f"signed_url:{bucket_name}:{blob_name}"

        # Check if the signed URL is already in the cache
        cached_url = get_cache_with_expiration(cache_key)
        if cached_url:
            return cached_url

        # Generate a new signed URL
        blob = self.__bucket.blob(blob_name)

        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiry_time),  # URL expires in 15 minutes
            method="GET"  # Read-only access
        )

        # Cache the signed URL with a slightly shorter expiration time (e.g., 14 minutes)
        set_cache_with_expiration(cache_key, signed_url, ttl_seconds=expiry_time*60)

        return signed_url

    # Deleting from the google storage
    def delete_from_storage(self, task_name, user_name, compressed):
        bucket = self.__bucket  # Assuming `self.__bucket` is a `google.cloud.storage.Bucket` instance
        if compressed == True:
            user_folder_path = f"{user_name}/compressed/"  # Deleteing the ones from the compressed files
        else:
            user_folder_path = f"{user_name}/"  # Deleting from the main folder path

        # List all files in the user's folder
        blobs = list(bucket.list_blobs(prefix=user_folder_path))

        if not blobs:
            return f"No files found for user '{user_name}'", 404

        # Filter files related to the task
        task_files = [blob for blob in blobs if blob.name.startswith(f"{user_folder_path}{task_name}_")]

        if not task_files:
            return f"No files found for task '{task_name}' in '{user_name}'", 404
        
        # Delete each file
        for blob in task_files:
            try:
                blob.delete()
                print(f"Deleted file: {blob.name}")
            except Exception as e:
                print(f"Error deleting {blob.name}: {e}")

        return f"Deleted all files for task '{task_name}' in '{user_name}'", 200