"""openrecruiting-intake-agent: scorecard Lambda for v2 intake sessions.

Input contract: {"session_id": uuid}
Reads from:    intake_sessions.current_answers + form_data + turns
Writes to:     intake_sessions.interview_plan, rounds, feedback_questions
Publishes:     SQS event `intake_v2_completed`
"""
