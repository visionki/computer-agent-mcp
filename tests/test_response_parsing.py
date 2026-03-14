from computer_agent_mcp.response_parsing import extract_json_object, extract_output_text


def test_extract_json_object_parses_fenced_json():
    text = """```json
    {"status":"completed","summary":"done","actions":[]}
    ```"""
    payload = extract_json_object(text)
    assert payload is not None
    assert payload["status"] == "completed"


def test_extract_json_object_returns_none_for_invalid_text():
    assert extract_json_object("not json") is None


def test_extract_output_text_preserves_fragmented_json():
    response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"status":"completed",'},
                    {"type": "output_text", "text": '"summary":"done","image_width":1000,'},
                    {"type": "output_text", "text": '"image_height":500,"actions":[]}'},
                ],
            }
        ]
    }
    text = extract_output_text(response)
    payload = extract_json_object(text)
    assert payload is not None
    assert payload["status"] == "completed"
