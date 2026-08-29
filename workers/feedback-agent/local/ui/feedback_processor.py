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

EXAMPLE_FEEDBACK = """[66:50] Sloane: Alright, so that was the interview with Pierce. Let me share my feedback.

Overall, I think Pierce has solid product management experience, particularly in the conversational AI space. He's been doing this for about five years now, which is good.

On the positive side, he demonstrated good outcome focus. He mentioned specific metrics like the $1M ARR at Sarti and the 4-5x increase in API consumption at Gupshup. That's the kind of quantified thinking we need.

However, I have concerns about his global maturity. Most of his experience is India-focused. Even at Gupshup, the AI products were targeting LatAm and MENA, not North America. For our role where customers are predominantly US-based, this could be a gap.

Regarding strategic thinking, he showed some good signs. The way he described the prioritization decision between adding new languages versus new use cases was thoughtful. He used revenue potential as the deciding factor, which aligns with how we think here.

One area I'd flag is cross-functional experience in a matrix organization. He's worked in fairly flat startups. Our org is highly matrixed - you need to influence without authority across sales, GTM, and multiple product lines. I'm not sure he's been tested in that environment.

Communication was clear throughout. He structured his answers well and provided concrete examples when asked.

I'd recommend moving forward to the case study round, but the next interviewer should probe deeper on the matrix organization navigation and global customer experience."""


st.set_page_config(page_title="Feedback Processor", layout="wide")
st.title("Interview Feedback Processor")
st.markdown("Extract, map, condense feedback and generate anti-feedback points")

st.header("1. Input Feedback Transcript")

col1, col2 = st.columns(2)
with col1:
    uploaded_file = st.file_uploader(
        "Upload Feedback Transcript",
        type=["txt", "json"],
        key="feedback_uploader",
    )
with col2:
    transcript_text = st.text_area(
        "Or Paste Feedback Transcript",
        height=200,
        placeholder=EXAMPLE_FEEDBACK,
        key="feedback_text",
    )

st.header("2. Input Scorecard Topics")
st.markdown("Enter topics as JSON array with `heading` and `description` for each topic.")

topics_json = st.text_area(
    "Scorecard Topics (JSON)",
    height=200,
    placeholder=EXAMPLE_TOPICS,
    key="feedback_topics_json",
)

if st.button("Process Feedback", type="primary"):
    transcript_content = None
    if uploaded_file:
        transcript_content = uploaded_file.getvalue().decode("utf-8")
    elif transcript_text.strip():
        transcript_content = transcript_text.strip()

    if not transcript_content:
        st.error("Please provide a feedback transcript")
    elif not topics_json.strip():
        st.error("Please enter scorecard topics")
    else:
        try:
            topics = json.loads(topics_json)
            if not isinstance(topics, list):
                st.error("Topics must be a JSON array")
            else:
                with st.spinner("Processing feedback (this may take a minute)..."):
                    try:
                        request_data = {
                            "transcript": transcript_content,
                            "topics": topics,
                        }

                        response = requests.post(
                            f"{API_URL}/process-feedback",
                            json=request_data,
                            timeout=180,
                        )
                        response.raise_for_status()
                        result = response.json()
                        st.session_state.feedback_result = result
                    except requests.exceptions.ConnectionError:
                        st.error("Cannot connect to API server. Make sure it's running on port 8001")
                    except requests.exceptions.HTTPError as e:
                        st.error(f"API error: {e.response.text}")
                    except Exception as e:
                        st.error(f"Request failed: {e}")
        except json.JSONDecodeError as e:
            st.error(f"Invalid topics JSON: {e}")

if st.session_state.get("feedback_result"):
    result = st.session_state.feedback_result

    st.divider()
    st.header("3. Processed Feedback")

    for topic_result in result["topic_feedback"]:
        with st.expander(f"**{topic_result['heading']}** ({len(topic_result['condensed_feedback'])} points)", expanded=True):
            st.markdown(f"*{topic_result['description']}*")
            st.markdown("---")

            for i, feedback_item in enumerate(topic_result["condensed_feedback"], 1):
                sentiment = feedback_item.get("sentiment", "neutral")
                sentiment_icon = {"positive": "+", "negative": "-", "neutral": "~"}.get(sentiment, "~")

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Feedback {i} [{sentiment_icon}]:**")
                    if sentiment == "positive":
                        st.success(feedback_item["feedback_bullet"])
                    elif sentiment == "negative":
                        st.error(feedback_item["feedback_bullet"])
                    else:
                        st.info(feedback_item["feedback_bullet"])
                with col2:
                    st.markdown(f"**Anti-Feedback {i}:**")
                    if sentiment == "positive":
                        st.error(feedback_item["antifeedback_bullet"])
                    elif sentiment == "negative":
                        st.success(feedback_item["antifeedback_bullet"])
                    else:
                        st.info(feedback_item["antifeedback_bullet"])

            with st.expander("View Raw Extracted Bullets", expanded=False):
                for bullet in topic_result["raw_bullets"]:
                    st.markdown(f"- {bullet}")

    st.subheader("Raw JSON Response")

    with st.expander("View Raw JSON", expanded=False):
        st.json(result)
