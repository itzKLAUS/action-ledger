check:
	uv run --locked ruff check .
	uv run --locked ruff format --check .
	uv run --locked python manage.py makemigrations --check --dry-run
	uv run --locked python manage.py check
	uv run --locked coverage run manage.py test
	uv run --locked coverage report

run:
	uv run --locked python manage.py migrate
	uv run --locked python manage.py runserver
