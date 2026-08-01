FROM public.ecr.aws/lambda/python:3.11

COPY production/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY production/ ${LAMBDA_TASK_ROOT}/production/

CMD ["production.handler.handler"]
