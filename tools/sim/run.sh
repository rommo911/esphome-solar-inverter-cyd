#!/bin/sh
# Extract the lambdas from the YAML, build + run the simulator in the ESPHome container, check.
# usage: ./run.sh [yaml] [results_dir]
set -e
Y=${1:-../../inverter-cyd.yaml}; R=${2:-results}
python3 -I extract.py "$Y" gen
docker exec esphome mkdir -p /tmp/sim/gen
docker cp sim.cpp esphome:/tmp/sim/sim.cpp
docker cp gen/lambdas.inc esphome:/tmp/sim/gen/lambdas.inc
docker cp gen/entities.inc esphome:/tmp/sim/gen/entities.inc
docker exec esphome sh -c 'cd /tmp/sim && g++ -std=c++17 -O2 -o sim sim.cpp && rm -rf out && mkdir out && for s in $(./sim | cut -f1); do ./sim $s > out/$s.jsonl; done'
mkdir -p "$R"
for f in $(docker exec esphome ls /tmp/sim/out); do docker cp esphome:/tmp/sim/out/$f "$R/$f"; done
python3 -I check.py "$R"
