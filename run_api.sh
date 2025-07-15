#!/usr/bin/env bash
export PYTHONPATH=$(pwd)
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload 