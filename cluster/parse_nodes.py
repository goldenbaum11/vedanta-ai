#!/usr/bin/env python3
"""Read nodes.yaml and print a comma-separated host:port list of workers,
for use as llama-server's --rpc argument. Uses each worker's first listed
interconnect IP (the primary RPC link)."""
import sys
import yaml

path = sys.argv[1] if len(sys.argv) > 1 else "nodes.yaml"
with open(path) as f:
    doc = yaml.safe_load(f)

workers = [n for n in doc["nodes"] if n["role"] == "worker"]
targets = [f"{n['interconnect_ips'][0]}:{n['rpc_port']}" for n in workers]
print(",".join(targets))
