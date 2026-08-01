# A WebRTC voice intake agent

> Outline. The full post is a follow-on writing effort.

- Pipecat + aiortc, and the parts of the pipeline that matter.
- Renaming an assistant is a distributed change: seven files across four services
  must agree, and the backend asserts it at startup because getting it wrong is
  silent -- the bot's own speech gets scored as interviewer feedback.
- The speech-to-text normaliser that could not be mechanically renamed: the old
  name was an invented word, so a fuzzy pattern was safe. "Scout" collides with
  real names, and rewriting a candidate called Scott would corrupt a transcript.
- `network_mode: host` does not work on Docker Desktop, and what to do instead.
