#!/bin/bash
# Quick PostgreSQL database explorer
# Usage: ./explore_db.sh [command]

export PGPASSWORD='streamflow_dev_pass'
DB_NAME="streamflow_db"
DB_USER="streamflow_user"
DB_HOST="localhost"

if [ -z "$1" ]; then
    echo "=== Streamflow Database Explorer ==="
    echo ""
    echo "Database: $DB_NAME"
    echo "User: $DB_USER"
    echo "Host: $DB_HOST"
    echo ""
    echo "Commands:"
    echo "  ./explore_db.sh tables          - List all tables"
    echo "  ./explore_db.sh count           - Count rows in each table"
    echo "  ./explore_db.sh describe TABLE  - Show table structure"
    echo "  ./explore_db.sh query 'SQL'     - Run custom SQL query"
    echo "  ./explore_db.sh shell           - Open psql shell"
    echo ""
    echo "Examples:"
    echo "  ./explore_db.sh tables"
    echo "  ./explore_db.sh describe stations"
    echo "  ./explore_db.sh query 'SELECT COUNT(*) FROM stations'"
    echo ""
elif [ "$1" == "tables" ]; then
    psql -U $DB_USER -d $DB_NAME -h $DB_HOST -c "\dt"
elif [ "$1" == "count" ]; then
    psql -U $DB_USER -d $DB_NAME -h $DB_HOST << 'EOF'
SELECT 
    schemaname,
    tablename,
    (xpath('/row/cnt/text()', xml_count))[1]::text::int as row_count
FROM (
    SELECT 
        schemaname, 
        tablename,
        query_to_xml(format('SELECT COUNT(*) as cnt FROM %I.%I', schemaname, tablename), false, true, '') as xml_count
    FROM pg_tables
    WHERE schemaname = 'public'
) t
ORDER BY row_count DESC;
EOF
elif [ "$1" == "describe" ]; then
    if [ -z "$2" ]; then
        echo "Usage: ./explore_db.sh describe TABLE_NAME"
        exit 1
    fi
    psql -U $DB_USER -d $DB_NAME -h $DB_HOST -c "\d $2"
elif [ "$1" == "query" ]; then
    if [ -z "$2" ]; then
        echo "Usage: ./explore_db.sh query 'YOUR SQL QUERY'"
        exit 1
    fi
    psql -U $DB_USER -d $DB_NAME -h $DB_HOST -c "$2"
elif [ "$1" == "shell" ]; then
    echo "Opening psql shell... (Type \q to exit)"
    psql -U $DB_USER -d $DB_NAME -h $DB_HOST
else
    echo "Unknown command: $1"
    echo "Run './explore_db.sh' with no arguments to see available commands"
fi
