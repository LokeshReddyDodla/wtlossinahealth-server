FROM python:3.9.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1\
    PYTHONWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VERSION=1.7.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv"

# prepend poetry and venv to path
ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

RUN apt-get update &&\
    apt-get upgrade -y &&\
    apt-get install -y curl build-essential

# install poetry - respects $POETRY_VERSION & $POETRY_HOME
RUN curl -sSL https://install.python-poetry.org | python -

# copy project requirement files here to ensure they will be cached.
WORKDIR $PYSETUP_PATH
COPY ../../../poetry.lock ../../../pyproject.toml ./

# install runtime deps - uses $POETRY_VIRTUALENVS_IN_PROJECT internally
RUN poetry install --no-dev

# Install Alembic
RUN $VENV_PATH/bin/pip install alembic

COPY . /src
WORKDIR /src

# Set up entrypoint to run migrations before starting the server
# CMD ["sh", "-c", "watchmedo auto-restart --directory=./ --pattern=*.py --recursive -- alembic upgrade head && gunicorn --bind 0.0.0.0:8000 --timeout 0 --workers 3 --threads 2 app.main:app -k uvicorn.workers.UvicornWorker"]
CMD ["sh", "-c", "alembic upgrade head && gunicorn --bind 0.0.0.0:8000 --timeout 0 --workers 3 --threads 2 app.main:app -k uvicorn.workers.UvicornWorker"]
