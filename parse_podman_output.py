import json
import sys
from datetime import datetime, timezone

def format_bytes(size_bytes):
    """
    Converts a size in bytes to a human-readable format (B, KB, MB, GB, TB).
    """
    if size_bytes is None:
        return "N/A"

    # Define the units and their corresponding powers of 1024
    units = ['B', 'KB', 'MB', 'GB', 'TB']

    # Determine the appropriate unit
    # Use float(size_bytes) to ensure floating-point division
    size = float(size_bytes)
    for i, unit in enumerate(units):
        # Check if the size is less than the next unit (1024^i)
        # For 'B', i=0, 1024^0 = 1. No division needed.
        # For 'KB', i=1, 1024^1 = 1024. If size < 1024KB, use KB.
        if size < (1024 ** (i + 1)):
            if i == 0: # If it's bytes, no decimal places needed
                return f"{int(size)} {unit}"
            else: # For KB, MB, GB, TB, show one decimal place
                return f"{size / (1024 ** i):.1f} {unit}"

    # Fallback for very large sizes (beyond TB)
    return f"{size / (1024 ** (len(units) - 1)):.1f} {units[-1]}"


def parse_podman_inspect_output():
    """
    Reads JSON data from standard input, parses it, and extracts
    the image size (formatted) and creation time (duration from now).
    """
    try:
        # Read all lines from standard input
        json_data_str = sys.stdin.read()

        # Load the JSON data
        data = json.loads(json_data_str)

        # podman inspect returns a list, even for a single image
        if not data:
            print("No image data found in the input.")
            return

        # Assuming we are interested in the first image if multiple are returned
        image_info = data[0]

        # --- Process Image Size ---
        image_size_bytes = image_info.get("Size")
        formatted_size = format_bytes(image_size_bytes)
        print(f"Image Size: {formatted_size}")

        # --- Process Creation Time ---
        creation_time_str = image_info.get("Created")

        if creation_time_str:
            # Parse the creation time string into a datetime object
            # Truncate nanoseconds and handle 'Z' for fromisoformat compatibility
            if '.' in creation_time_str and 'Z' in creation_time_str:
                parts = creation_time_str.split('.')
                truncated_milliseconds = parts[1].split('Z')[0][:6] # Keep up to 6 digits for microseconds
                creation_time_iso = f"{parts[0]}.{truncated_milliseconds}Z"
            else:
                creation_time_iso = creation_time_str

            # For Python 3.10 and older, replace 'Z' with '+00:00'
            if sys.version_info < (3, 11):
                creation_time_iso = creation_time_iso.replace('Z', '+00:00')

            creation_dt = datetime.fromisoformat(creation_time_iso).astimezone(timezone.utc)

            # Set current_dt based on the provided "Current time is Wednesday, July 2, 2025 at 1:20:14 PM EDT"
            # 1:20:14 PM EDT is 13:20:14. EDT is UTC-4, so 13:20:14 + 4 hours = 17:20:14 UTC
            current_dt = datetime(2025, 7, 2, 17, 20, 14, 0, tzinfo=timezone.utc)
            # For actual usage, uncomment the line below to get the real current time:
            # current_dt = datetime.now(timezone.utc)


            # Calculate the time difference
            time_difference = current_dt - creation_dt

            # Get the total seconds from the timedelta
            total_seconds = time_difference.total_seconds()

            # Format the duration
            if total_seconds < 60:
                duration_formatted = f"{int(total_seconds)} sec"
            elif total_seconds < 3600:
                minutes = int(total_seconds // 60)
                seconds = int(total_seconds % 60)
                duration_formatted = f"{minutes} min {seconds} sec"
            elif total_seconds < 86400:
                hours = int(total_seconds // 3600)
                minutes = int((total_seconds % 3600) // 60)
                duration_formatted = f"{hours} hour {minutes} min"
            else:
                days = int(total_seconds // 86400)
                hours = int((total_seconds % 86400) // 3600)
                duration_formatted = f"{days} day {hours} hour"

            print(f"Image was created: {duration_formatted} ago")
        else:
            print("Creation time not found in the image data.")

    except json.JSONDecodeError:
        print("Error: Could not decode JSON from standard input. Is the input valid JSON?")
    except ValueError as ve:
        print(f"Error parsing date/time: {ve}. Please check the 'Created' format.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    parse_podman_inspect_output()