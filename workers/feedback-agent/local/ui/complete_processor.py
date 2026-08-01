import json
import os

import requests
import streamlit as st


API_URL = os.getenv("API_URL", "http://localhost:8001")

EXAMPLE_TOPICS = """[
  {
    "heading": "Global Maturity",
    "description": "How candidate managed complexities of global B2B SaaS to meet diverse regional requirements"
  },
  {
    "heading": "Strategic Thinking",
    "description": "Evidence of long-term vision, market positioning, and outcome-focused decision making vs tactical execution"
  },
  {
    "heading": "Cross-functional Leadership",
    "description": "Ability to influence and collaborate across teams without direct authority"
  }
]"""


st.set_page_config(page_title="Complete Interview Processor", layout="wide")
st.title("Complete Interview Processor")
st.markdown("Process interview transcript + feedback transcript to generate normalized data maps")

st.header("1. Input Interview Transcript")

col1, col2 = st.columns(2)
with col1:
    interview_file = st.file_uploader(
        "Upload Interview Transcript",
        type=["txt", "json"],
        key="interview_uploader",
    )
with col2:
    interview_text = st.text_area(
        "Or Paste Interview Transcript",
        height=200,
        key="interview_text",
    )

st.header("2. Input Feedback Transcript")

col1, col2 = st.columns(2)
with col1:
    feedback_file = st.file_uploader(
        "Upload Feedback Transcript",
        type=["txt", "json"],
        key="feedback_uploader",
    )
with col2:
    feedback_text = st.text_area(
        "Or Paste Feedback Transcript",
        height=200,
        key="feedback_text",
    )

st.header("3. Input Scorecard Topics")
st.markdown("Enter topics as JSON array with `heading` and `description` for each topic.")

topics_json = st.text_area(
    "Scorecard Topics (JSON)",
    height=200,
    placeholder=EXAMPLE_TOPICS,
    key="complete_topics_json",
)

candidate_name = st.text_input(
    "Candidate Name (optional - will auto-detect if empty)",
    placeholder="e.g., Ankit Dalal",
    key="complete_candidate_name",
)

if st.button("Process Complete", type="primary"):
    interview_content = None
    if interview_file:
        interview_content = interview_file.getvalue().decode("utf-8")
    elif interview_text.strip():
        interview_content = interview_text.strip()

    feedback_content = None
    if feedback_file:
        feedback_content = feedback_file.getvalue().decode("utf-8")
    elif feedback_text.strip():
        feedback_content = feedback_text.strip()

    if not interview_content:
        st.error("Please provide an interview transcript")
    elif not feedback_content:
        st.error("Please provide a feedback transcript")
    elif not topics_json.strip():
        st.error("Please enter scorecard topics")
    else:
        try:
            topics = json.loads(topics_json)
            if not isinstance(topics, list):
                st.error("Topics must be a JSON array")
            else:
                with st.spinner("Processing both transcripts in parallel (this may take a couple minutes)..."):
                    try:
                        request_data = {
                            "interview_transcript": interview_content,
                            "feedback_transcript": feedback_content,
                            "topics": topics,
                        }
                        if candidate_name and candidate_name.strip():
                            request_data["candidate_name"] = candidate_name.strip()

                        response = requests.post(
                            f"{API_URL}/process-complete",
                            json=request_data,
                            timeout=300,
                        )
                        response.raise_for_status()
                        result = response.json()
                        st.session_state.complete_result = result
                    except requests.exceptions.ConnectionError:
                        st.error("Cannot connect to API server. Make sure it's running on port 8001")
                    except requests.exceptions.HTTPError as e:
                        st.error(f"API error: {e.response.text}")
                    except Exception as e:
                        st.error(f"Request failed: {e}")
        except json.JSONDecodeError as e:
            st.error(f"Invalid topics JSON: {e}")

if st.session_state.get("complete_result"):
    result = st.session_state.complete_result

    st.divider()
    st.header("4. Results - Normalized Data Maps")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Chunks", len(result["chunk_map"]))
    with col2:
        st.metric("Total Topics", len(result["topic_map"]))

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Topic Overview",
        "Chunk Map",
        "Topic Map",
        "Topic-Chunk Map",
        "Topic-Feedback Map",
    ])

    with tab1:
        st.subheader("Topic Overview")
        for topic_id, topic_info in result["topic_map"].items():
            chunk_ids = result["topic_chunk_map"].get(topic_id, [])
            feedback_items = result["topic_feedback_map"].get(topic_id, [])

            with st.expander(f"**{topic_info['heading']}** ({len(chunk_ids)} chunks, {len(feedback_items)} feedback points)", expanded=True):
                st.markdown(f"*{topic_info['description']}*")
                st.markdown("---")

                if chunk_ids:
                    st.markdown("**Mapped Chunks:**")
                    for cid in chunk_ids:
                        chunk = result["chunk_map"].get(cid, {})
                        st.markdown(f"- Chunk {cid}: {chunk.get('speaker', 'Unknown')} | {chunk.get('time_range', 'N/A')}")

                if feedback_items:
                    st.markdown("**Feedback:**")
                    for i, item in enumerate(feedback_items, 1):
                        sentiment = item.get("sentiment", "neutral")
                        sentiment_icon = {
                            "positive": "+",
                            "negative": "-",
                            "neutral": "~",
                        }.get(sentiment, "~")

                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Point {i} [{sentiment_icon}]:**")
                            if sentiment == "positive":
                                st.success(item["feedback"])
                            elif sentiment == "negative":
                                st.error(item["feedback"])
                            else:
                                st.info(item["feedback"])
                        with col2:
                            st.markdown(f"**Anti-Feedback {i}:**")
                            if sentiment == "positive":
                                st.error(item["antifeedback"])
                            elif sentiment == "negative":
                                st.success(item["antifeedback"])
                            else:
                                st.info(item["antifeedback"])

    with tab2:
        st.subheader("Chunk Map")
        st.markdown("All transcript chunks indexed by ID")
        st.json(result["chunk_map"])

    with tab3:
        st.subheader("Topic Map")
        st.markdown("All topics with their headings and descriptions")
        st.json(result["topic_map"])

    with tab4:
        st.subheader("Topic-Chunk Map")
        st.markdown("Which chunk IDs are mapped to each topic")
        st.json(result["topic_chunk_map"])

    with tab5:
        st.subheader("Topic-Feedback Map")
        st.markdown("Feedback and anti-feedback for each topic")
        st.json(result["topic_feedback_map"])

    st.divider()
    st.header("5. Extract Evidence")
    st.markdown("Extract evidence from interview chunks to support/contradict each feedback point")

    if st.button("Extract Evidence", type="secondary"):
        with st.spinner("Extracting evidence for all feedback points (parallel processing)..."):
            try:
                evidence_response = requests.post(
                    f"{API_URL}/extract-evidence",
                    json=result,
                    timeout=300,
                )
                evidence_response.raise_for_status()
                evidence_result = evidence_response.json()
                st.session_state.evidence_result = evidence_result
            except requests.exceptions.ConnectionError:
                st.error("Cannot connect to API server")
            except requests.exceptions.HTTPError as e:
                st.error(f"API error: {e.response.text}")
            except Exception as e:
                st.error(f"Request failed: {e}")

if st.session_state.get("evidence_result"):
    evidence_result = st.session_state.evidence_result

    st.divider()
    st.header("6. Enriched Feedback with Evidence")

    for item in evidence_result["enriched_feedback"]:
        with st.expander(f"**{item['topic_heading']}** - {item['feedback'][:50]}...", expanded=True):
            col1, col2 = st.columns(2)

            with col1:
                sentiment_icon = {"positive": "+", "negative": "-", "neutral": "~"}.get(item["sentiment"], "~")
                st.markdown(f"**Feedback [{sentiment_icon}]:**")
                if item["sentiment"] == "positive":
                    st.success(item["feedback"])
                elif item["sentiment"] == "negative":
                    st.error(item["feedback"])
                else:
                    st.info(item["feedback"])

                st.markdown("**Evidence:**")
                if item["feedback_evidence"]:
                    for evidence in item["feedback_evidence"]:
                        st.markdown(f"- {evidence}")
                else:
                    st.caption("No supporting evidence found")

            with col2:
                st.markdown("**Anti-Feedback:**")
                if item["sentiment"] == "positive":
                    st.error(item["antifeedback"])
                elif item["sentiment"] == "negative":
                    st.success(item["antifeedback"])
                else:
                    st.info(item["antifeedback"])

                st.markdown("**Evidence:**")
                if item["antifeedback_evidence"]:
                    for evidence in item["antifeedback_evidence"]:
                        st.markdown(f"- {evidence}")
                else:
                    st.caption("No supporting evidence found")

            st.markdown("---")
            st.markdown(f"**Reasoning:** {item['reasoning']}")

    st.subheader("Enriched Feedback JSON")
    with st.expander("View Enriched JSON", expanded=False):
        st.json(evidence_result)

    st.divider()
    st.header("7. Judge Feedback")
    st.markdown("Compare evidence and determine if each feedback is supported or contradicted")

    with st.expander("Role Context (recommended for better judgment)", expanded=True):
        st.markdown("Provide context about the role to help the judge make better decisions.")

        role_col1, role_col2 = st.columns(2)
        with role_col1:
            role_title = st.text_input(
                "Role Title",
                placeholder="e.g., Product Manager",
                key="judge_role_title",
            )
            experience_range = st.text_input(
                "Experience Range",
                placeholder="e.g., 3-6 years",
                key="judge_experience_range",
            )
            must_have_skills = st.text_input(
                "Must-Have Skills (comma-separated)",
                placeholder="e.g., Product Strategy, Stakeholder Management, Data Analysis",
                key="judge_must_have_skills",
            )
            good_to_have_skills = st.text_input(
                "Good-to-Have Skills (comma-separated)",
                placeholder="e.g., SQL, Figma, Machine Learning Basics",
                key="judge_good_to_have_skills",
            )

        with role_col2:
            job_description = st.text_area(
                "Job Description",
                height=100,
                placeholder="Paste the job description here...",
                key="judge_job_description",
            )
            intake_notes = st.text_area(
                "Intake Notes (from hiring manager)",
                height=100,
                placeholder="e.g., Need someone with strong cross-functional collaboration skills...",
                key="judge_intake_notes",
            )

    if st.button("Judge Feedback", type="secondary"):
        with st.spinner("Judging feedback points (parallel processing)..."):
            try:
                role_context = {
                    "role_title": role_title,
                    "experience_range": experience_range,
                    "must_have_skills": [s.strip().strip('"').strip("'") for s in must_have_skills.split(",") if s.strip()] if must_have_skills else [],
                    "good_to_have_skills": [s.strip().strip('"').strip("'") for s in good_to_have_skills.split(",") if s.strip()] if good_to_have_skills else [],
                    "job_description": job_description,
                    "intake_notes": intake_notes,
                }

                judge_request = {
                    "enriched_feedback": evidence_result["enriched_feedback"],
                    "role_context": role_context,
                }

                judge_response = requests.post(
                    f"{API_URL}/judge-feedback",
                    json=judge_request,
                    timeout=300,
                )
                judge_response.raise_for_status()
                judge_result = judge_response.json()
                st.session_state.judge_result = judge_result
            except requests.exceptions.ConnectionError:
                st.error("Cannot connect to API server")
            except requests.exceptions.HTTPError as e:
                st.error(f"API error: {e.response.text}")
            except Exception as e:
                st.error(f"Request failed: {e}")

if st.session_state.get("judge_result"):
    judge_result = st.session_state.judge_result

    st.divider()
    st.header("8. Final Judged Feedback")

    supported_count = sum(1 for item in judge_result["judged_feedback"] if item["evidence_status"] == "supported")
    contradicted_count = sum(1 for item in judge_result["judged_feedback"] if item["evidence_status"] == "contradicted")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Feedback Points", len(judge_result["judged_feedback"]))
    with col2:
        st.metric("Supported", supported_count)
    with col3:
        st.metric("Contradicted", contradicted_count)

    if judge_result.get("role_context_used"):
        rc = judge_result["role_context_used"]
        with st.expander("Role Context Applied", expanded=False):
            st.markdown(f"**Role:** {rc.get('role_title', 'Not specified')} ({rc.get('experience_range', 'Not specified')})")
            if rc.get("must_have_skills"):
                st.markdown(f"**Must-Have Skills:** {', '.join(rc['must_have_skills'])}")
            if rc.get("good_to_have_skills"):
                st.markdown(f"**Good-to-Have Skills:** {', '.join(rc['good_to_have_skills'])}")
            if rc.get("intake_notes"):
                st.markdown(f"**Intake Notes:** {rc['intake_notes'][:200]}..." if len(rc.get('intake_notes', '')) > 200 else f"**Intake Notes:** {rc.get('intake_notes', '')}")

    for item in judge_result["judged_feedback"]:
        status_icon = "✓" if item["evidence_status"] == "supported" else "✗"
        status_color = "green" if item["evidence_status"] == "supported" else "red"

        with st.expander(f"**{item['topic_heading']}** [{status_icon}] - {item['feedback'][:50]}...", expanded=True):
            if item["evidence_status"] == "supported":
                st.success(f"**SUPPORTED**: {item['feedback']}")
            else:
                st.error(f"**CONTRADICTED**: {item['feedback']}")

            st.markdown("**Evidence:**")
            if item["evidence"]:
                for evidence in item["evidence"]:
                    st.markdown(f"- {evidence}")
            else:
                st.caption("No evidence")

            st.markdown("---")
            st.markdown(f"**Judge Reasoning:** {item['reasoning']}")

    st.subheader("Final Judged Feedback JSON")
    with st.expander("View Judged JSON", expanded=False):
        st.json(judge_result)

    st.divider()
    st.subheader("Raw Processing JSON")
    with st.expander("View Complete Raw JSON", expanded=False):
        st.json(result)
