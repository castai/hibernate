FROM python:3.9

ENV PATH /usr/local/bin:$PATH

ENV PYTHONUNBUFFERED 1

RUN mkdir /app
COPY /app /app
COPY app/pyproject.toml /app
WORKDIR /app

RUN pip install --disable-pip-version-check poetry
RUN poetry config virtualenvs.create false
RUN poetry install --no-root --no-dev --no-interaction --no-ansi

CMD ["python", "main.py"]