FROM python:3.10-slim

ENV PATH /usr/local/bin:$PATH

ENV PYTHONUNBUFFERED 1

RUN mkdir /app
COPY /app /app
WORKDIR /app

RUN pip install --disable-pip-version-check poetry
RUN poetry config virtualenvs.create false
RUN poetry install --without dev --no-root --no-interaction --no-ansi

CMD ["python", "main.py"]