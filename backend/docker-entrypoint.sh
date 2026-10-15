#!/bin/sh
set -eu

python -m backend.aidr_signing
exec "$@"
