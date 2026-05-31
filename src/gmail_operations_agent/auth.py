import os
import logging
from typing import Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Scopes needed for Gmail and Google Sheets
SCOPES = [
    "https://mail.google.com/",  # Read, write, send, and manage emails
    "https://www.googleapis.com/auth/spreadsheets"  # Read and write to Google Sheets
]

def authenticate_google(credentials_file: str = "credentials.json", token_file: str = "token.json") -> Optional[Credentials]:
    """
    Authenticates the user with Google APIs using OAuth2.
    
    This function checks for an existing token.json file. If it doesn't exist or is invalid,
    it initiates an OAuth2 flow using credentials.json to get a new token.
    
    Args:
        credentials_file (str): Path to the OAuth2 credentials JSON file downloaded from Google Cloud Console.
        token_file (str): Path to store/read the generated OAuth2 token.
        
    Returns:
        Credentials: Authenticated Google Credentials object, or None if authentication fails.
    """
    creds = None
    
    # Check if we already have a valid token
    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
            logger.info("Loaded existing Google credentials from token.json")
        except Exception as e:
            logger.warning(f"Failed to load token.json: {e}")

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info("Refreshing expired Google credentials...")
                creds.refresh(Request())
            except Exception as e:
                logger.error(f"Failed to refresh token: {e}")
                creds = None

        if not creds:
            if not os.path.exists(credentials_file):
                logger.error(f"Credentials file '{credentials_file}' not found. "
                             f"Please download it from Google Cloud Console and place it in the root directory.")
                return None
            
            logger.info("Initiating new OAuth flow...")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            # Run local server to capture the auth callback
            creds = flow.run_local_server(port=0)

        # Save the credentials for the next run
        with open(token_file, "w") as token:
            token.write(creds.to_json())
            logger.info(f"Saved new Google credentials to {token_file}")

    return creds

if __name__ == "__main__":
    # Test authentication
    authenticate_google()