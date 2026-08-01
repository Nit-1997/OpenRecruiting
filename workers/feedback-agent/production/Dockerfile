FROM public.ecr.aws/lambda/python:3.11

# Copy production requirements (not root requirements.txt)
COPY production/requirements.txt .

# Install with prefer-binary to use prebuilt wheels when available
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY production/ ${LAMBDA_TASK_ROOT}/production/

CMD ["production.handler.handler"]
