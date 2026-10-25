#!/bin/bash
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE multi_test OWNER $POSTGRES_USER;
    \c multi_test
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
