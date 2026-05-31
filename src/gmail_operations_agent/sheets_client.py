import logging
from typing import List, Any
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

class SheetsClient:
    """Client for interacting with the Google Sheets API."""
    
    def __init__(self, credentials: Credentials):
        """
        Initializes the Sheets Client.
        
        Args:
            credentials (Credentials): Authenticated Google Credentials object.
        """
        self.service = build('sheets', 'v4', credentials=credentials)

    def append_row(self, spreadsheet_id: str, range_name: str, values: List[Any]) -> bool:
        """
        Appends a row of data to the specified spreadsheet.
        
        Args:
            spreadsheet_id (str): The ID of the Google Spreadsheet.
            range_name (str): The A1 notation of a range to search for a logical table of data. 
                              Values are appended after the last row of the table. (e.g., 'Sheet1!A:D')
            values (List[Any]): A list of values representing the row to append.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            body = {
                'values': [values]
            }
            
            result = self.service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption='USER_ENTERED',
                insertDataOption='INSERT_ROWS',
                body=body
            ).execute()
            
            updates = result.get('updates', {})
            updated_cells = updates.get('updatedCells', 0)
            logger.info(f"Successfully appended row to Sheets. {updated_cells} cells updated.")
            return True

        except HttpError as error:
            logger.error(f"An error occurred while appending to Sheets: {error}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error appending to Sheets: {e}")
            return False