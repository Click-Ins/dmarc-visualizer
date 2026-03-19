# gdrive_poller/Dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install google-auth google-auth-httplib2 google-api-python-client
COPY poll.py .
CMD ["python", "poll.py"]