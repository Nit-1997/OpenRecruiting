import os

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8001")

st.set_page_config(page_title="Round Pipeline Tester", layout="wide")
st.title("Round Pipeline Tester")
st.markdown("Test the feedback processing pipeline with real candidate rounds from Supabase")


@st.cache_data(ttl=60)
def fetch_rounds():
    try:
        resp = requests.get(f"{API_URL}/rounds", timeout=30)
        resp.raise_for_status()
        return resp.json().get("rounds", [])
    except Exception as e:
        st.error(f"Failed to fetch rounds: {e}")
        return []


def fetch_round_details(round_id: str):
    try:
        resp = requests.get(f"{API_URL}/rounds/{round_id}", timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Failed to fetch round details: {e}")
        return None


def process_round(round_id: str):
    try:
        resp = requests.post(f"{API_URL}/rounds/{round_id}/process", timeout=600)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        return {"error": e.response.text}
    except Exception as e:
        return {"error": str(e)}


if st.button("Refresh Rounds", key="refresh_rounds_btn"):
    st.cache_data.clear()
    st.rerun()

rounds = fetch_rounds()

if not rounds:
    st.warning("No candidate rounds found. Make sure the API is running and connected to Supabase.")
    st.stop()

round_options = {
    f"{r['candidate_name']} | {r['round_name']} | {r['role_title']} ({r['processing_status']}) [{r['id'][:8]}]": r["id"]
    for r in rounds
}

st.header("1. Select Candidate Round")

selected_label = st.selectbox(
    "Choose a round to process",
    options=list(round_options.keys()),
    key="round_selector",
)

selected_round_id = round_options[selected_label]

st.divider()
st.header("2. Round Details")

details = fetch_round_details(selected_round_id)

if details:
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Candidate")
        st.markdown(f"**Name:** {details['candidate']['name']}")
        st.markdown(f"**Email:** {details['candidate']['email']}")

    with col2:
        st.subheader("Round")
        round_info = details.get("round") or {}
        st.markdown(f"**Name:** {round_info.get('name', 'N/A')}")
        st.markdown(f"**Duration:** {round_info.get('duration_minutes', 'N/A')} mins")
        st.markdown(f"**Description:** {round_info.get('description', 'N/A')[:100]}..." if round_info.get('description') else "**Description:** N/A")

    with col3:
        st.subheader("Role Context")
        role_ctx = details.get("role_context") or {}
        st.markdown(f"**Role:** {role_ctx.get('role_title', 'N/A')}")
        st.markdown(f"**Location:** {role_ctx.get('location', 'N/A')}")
        st.markdown(f"**Experience:** {role_ctx.get('experience', 'N/A')}")

    st.divider()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        cr = details.get("candidate_round") or {}
        status = cr.get("processing_status", "none")
        status_color = {"none": "gray", "processing": "orange", "completed": "green", "failed": "red"}.get(status, "gray")
        st.metric("Processing Status", status)

    with col2:
        transcript = details.get("transcript") or {}
        st.metric("Transcript Segments", transcript.get("segment_count", 0))

    with col3:
        scorecard = details.get("scorecard") or {}
        st.metric("Scorecard Questions", scorecard.get("question_count", 0))

    with col4:
        bot = details.get("bot")
        has_feedback_ts = "Yes" if bot and bot.get("feedback_started_at") else "No"
        st.metric("Feedback Timestamp", has_feedback_ts)

    with st.expander("Scorecard Questions", expanded=False):
        questions = details.get("scorecard", {}).get("questions", [])
        for q in questions:
            st.markdown(f"**{q['question_number']}. {q['heading']}**")
            st.caption(q.get("description", "No description"))

    transcript = details.get("transcript") or {}
    if not transcript.get("has_segments"):
        st.error("This round has no transcript segments. Cannot process.")
        st.stop()

    scorecard = details.get("scorecard") or {}
    if scorecard.get("question_count", 0) == 0:
        st.error("This round has no scorecard questions. Cannot process.")
        st.stop()

    st.divider()
    st.header("3. Process Pipeline")

    st.info("""
    **Pipeline Steps:**
    1. Fetch transcript segments from Supabase
    2. Split into interview (before feedback timestamp) and feedback (after) sections
    3. Chunk interview semantically and map to scorecard topics
    4. Extract feedback bullets from feedback transcript
    5. Link feedback to evidence from interview chunks
    6. Judge each feedback point (supported/contradicted)
    7. Save results to database
    """)

    if st.button("Process Round", type="primary", key="process_round_btn"):
        with st.spinner("Processing pipeline... This may take 2-5 minutes..."):
            result = process_round(selected_round_id)

        if "error" in result:
            st.error(f"Processing failed: {result['error']}")
        else:
            st.success(f"Processing completed successfully!")
            st.session_state.pipeline_result = result

if st.session_state.get("pipeline_result"):
    result = st.session_state.pipeline_result

    st.divider()
    st.header("4. Pipeline Results")

    complete = result.get("complete_result", {})
    evidence = result.get("evidence_result", {})
    judge = result.get("judge_result", {})
    summary = result.get("summary_result", {})

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Final Summary",
        "Question Summaries",
        "Judged Feedback",
        "Evidence Extraction",
        "Topic Mapping",
        "All Raw JSON"
    ])

    with tab1:
        st.subheader("Final Round Summary")

        rating = summary.get("round_rating", "N/A")
        rating_colors = {
            "strong_yes": "green",
            "yes": "lightgreen",
            "maybe": "orange",
            "no": "red",
            "strong_no": "darkred"
        }
        st.markdown(f"### Round Rating: **:{rating_colors.get(rating, 'gray')}[{rating.upper()}]**")

        st.markdown("---")
        st.subheader("Overall Summary")
        round_summary_text = summary.get("round_summary", "No summary generated")
        st.markdown(round_summary_text if round_summary_text else "_No summary generated_")

        st.markdown("---")
        st.subheader("Competency Snapshots")
        competency_snapshots = summary.get("competency_snapshots", "")
        if competency_snapshots:
            st.markdown(competency_snapshots)
        else:
            st.markdown("_No competency snapshots generated_")

        st.markdown("---")
        st.subheader("Pipeline Statistics")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Chunks Created", len(complete.get("chunk_map", {})))
        with col2:
            st.metric("Topics Mapped", len(complete.get("topic_map", {})))
        with col3:
            st.metric("Feedback Points", len(judge.get("judged_feedback", [])))
        with col4:
            st.metric("Questions Summarized", len(summary.get("question_summaries", [])))

    with tab2:
        st.subheader("Per-Question Summaries")

        question_summaries = summary.get("question_summaries", [])
        if not question_summaries:
            st.warning("No question summaries generated")
        else:
            for qs in question_summaries:
                topic_id = qs.get("topic_id", "")
                topic_heading = qs.get("topic_heading", "Unknown Topic")
                summary_text = qs.get("summary", "No summary")
                evidence_status = qs.get("evidence_status", "none")
                sentiment = qs.get("sentiment", "neutral")

                status_icon = {"supported": "✅", "contradicted": "❌"}.get(evidence_status, "❓")
                sentiment_icon = {"positive": "👍", "negative": "👎", "neutral": "➖"}.get(sentiment, "")

                with st.expander(f"{status_icon} {sentiment_icon} **{topic_heading}** ({topic_id})", expanded=True):
                    st.markdown(f"**Summary:** {summary_text}")
                    st.markdown(f"**Evidence Status:** {evidence_status}")
                    st.markdown(f"**Sentiment:** {sentiment}")

        st.markdown("---")
        st.subheader("Question Summaries JSON")
        st.json(question_summaries)

    with tab3:
        st.subheader("Judged Feedback Details")

        judged = judge.get("judged_feedback", [])

        supported = [f for f in judged if f.get("evidence_status") == "supported"]
        contradicted = [f for f in judged if f.get("evidence_status") == "contradicted"]
        partial = [f for f in judged if f.get("evidence_status") == "partial"]
        no_evidence = [f for f in judged if f.get("evidence_status") in ("none", None)]

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Supported", len(supported))
        with col2:
            st.metric("Contradicted", len(contradicted))
        with col3:
            st.metric("Partial", len(partial))
        with col4:
            st.metric("No Evidence", len(no_evidence))

        st.markdown("---")

        current_topic = None
        for item in judged:
            topic_heading = item.get("topic_heading", "Unknown")

            if topic_heading != current_topic:
                current_topic = topic_heading
                st.markdown(f"### {topic_heading}")

            status = item.get("evidence_status", "none")
            status_icon = {"supported": "✅", "contradicted": "❌", "partial": "⚠️"}.get(status, "❓")
            sentiment = item.get("sentiment", "neutral")
            sentiment_icon = {"positive": "👍", "negative": "👎", "neutral": "➖"}.get(sentiment, "")

            feedback_text = item.get("feedback", "")
            with st.expander(f"{status_icon} {sentiment_icon} {feedback_text[:80]}...", expanded=False):
                st.markdown(f"**Feedback:** {feedback_text}")
                st.markdown(f"**Evidence Status:** {status}")
                st.markdown(f"**Sentiment:** {sentiment}")

                evidence_list = item.get("evidence", [])
                if evidence_list:
                    st.markdown("**Evidence:**")
                    for ev in evidence_list:
                        st.markdown(f"- {ev}")

                reasoning = item.get("reasoning", "")
                if reasoning:
                    st.markdown(f"**Judge Reasoning:** {reasoning}")

        st.markdown("---")
        st.subheader("Judge Result JSON")
        st.json(judge)

    with tab4:
        st.subheader("Evidence Extraction Results")

        enriched = evidence.get("enriched_feedback", [])
        if not enriched:
            st.warning("No enriched feedback found")
        else:
            for item in enriched:
                topic_heading = item.get("topic_heading", "Unknown")
                feedback = item.get("feedback", "")
                antifeedback = item.get("antifeedback", "")
                feedback_evidence = item.get("feedback_evidence", [])
                antifeedback_evidence = item.get("antifeedback_evidence", [])
                reasoning = item.get("reasoning", "")

                with st.expander(f"**{topic_heading}**: {feedback[:60]}...", expanded=False):
                    col1, col2 = st.columns(2)

                    with col1:
                        st.markdown("**Feedback (Original):**")
                        st.markdown(f"> {feedback}")
                        st.markdown("**Evidence FOR feedback:**")
                        if feedback_evidence:
                            for ev in feedback_evidence:
                                st.markdown(f"- {ev}")
                        else:
                            st.markdown("_No evidence found_")

                    with col2:
                        st.markdown("**Antifeedback (Negation):**")
                        st.markdown(f"> {antifeedback}")
                        st.markdown("**Evidence FOR antifeedback:**")
                        if antifeedback_evidence:
                            for ev in antifeedback_evidence:
                                st.markdown(f"- {ev}")
                        else:
                            st.markdown("_No evidence found_")

                    st.markdown("---")
                    st.markdown(f"**Reasoning:** {reasoning}")

        st.markdown("---")
        st.subheader("Evidence Extraction JSON")
        st.json(evidence)

    with tab5:
        st.subheader("Topic Mapping & Chunks")

        chunk_map = complete.get("chunk_map", {})
        topic_map = complete.get("topic_map", {})
        topic_chunk_map = complete.get("topic_chunk_map", {})
        topic_feedback_map = complete.get("topic_feedback_map", {})

        st.markdown(f"**Total Chunks:** {len(chunk_map)}")
        st.markdown(f"**Total Topics:** {len(topic_map)}")

        st.markdown("---")
        st.subheader("Topics and Their Mapped Chunks")

        for topic_id, topic_info in topic_map.items():
            heading = topic_info.get("heading", topic_id)
            description = topic_info.get("description", "")
            chunk_ids = topic_chunk_map.get(topic_id, [])
            feedback_items = topic_feedback_map.get(topic_id, [])

            with st.expander(f"**{topic_id}: {heading}** ({len(chunk_ids)} chunks, {len(feedback_items)} feedback items)", expanded=False):
                st.markdown(f"**Description:** {description}")

                st.markdown("**Mapped Chunk IDs:**")
                st.markdown(f"`{chunk_ids}`" if chunk_ids else "_No chunks mapped_")

                if feedback_items:
                    st.markdown("**Extracted Feedback:**")
                    for fb in feedback_items:
                        sentiment = fb.get("sentiment", "neutral")
                        sentiment_icon = {"positive": "👍", "negative": "👎", "neutral": "➖"}.get(sentiment, "")
                        st.markdown(f"- {sentiment_icon} {fb.get('feedback', '')}")
                        st.markdown(f"  - _Antifeedback:_ {fb.get('antifeedback', '')}")

        st.markdown("---")
        st.subheader("All Chunks")

        for chunk_id, chunk_content in chunk_map.items():
            time_range = chunk_content.get("time_range", "")
            speaker = chunk_content.get("speaker", "Unknown")
            content = chunk_content.get("content", "")

            with st.expander(f"**Chunk {chunk_id}** [{time_range}] - {speaker}", expanded=False):
                st.text(content[:2000] + "..." if len(content) > 2000 else content)

        st.markdown("---")
        st.subheader("Complete Result JSON")
        st.json(complete)

    with tab6:
        st.subheader("All Raw JSON Outputs")

        st.markdown("### Summary Result")
        st.json(summary)

        st.markdown("### Judge Result")
        st.json(judge)

        st.markdown("### Evidence Result")
        st.json(evidence)

        st.markdown("### Complete Result")
        st.json(complete)

        st.markdown("---")
        st.subheader("Full Pipeline Response")
        st.json(result)
