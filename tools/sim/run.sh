#!/bin/sh
# Extract the lambdas from the YAML, build + run the simulator in the ESPHome container, check.
# usage: ./run.sh [yaml] [results_dir]
#   The controller logic comes from the C++ core (components/solar_autopilot) when the YAML uses
#   solar_autopilot:, or when CORE=1 is set; otherwise from the YAML's own lambdas (before v3).
set -e
Y=${1:-../../inverter-cyd.yaml}; R=${2:-results}
C=../../components/solar_autopilot
mkdir -p "$R" && rm -f "$R"/*.jsonl   # a failed run must not leave old results to compare
python3 -I extract.py "$Y" gen
DEF=""; SRC=""
if [ -n "$CORE" ] || grep -q '^solar_autopilot:' "$Y"; then DEF="-DUSE_CORE"; SRC="ap/ap_*.cpp"; fi
docker exec esphome sh -c 'rm -rf /tmp/sim && mkdir -p /tmp/sim/gen /tmp/sim/ap'
docker cp sim.cpp esphome:/tmp/sim/sim.cpp
docker cp test_forecast.cpp esphome:/tmp/sim/test_forecast.cpp
docker cp gen/lambdas.inc esphome:/tmp/sim/gen/lambdas.inc
docker cp gen/entities.inc esphome:/tmp/sim/gen/entities.inc
for f in $C/ap_*.h $C/ap_*.cpp $C/autopilot.h; do docker cp "$f" esphome:/tmp/sim/ap/; done
echo "build: ${DEF:-YAML lambdas}"
docker exec esphome sh -c "cd /tmp/sim && g++ -std=c++17 -O2 -Wall -Wno-unused-function $DEF -o sim sim.cpp $SRC && mkdir out && for s in \$(./sim | cut -f1); do ./sim \$s > out/\$s.jsonl; done"
for f in $(docker exec esphome ls /tmp/sim/out); do docker cp esphome:/tmp/sim/out/$f "$R/$f"; done
python3 -I check.py "$R" | tail -1
docker exec esphome sh -c "cd /tmp/sim && g++ -std=c++17 -O2 -Wall -Wextra -o tf test_forecast.cpp ap/ap_forecast.cpp && ./tf"
