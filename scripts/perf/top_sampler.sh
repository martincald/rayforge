#!/bin/sh
# Serves measure.py's energy samples when it runs under sandbox-exec,
# which may not exec the setuid top. Runs outside the sandbox until
# killed: for each "<pid> <samples>" written to $1/request it runs top
# on that pid and leaves the output in $1/result.
dir=$1
mkdir -p "$dir"
while :; do
    if [ -f "$dir/request" ]; then
        set -- $(cat "$dir/request")
        rm -f "$dir/request"
        top -l "$2" -s 1 -pid "$1" -stats pid,cpu,idlew,power \
            > "$dir/result.tmp" 2>&1
        mv "$dir/result.tmp" "$dir/result"
    fi
    sleep 0.2
done
