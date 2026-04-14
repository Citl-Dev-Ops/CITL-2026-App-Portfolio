FROM python:3.11-slim
WORKDIR /app
COPY run_demo.py /app/run_demo.py
COPY run_demo.sh /app/run_demo.sh
COPY demo_prompt.txt /app/demo_prompt.txt
RUN chmod +x /app/run_demo.sh /app/run_demo.py
ENV OLLAMA_HOST=http://host.docker.internal:11434
ENV OLLAMA_MODEL=citl-custom
CMD ["/app/run_demo.sh"]
