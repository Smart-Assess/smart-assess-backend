#!/bin/bash
alembic revision --autogenerate -m "Made some changes in DB"
alembic upgrade head