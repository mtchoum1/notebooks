"""Generate a small CSV dataset using only the Python standard library."""

import csv
import os
import time

record_count = int(os.getenv("record_count", "10"))

with open("raw_records", "w", newline="") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(["id", "value"])
    for record_id in range(record_count):
        random_num = int(time.time() * 1000000) % 100 + 1
        writer.writerow([record_id, random_num])
