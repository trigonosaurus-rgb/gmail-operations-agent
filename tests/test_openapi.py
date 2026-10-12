from gmail_operations_agent.api import openapi


def test_frontend_schema_is_up_to_date() -> None:
    """The UI's TypeScript types come from this file.

    Regenerate it with `python -m gmail_operations_agent.api.openapi`, then `npm run gen:api`.
    """
    assert openapi.SCHEMA_FILE.read_text("utf-8") == openapi.render()
