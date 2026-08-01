FROM public.ecr.aws/lambda/python:3.11

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY production/ ${LAMBDA_TASK_ROOT}/production/

# intake-core is installed during local dev via pip install -e.
# For Lambda image, vendor it in by copying the package directly.
COPY intake-core-pkg/ ${LAMBDA_TASK_ROOT}/intake_core/

CMD ["production.handler.handler"]
