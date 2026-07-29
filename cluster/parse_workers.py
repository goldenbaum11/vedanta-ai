#!/usr/bin/env python3
"""Read nodes.yaml and print one worker per line as 'user@interconnect_ip<TAB>rpc_port',
for use by bootstrap.sh to SSH into each worker and check/start its service."""
import sys
import yaml

path = sys.argv[1] if len(sys.argv) > 1 else "nodes.yaml"
with open(path) as f:
    doc = yaml.safe_load(f)

for n in doc["nodes"]:
    if n["role"] == "worker":
        print(f"{n['user']}@{n['interconnect_ips'][0]}\t{n['rpc_port']}")
