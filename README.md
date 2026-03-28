# Google Form Filler

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/cincaoais/googleform.git
cd googleform
```

### 2. Install Python

Install Python 3.13 from [python.org](https://www.python.org/downloads/).

If you have other projects on your local machine using a different Python version, it is recommended to use a virtual environment manager such as:

- [uv](https://docs.astral.sh/uv/) - `uv venv && source .venv/bin/activate`
- [pyenv](https://github.com/pyenv/pyenv) - `pyenv install 3.13 && pyenv local 3.13`

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run database migrations

```bash
python manage.py migrate
```

### 5. Start the development server

```bash
python manage.py runserver
```

The app will be available at [http://127.0.0.1:8000](http://127.0.0.1:8000).
