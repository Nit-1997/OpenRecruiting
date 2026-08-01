# Real meeting capture with Recall.ai

> Outline. The full post is a follow-on writing effort.

- A bot joins the call, records, transcribes, and calls you back.
- The asterisk nobody can engineer away: it is a cloud service calling your
  laptop, so local development needs a tunnel. Say so plainly in the docs.
- Degrading honestly: distinguishing "no API key" from "key but nothing public to
  call back to", because they fail in completely different ways.
- A security guard that only worked for one company: the ENV=test HMAC bypass was
  gated on the URL containing a vendor domain. For a self-hoster that check can
  never fire. Inverting it to an allow-list of local hosts makes it fail-closed.
