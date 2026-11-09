#!/bin/bash
# usage: sample.sh <pid> [n] -- CPU% of one core + RSS, 2s apart
pid=$1; n=${2:-8}; tck=$(getconf CLK_TCK)
for i in $(seq $n); do a=$(awk '{print $14+$15}' /proc/$pid/stat); sleep 2; b=$(awk '{print $14+$15}' /proc/$pid/stat)
echo "cpu=$(( (b-a)*100/(2*tck) ))% rss=$(( $(awk '/VmRSS/{print $2}' /proc/$pid/status)/1024 ))MiB"; done
