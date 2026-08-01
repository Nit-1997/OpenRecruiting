# Turning AWS Lambdas into local containers

> Outline. The full post is a follow-on writing effort.

- A self-hoster has no AWS, but the handlers were fine. Only the trigger needed
  to change.
- The JobInvoker seam: one interface, two transports, selected by env. The
  payload is byte-identical, so nothing about the job logic forks.
- Preserving a Lambda guarantee the handlers depend on: AWS runs one invocation
  per container, and these cache loop-bound async clients in module globals.
  Serving concurrent requests in one process lets two invocations close each
  other's clients. Hence a semaphore.
- "intake" turned out to be two different jobs with different payload shapes.
  One shared target made the second silently 400.
- Prefill and reprocess were gated on an AWS ARN, so they skipped themselves
  entirely under the HTTP transport.
- Taking a baseline test run BEFORE a 161-file rename, and why that is the
  difference between "I broke it" and "it was already broken".
