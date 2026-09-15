from app.services.meeting_intelligence import extract_insights


def test_meeting_intelligence_abstains_without_transcript() -> None:
    result = extract_insights(transcript="")
    assert result["abstained"] is True
    assert result["commitments"] == []
    assert result["next_actions"] == []


def test_meeting_intelligence_keeps_only_cited_phrases() -> None:
    transcript = "We will send the proposal on Friday. The budget is a concern."
    result = extract_insights(transcript=transcript)
    for item in result["commitments"] + result["objections"] + result["risks"] + result["next_actions"]:
        assert item.lower() in transcript.lower() or any(word in transcript.lower() for word in item.lower().split() if len(word) > 3)
    assert result["is_mock"] is True
