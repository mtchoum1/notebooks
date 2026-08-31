"""Read the upstream CSV artifact and write summary statistics as JSON."""

import csv
import json
import statistics

values: list[int] = []

with open("raw_records") as input_file:
    reader = csv.DictReader(input_file)
    for row in reader:
        values.append(int(row["value"]))

summary = {
    "count": len(values),
    "mean": statistics.mean(values),
    "median": statistics.median(values),
    "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
    "min": min(values),
    "max": max(values),
}

with open("summary", "w") as output_file:
    json.dump(summary, output_file, indent=2)
