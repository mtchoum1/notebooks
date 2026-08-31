"""Generate a small CSV dataset using only the Python standard library."""

import csv
import os
import random

record_count = int(os.getenv("record_count", "10"))
random_seed = int(os.getenv("random_seed", "42"))

random.seed(random_seed)

with open("raw_records", "w", newline="") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(["id", "value"])
    for record_id in range(record_count):
        writer.writerow([record_id, random.randint(1, 100)])
