import os
import logging
from typing import Optional
from notion_client import Client
from notion_client.errors import APIResponseError

logger = logging.getLogger(__name__)

class NotionAgentClient:
    """Client for interacting with the Notion API."""
    
    def __init__(self, token: Optional[str] = None):
        """
        Initializes the Notion Client.
        
        Args:
            token (str, optional): Notion integration token. Defaults to NOTION_API_KEY environment variable.
        """
        api_token = token or os.getenv("NOTION_API_KEY")
        if not api_token:
            logger.warning("Notion API token not provided. Notion integration will be disabled.")
            self.client = None
        else:
            self.client = Client(auth=api_token)

    def create_task(self, database_id: str, title: str, description: str, priority: str = "Medium") -> bool:
        """
        Creates a new task (page) in the specified Notion database.
        
        Args:
            database_id (str): The ID of the Notion database.
            title (str): Task title.
            description (str): Task description.
            priority (str): Task priority (e.g., 'High', 'Medium', 'Low').
            
        Returns:
            bool: True if successful, False otherwise.
        """
        if not self.client:
            logger.error("Cannot create task: Notion client is not initialized.")
            return False

        try:
            new_page = {
                "parent": {"database_id": database_id},
                "properties": {
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": title
                                }
                            }
                        ]
                    },
                    # Note: 'Priority' property must exist in the Notion database as a Select or similar.
                    # This is a common setup, but might need adjustment based on the actual DB schema.
                    "Priority": {
                        "select": {
                            "name": priority
                        }
                    }
                },
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": description
                                    }
                                }
                            ]
                        }
                    }
                ]
            }

            self.client.pages.create(**new_page)
            logger.info(f"Successfully created task in Notion: '{title}'")
            return True

        except APIResponseError as error:
            logger.error(f"Notion API error: {error}")
            return False
        except Exception as e:
            logger.error(f"Failed to create Notion task: {e}")
            return False