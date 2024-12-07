#!/bin/bash

# Find and kill processes running on port 8000
PORT=8000

# Find the process IDs (PIDs) using the port
PIDS=$(lsof -t -i:$PORT)

if [ -z "$PIDS" ]; then
  echo "No processes found running on port $PORT"
else
  echo "Killing processes running on port $PORT: $PIDS"
  kill -9 $PIDS
fi