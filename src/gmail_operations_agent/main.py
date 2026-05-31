import os
import asyncio
import logging
from dotenv import load_dotenv

from gmail_operations_agent.auth import authenticate_google
from gmail_operations_agent.gmail_client import GmailClient
from gmail_operations_agent.notion_client import NotionAgentClient
from gmail_operations_agent.sheets_client import SheetsClient
from gmail_operations_agent.ai_analyzer import AIAnalyzer

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

async def process_emails():
    """Main orchestration function to process unread emails."""
    # Load environment variables
    load_dotenv()

    # Verify required environment variables
    notion_db_id = os.getenv("NOTION_DATABASE_ID")
    sheets_id = os.getenv("GOOGLE_SHEETS_ID")
    sheets_range = os.getenv("GOOGLE_SHEETS_RANGE", "Sheet1!A:E")

    if not all([notion_db_id, sheets_id]):
        logger.warning("NOTION_DATABASE_ID or GOOGLE_SHEETS_ID is not set in the environment.")
        logger.warning("Some features might be disabled.")

    logger.info("Authenticating with Google...")
    creds = authenticate_google()
    if not creds:
        logger.error("Failed to authenticate with Google. Exiting.")
        return

    logger.info("Initializing clients...")
    gmail = GmailClient(credentials=creds)
    sheets = SheetsClient(credentials=creds)
    notion = NotionAgentClient()
    ai = AIAnalyzer()

    logger.info("Fetching unread emails...")
    emails = gmail.get_unread_emails(max_results=10)
    
    if not emails:
        logger.info("No unread emails found.")
        return

    logger.info(f"Found {len(emails)} unread email(s). Processing...")

    for email in emails:
        msg_id = email['id']
        subject = email['subject']
        sender = email['sender']
        body = email['body']
        thread_id = email['threadId']
        msg_id_header = email['message_id_header']

        logger.info(f"--- Analyzing Email: '{subject}' from '{sender}' ---")
        
        # 1. Analyze with AI
        analysis = await ai.analyze_email(subject, sender, body)
        
        if not analysis:
            logger.error(f"Failed to analyze email {msg_id}. Skipping.")
            continue
            
        logger.info(f"Analysis complete. Important: {analysis.is_important}")

        # 2. Create Notion Task if required
        if analysis.task_required and notion_db_id:
            title = analysis.task_title or f"Task from {sender}"
            desc = analysis.task_description or "No description provided."
            priority = "High" if analysis.is_important else "Medium"
            
            logger.info(f"Creating Notion Task: {title}")
            notion.create_task(notion_db_id, title, desc, priority)

        # 3. Log to Google Sheets if there's table data
        if analysis.has_table_data and sheets_id:
            # We construct a simple row: [Sender, Subject, Category, Summary, Importance]
            row_data = [
                sender,
                subject,
                analysis.category or "General",
                analysis.table_data_summary or "No summary",
                "High" if analysis.is_important else "Normal"
            ]
            logger.info(f"Appending data to Google Sheets: {row_data}")
            sheets.append_row(sheets_id, sheets_range, row_data)

        # 4. Create Draft Reply if required
        if analysis.draft_reply_required and analysis.draft_reply:
            logger.info("Creating Gmail draft reply...")
            gmail.create_draft_reply(
                thread_id=thread_id,
                original_msg_id_header=msg_id_header,
                to=sender,
                subject=subject,
                body=analysis.draft_reply
            )

        # 5. Mark as read
        logger.info("Marking email as read...")
        gmail.mark_as_read(msg_id)
        
        logger.info("--- Finished Processing Email ---\n")

    logger.info("All emails processed successfully.")

def main():
    """Entry point for the application."""
    asyncio.run(process_emails())

if __name__ == "__main__":
    main()