# Scavenger Hunt Website

Created to use while on a trip with friends to create your own scavenger hunt. You just need to link up a google sheet with the tasks you want and the website will read it from there. There is a docker file made so this project is easily deployable with the click of a button.
The photos and videos will be saved on a Google Cloud Bucket and this project was run off Google Cloud run.

It was used for my Japan trip with atleast 10 concurrent users and they experienced no issues.

Features:
- The tasks are read off a google sheet
- Players create their own account
- Players can view / upload videos & pictures
- Uses a Kahoot version of leaderboard tracking
- Allows for multiple people to approve the tasks
