
AIHealth Backup Script Cron Job

This document provides detailed instructions for setting up a cron job that runs the AIHealth backup script every minute for testing purposes.

Prerequisites

- A Unix-like operating system (e.g., Linux)
- A user with sudo privileges
- The cron service installed and running
- The backup script located at /home/deployer/aihealth-deployment/aihealth-server/.backup-scripts/backup.sh

Steps to Set Up the Cron Job

1. Ensure the Script is Executable

Make sure the backup script has executable permissions. Run the following command:

chmod +x /home/deployer/aihealth-deployment/aihealth-server/.backup-scripts/backup.sh

2. Edit the Sudoers File

To allow the deployer user to run the script with sudo without a password and preserve the environment variables, you need to edit the sudoers file.

Open the sudoers file with visudo:

sudo visudo

Add the following line at the end of the file:

deployer ALL=(ALL) NOPASSWD:SETENV: /home/deployer/aihealth-deployment/aihealth-server/.backup-scripts/backup.sh

3. Create the Log File

Ensure that the log file exists and has the appropriate permissions:

touch /home/deployer/aihealth-deployment/aihealth-server/.backup-scripts/backup.log
chmod 666 /home/deployer/aihealth-deployment/aihealth-server/.backup-scripts/backup.log

4. Update the Crontab

Edit the crontab for the deployer user:

crontab -e

Add the following line to run the backup script every minute:

* * * * * /usr/bin/sudo /home/deployer/aihealth-deployment/aihealth-server/.backup-scripts/backup.sh >> /home/deployer/aihealth-deployment/aihealth-server/.backup-scripts/backup.log 2>&1

Save and exit the crontab editor.

5. Verify the Cron Job

To verify that the cron job is working, you can monitor the log file:

tail -f /home/deployer/aihealth-deployment/aihealth-server/.backup-scripts/backup.log

This will show the output of the backup script each time it runs.

6. Test the Script Manually

Ensure the script runs without issues manually:

sudo /home/deployer/aihealth-deployment/aihealth-server/.backup-scripts/backup.sh

If there are any issues, they will need to be resolved before relying on the cron job.

7. Ensure cron Service is Running

Ensure that the cron service is running and enabled on your system:

sudo systemctl status cron

If the service is not running, start and enable it:

sudo systemctl start cron
sudo systemctl enable cron

Notes

- This setup is intended for testing purposes by running the script every minute. For production use, adjust the cron job timing as needed.
- Ensure that the cron service is running and enabled on your system.

