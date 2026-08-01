import json

import requests
import streamlit as st


API_URL = "http://localhost:8001"

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


st.set_page_config(page_title="Topic Mapper", layout="wide")
st.title("Interview Topic Mapper")
st.markdown("Map transcript chunks to scorecard topics using LLM reasoning")

st.header("1. Input Transcript")

col1, col2 = st.columns(2)
with col1:
    uploaded_file = st.file_uploader(
        "Upload Transcript",
        type=["txt", "json"],
        key="transcript_uploader",
    )
with col2:
    transcript_text = st.text_area(
        "Or Paste Transcript",
        height=200,
        key="transcript_text",
    )

candidate_name = st.text_input(
    "Candidate Name (optional - will auto-detect if empty)",
    placeholder="e.g., Ankit Dalal",
    key="candidate_name",
    help="Leave empty to auto-detect from transcript using AI",
)

st.header("2. Input Scorecard Topics")
st.markdown("Enter topics as JSON array with `heading` and `description` for each topic.")

topics_json = st.text_area(
    "Scorecard Topics (JSON)",
    height=200,
    placeholder=EXAMPLE_TOPICS,
    key="topics_json",
)

if st.button("Map Topics", type="primary"):
    transcript_content = None
    if uploaded_file:
        transcript_content = uploaded_file.getvalue().decode("utf-8")
    elif transcript_text.strip():
        transcript_content = transcript_text.strip()

    if not transcript_content:
        st.error("Please provide a transcript")
    elif not topics_json.strip():
        st.error("Please enter scorecard topics")
    else:
        try:
            topics = json.loads(topics_json)
            if not isinstance(topics, list):
                st.error("Topics must be a JSON array")
            else:
                with st.spinner("Mapping topics (this may take a minute)..."):
                    try:
                        request_data = {
                            "transcript": transcript_content,
                            "topics": topics,
                        }
                        if candidate_name and candidate_name.strip():
                            request_data["candidate_name"] = candidate_name.strip()

                        response = requests.post(
                            f"{API_URL}/map-topics",
                            json=request_data,
                            timeout=180,
                        )
                        response.raise_for_status()
                        result = response.json()
                        st.session_state.mapping_result = result
                    except requests.exceptions.ConnectionError:
                        st.error("Cannot connect to API server. Make sure it's running: `uvicorn src.api.server:app --reload`")
                    except requests.exceptions.HTTPError as e:
                        st.error(f"API error: {e.response.text}")
                    except Exception as e:
                        st.error(f"Request failed: {e}")
        except json.JSONDecodeError as e:
            st.error(f"Invalid topics JSON: {e}")

if st.session_state.get("mapping_result"):
    result = st.session_state.mapping_result

    st.divider()
    st.header("3. Results")

    metadata = result["transcript_metadata"]
    participants = result["participants"]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Candidate", participants["candidate"])
    with col2:
        st.metric("Interviewer", participants["interviewer"])
    with col3:
        st.metric("Duration", f"{metadata['duration_minutes']} min")
    with col4:
        st.metric("Total Chunks", metadata["total_chunks"])

    if participants.get("auto_detected"):
        confidence = participants.get("confidence", "unknown")
        st.info(f"**Auto-detected participants** (confidence: {confidence}): {participants.get('reasoning', '')}")

    if result.get("warnings"):
        for warning in result["warnings"]:
            st.warning(warning)

    st.subheader("Topic Mappings")

    for mapping in result["topic_mappings"]:
        with st.expander(f"**{mapping['heading']}** ({len(mapping['relevant_chunk_ids'])} chunks)", expanded=True):
            st.markdown(f"*{mapping['description']}*")
            st.markdown(f"**Reasoning:** {mapping['reasoning']}")
            st.markdown("---")

            for chunk in mapping["relevant_chunks"]:
                st.markdown(f"**Chunk {chunk['id']}** | {chunk['primary_speaker']} | {chunk['time_range']} | {chunk['token_count']} tokens")
                st.text_area(
                    "content",
                    value=chunk["content"],
                    height=150,
                    disabled=True,
                    key=f"chunk_{mapping['topic_id']}_{chunk['id']}",
                    label_visibility="collapsed",
                )
                st.markdown("---")

    st.subheader("All Chunks Reference")

    with st.expander("View All Chunks", expanded=False):
        for chunk in result["chunks"]:
            st.markdown(f"**Chunk {chunk['id']}** | {chunk['primary_speaker']} | {chunk['time_range']}")
            st.text(chunk["content"][:500] + "..." if len(chunk["content"]) > 500 else chunk["content"])
            st.markdown("---")

    st.subheader("Raw JSON Response")

    with st.expander("View Raw JSON", expanded=False):
        st.json(result)
