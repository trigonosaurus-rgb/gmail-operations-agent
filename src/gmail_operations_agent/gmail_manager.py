import base64
import logging
from typing import List, Dict, Any, Optional
from email.message import EmailMessage
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

class GmailClient:
    """Client for interacting with the Gmail API."""
    
    def __init__(self, credentials: Credentials):
        """
        Initializes the Gmail Client.
        
        Args:
            credentials (Credentials): Authenticated Google Credentials object.
        """
        self.service = build('gmail', 'v1', credentials=credentials)

    def get_unread_emails(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Fetches unread emails from the inbox.
        
        Args:
            max_results (int): Maximum number of emails to retrieve.
            
        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing email 'id', 'threadId', 'subject', 'sender', and 'body'.
        """
        try:
            # Query for unread messages in the inbox
            results = self.service.users().messages().list(
                userId='me', 
                labelIds=['INBOX', 'UNREAD'],
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            parsed_emails = []

            for msg in messages:
                msg_id = msg['id']
                # Fetch full message payload
                msg_data = self.service.users().messages().get(
                    userId='me', 
                    id=msg_id, 
                    format='full'
                ).execute()
                
                payload = msg_data.get('payload', {})
                headers = payload.get('headers', [])
                
                # Extract basic headers
                subject = next((header['value'] for header in headers if header['name'].lower() == 'subject'), "No Subject")
                sender = next((header['value'] for header in headers if header['name'].lower() == 'from'), "Unknown Sender")
                message_id_header = next((header['value'] for header in headers if header['name'].lower() == 'message-id'), "")
                
                # Extract body
                body = self._extract_body(payload)
                
                parsed_emails.append({
                    'id': msg_id,
                    'threadId': msg_data['threadId'],
                    'message_id_header': message_id_header,
                    'subject': subject,
                    'sender': sender,
                    'body': body
                })
                
            return parsed_emails

        except HttpError as error:
            logger.error(f"An error occurred while fetching emails: {error}")
            return []

    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """Recursively extracts plain text body from the email payload."""
        body = ""
        if 'parts' in payload:
            for part in payload['parts']:
                if part.get('mimeType') == 'text/plain':
                    data = part.get('body', {}).get('data')
                    if data:
                        body += base64.urlsafe_b64decode(data).decode('utf-8')
                elif 'parts' in part:
                    body += self._extract_body(part)
        else:
            # If there are no parts, the body might be in the main payload
            if payload.get('mimeType') == 'text/plain':
                data = payload.get('body', {}).get('data')
                if data:
                    body = base64.urlsafe_b64decode(data).decode('utf-8')
        return body.strip()

    def mark_as_read(self, msg_id: str) -> bool:
        """
        Removes the 'UNREAD' label from the specified email.
        
        Args:
            msg_id (str): The ID of the email to mark as read.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            self.service.users().messages().modify(
                userId='me',
                id=msg_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
            logger.info(f"Message {msg_id} marked as read.")
            return True
        except HttpError as error:
            logger.error(f"An error occurred while marking message as read: {error}")
            return False

    def create_draft_reply(self, thread_id: str, original_msg_id_header: str, to: str, subject: str, body: str) -> Optional[str]:
        """
        Creates a draft reply in the same thread.
        
        Args:
            thread_id (str): The ID of the thread.
            original_msg_id_header (str): The Message-ID header of the email we're replying to.
            to (str): Recipient email address.
            subject (str): Email subject (usually starts with "Re: ").
            body (str): The content of the draft reply.
            
        Returns:
            Optional[str]: The ID of the created draft, or None if failed.
        """
        try:
            message = EmailMessage()
            message.set_content(body)
            message['To'] = to
            message['Subject'] = subject if subject.startswith("Re:") else f"Re: {subject}"
            
            if original_msg_id_header:
                message['In-Reply-To'] = original_msg_id_header
                message['References'] = original_msg_id_header

            # Encode as base64 urlsafe string
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

            draft = {
                'message': {
                    'raw': encoded_message,
                    'threadId': thread_id
                }
            }
            
            created_draft = self.service.users().drafts().create(
                userId='me',
                body=draft
            ).execute()
            
            draft_id = created_draft.get('id')
            logger.info(f"Draft created successfully. Draft ID: {draft_id}")
            return draft_id

        except HttpError as error:
            logger.error(f"An error occurred while creating draft: {error}")
            return None