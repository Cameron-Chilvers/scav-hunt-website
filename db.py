from flask import Request
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient import _auth
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow

import pandas as pd
import os
import glob
import time
import threading
from datetime import datetime


# Function to delete files
def delete_files(user_folder):
    globbed_files = glob.glob(user_folder + "\\*")
    filtered_files = [f for f in globbed_files if "compressed" not in f]

    max_retries = 10
    for file in filtered_files:
        time.sleep(2)  # add small delay not to spam
        
        print("Deleting file...")
        tries = 0
        while tries < max_retries:
            try:
                os.remove(file)
                tries = 6
                print("Finished deleting.")
            except Exception as e:
                tries += 1
                print(f"Failed to delete file. Error: {e}. Retrying...")
                time.sleep(2)



class GoogleConnector:
    def __init__(self, scopes = ["https://www.googleapis.com/auth/spreadsheets", 
                                 'https://www.googleapis.com/auth/drive'], 
                 credential_path = r"flaskr\\credentials.json", 
                 sheet_id = "1Ue-ugS6uAHgjY6rOvcbGNK92AKasbJiLINxpWmoKtvE", 
                 folder_id='1wClLnyxbprifajhcqJenXD1zdAC79IMk'):

        # Connection to Google sheets
        self.__scopes = scopes
        self.__credential_path = credential_path
        self.__sheet_id = sheet_id
        self.__folder_id = folder_id

        # Connecting to the google client
        creds = Credentials.from_service_account_file(self.__credential_path, scopes=self.__scopes, subject = 'jpscavdb@jpscavdb.iam.gserviceaccount.com')
        self.sheet_client = gspread.authorize(creds)

        # Getting sheet id and opening it
        self.__sheet_id = sheet_id
        self.__sheet = self.sheet_client.open_by_key(self.__sheet_id)

        # Connection to drive client
        self.http = _auth.authorized_http(creds)
        self.__drive_service = build('drive', 'v3', http=self.http)


        # Used for filtering
        self.__activity_worksheets = ["1_point", "3_point", "5_point", "7_point", "10_point"]

        # Initialise compelted activite store
        # 0 is pending
        # 1 is approved
        self.activities: dict[str, pd.DataFrame] = self.__get_activities()
    
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
    
    def __get_time_now(self):
        # Format the date and time
        now = datetime.now()
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
    def __get_activities(self):
        # Initializing dict
        all_data = dict()

        # Looping all worksheets and getting its info
        for worksheet in self.__sheet.worksheets():
            title = worksheet.title

            # Only getting activity worksheets
            if title not in self.__activity_worksheets:
                continue
            
            # Getting data
            worksheet_data, worksheet_col = self.__get_worksheet_data(title)
            
            # Converting df
            worksheet_df = pd.DataFrame(worksheet_data, columns=worksheet_col)

            # Adding to dict
            all_data[title] = worksheet_df
        
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
    def add_user(self, username, password):
        worksheet = self.__sheet.worksheet("user_info")

        # Adding to the sheet
        try:
            worksheet.append_row([username, password, self.__get_time_now(), '0'])
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
    def get_user_by_username(self, username):
        # Getting column
        worksheet = self.__sheet.worksheet("user_info")
        column_values = worksheet.col_values(1)

        # Checking for the cell informaiton
        cell = self.__find_value_in_column(column_values, username)

        # If doenst exist then return
        if cell is None:
            return None
        
        user_info = worksheet.get(f"A{cell[0]}:B{cell[0]}")
       
        return {'user': user_info[0][0], 'password': user_info[0][1]}

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
                self.totals.append({'name': username, 'points': 0})
                continue
            elif "_point" not in title: # removes other pages not needed
                continue
            
            # Getting info from worksheet
            row_values = worksheet.row_values(1)

            # Getting last index
            first_empty_index = len(row_values) + 1            
            print(first_empty_index)
            # Updating the last index
            worksheet.update_cell(1, first_empty_index, username)

            # Append into the dataframe as well
            self.activities[title][username] = ""

    # Updating totals
    def update_totals(self):
        # go through each person in each dataframe and save to another dict
        current_totals = dict()

        old_totals = self.get_totals()

        # Looping through all of the task dataframes
        for k, df in self.activities.items():
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

    # Adding files to google drive
    def google_drive_file_upload(self, task_safe, person_name_safe, files, task, user_id, user_folder):
        # Check if the folder exists in Google Drive
        user_folder_id = self.get_folder_id(person_name_safe)

        if user_folder_id is None:
            # Create the folder if it doesn't exist
            folder_metadata = {
                'name': person_name_safe,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [self.__folder_id]
            }
            folder = self.__drive_service.files().create(body=folder_metadata, fields='id').execute()
            user_folder_id = folder['id']

        # Save each file to the user's folder
        for file in files:
            filename = f"{task_safe}_{file.filename.replace(' ', '-')}"
            
           # Creating temp file
            file_path = os.path.join(user_folder, filename)
    
            # # Save the file locally
            # file.save(file_path)

            # Prepare metadata for the file
            file_metadata = {
                'name': filename,
                'parents': [user_folder_id]
            }

            # Use the temporary file path for MediaFileUpload
            media = MediaFileUpload(
                file_path,
                mimetype=file.mimetype,
                resumable=True
            )

            # Upload the file to Google Drive
            self.__drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()

        # Clean up the temporary files in the background
        threading.Thread(target=delete_files, args=(user_folder,)).start()                             

        # Update the database for the given task
        for key, value in self.activities.items():
            if task not in [activity for activity in value['Activities']]:
                continue

            # Update Dataframe
            value.loc[value['Activities'] == task, user_id] = '0'

            # Call the database update method
            self.change_task(key, task, '0', user_id)

    # Function to get folder ID by name
    def get_folder_id(self, folder_name):
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and '{self.__folder_id}' in parents"
        results = self.__drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        items = results.get('files', [])
        if not items:
            return None
        return items[0]['id']

    # Function to search for image files inside a folder
    def search_media_in_folder(self, folder_id, task_name):
        query = f"'{folder_id}' in parents and (mimeType contains 'image/' or mimeType contains 'video/') and name contains '{task_name}'"
        results = self.__drive_service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        items = results.get('files', [])
        return items

    # Functions gets all media
    def search_all_media_in_folder(self, folder_id):
        query = f"'{folder_id}' in parents and (mimeType contains 'image/' or mimeType contains 'video/')"
        results = self.__drive_service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        items = results.get('files', [])
        return items

    # New method to view images in a specific folder
    def get_media_from_folder(self, user_folder_name, task_name):
        # Get the user folder ID
        user_folder_id = self.get_folder_id(user_folder_name)
        if not user_folder_id:
            return f"User folder '{user_folder_name}' not found", 404

        # List all images and videos inside the pictures folder
        media_files = self.search_media_in_folder(user_folder_id, task_name)
        if not media_files:
            return "No media files found in the pictures folder", 404

        # Generate list of media
        media_list = [(media['id'], media['mimeType'], media['name'], user_folder_name) for media in media_files]

        return media_list 
    
    # Getting all media to make it a faster query
    def get_all_media_from_user(self, user_folder_name):
        # Check if folder is there
        user_folder_id = self.get_folder_id(user_folder_name)
        if not user_folder_id:
            return pd.DataFrame(columns=['id', 'mimeType', 'filename', 'name', 'Task'])

        # List all images and videos inside the pictures folder
        media_files = self.search_all_media_in_folder(user_folder_id)
        if not media_files:
            return pd.DataFrame(columns=['id', 'mimeType', 'filename', 'name', 'Task'])
        
        # Generate list of media
        media_list = pd.DataFrame([(media['id'], media['mimeType'], media['name'], user_folder_name, media['name'].split('_')[0].replace('-', ' ')) for media in media_files]
                                  , columns=['id', 'mimeType', 'filename', 'name', 'Task'])

        return media_list 

    def get_file_mine_name(self, file_id):
        print(f"Fetching metadata for file ID: {file_id}")

        file_metadata = self.__drive_service.files().get(fileId=file_id, fields='mimeType, name').execute()

        mime_type = file_metadata.get('mimeType', 'application/octet-stream')
        file_name = file_metadata.get('name', 'file')
        return mime_type,file_name
    
    def get_google_drive_service(self):
        return self.__drive_service
    
    def add_to_task_status(self, user, task, status, message):
        worksheet = self.__sheet.worksheet("task_status")

        # Format the date and time
        formatted_time = self.__get_time_now()

        try:
            worksheet.append_row([formatted_time, user, task, status, message])
        except Exception as e:
            # Throw exception if there is an error adding the user
            raise self.UserAdditionError(f"Failed to add recent tas: {task} for user '{user}': {str(e)}")
    
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
    
    def detete_from_drive(self, task_name, user_name):
        # Get the user folder ID
        user_folder_id = self.get_folder_id(user_name)
        if not user_folder_id:
            return f"User folder '{user_name}' not found", 404

        # List all images and videos inside the pictures folder
        media_files = self.search_media_in_folder(user_folder_id, task_name)
        if not media_files:
            return "No media files found in the pictures folder", 404

        # Loop file and delete from the drive
        for file in media_files:
            file_id = file["id"]
            try:
                self.__drive_service.files().delete(fileId=file_id).execute()
                print(f"Deleted file with ID: {file}")
            except HttpError as error:
                print(f"An error occurred for file ID {file_id}: {error}")
    
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
