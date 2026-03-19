#!/bin/sh
mkdir -p /input/processed

while true; do
    parsedmarc -c /parsedmarc.ini /input/*.xml /input/*.gz /input/*.zip /input/*.xml.gz --debug 2>&1

    find /input -maxdepth 1 -type f \( -name '*.xml' -o -name '*.gz' -o -name '*.zip' \) \
        -exec mv {} /input/processed/ \;

    find /input/processed -mtime +7 -delete 2>/dev/null

    echo 'Sleeping 30s...'
    sleep 30
done
